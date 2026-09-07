"""FastAPI application — routes + lifespan."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import ArchiveDB
from .jobs import BatchStore, JobRunner, JobStore, cleanup_loop
from pydantic import BaseModel

from .models import (
    ArchiveDeleteRequest,
    ArchiveDeleteResponse,
    ArchiveEntry,
    ArchiveListResponse,
    ArchiveTranscriptResponse,
    BatchStatus,
    BatchSubmitRequest,
    BatchSubmitResponse,
    JobStatus,
    JobStatusResponse,
    TranscriptSegment,
    TriageEntry,
)
from .summarizer import get_llm

def _parse_takeaways(raw) -> list[str]:
    """Parse key_takeaways from DB (JSON string or None) into a list."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_DIR / "static"

# ── Video URL/ID parsing ─────────────────────────────────────────────────────

_YT_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})"),
    re.compile(r"^([A-Za-z0-9_-]{11})$"),
]

_VIMEO_PATTERNS = [
    re.compile(r"vimeo\.com/(\d+)"),
    re.compile(r"player\.vimeo\.com/video/(\d+)"),
]


def parse_video_url(url: str) -> tuple[str, str]:
    """Extract (video_id, source_url) from a YouTube or Vimeo URL.

    video_id is used for dedup and file naming.
    Vimeo IDs are prefixed with 'vimeo_' to avoid collisions with YouTube IDs.
    """
    url = url.strip()
    for pat in _YT_PATTERNS:
        m = pat.search(url)
        if m:
            vid = m.group(1)
            return vid, f"https://www.youtube.com/watch?v={vid}"
    for pat in _VIMEO_PATTERNS:
        m = pat.search(url)
        if m:
            vid = m.group(1)
            return f"vimeo_{vid}", f"https://vimeo.com/{vid}"
    raise ValueError(f"Could not parse video URL: {url}")


def parse_urls(raw: list[str]) -> list[str]:
    """Flatten comma/newline-separated URL lists and strip empties."""
    result = []
    for item in raw:
        for part in re.split(r"[\n,]+", item):
            stripped = part.strip()
            if stripped:
                result.append(stripped)
    return result


# ── App globals ───────────────────────────────────────────────────────────────

store = JobStore()
batch_store = BatchStore()
archive_db = ArchiveDB(settings.db_path)
llm = get_llm(settings)
runner = JobRunner(store, batch_store, archive_db=archive_db, llm=llm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.audio_dir).mkdir(parents=True, exist_ok=True)
    await archive_db.init()
    cleanup_task = asyncio.create_task(cleanup_loop(store, archive_db=archive_db))
    device_info = settings.whisper_devices or settings.whisper_device
    log.info(
        "yt-queue started — model=%s, device=%s, concurrency=%d, llm_provider=%s",
        settings.whisper_model,
        device_info,
        len([d for d in settings.whisper_devices.split(",") if d.strip()])
            if settings.whisper_devices else settings.max_concurrent_jobs,
        settings.llm_provider,
    )
    yield
    cleanup_task.cancel()
    await archive_db.close()


app = FastAPI(title="yt-queue", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.youtube.com", "https://youtu.be", "https://vimeo.com"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


# ── Batch routes ──────────────────────────────────────────────────────────────


@app.get("/api/batches")
async def list_batches(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    batches = await archive_db.list_batches(limit=limit, offset=offset)
    # Annotate each with a video count from the DB
    result = []
    for b in batches:
        count = await archive_db.count_batch(b["id"])
        titles = await archive_db.sample_batch_titles(b["id"], n=3)
        result.append({**b, "count": count, "sample_titles": titles})
    return result


@app.post("/api/batches", status_code=202)
async def create_batch(req: BatchSubmitRequest) -> BatchSubmitResponse:
    urls = parse_urls(req.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    parsed: list[tuple[str, str]] = []  # (video_id, source_url)
    errors: list[str] = []
    for url in urls:
        try:
            parsed.append(parse_video_url(url))
        except ValueError as e:
            errors.append(str(e))

    if not parsed:
        raise HTTPException(status_code=400, detail=f"No valid video URLs. Errors: {errors}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for vid, src in parsed:
        if vid not in seen:
            seen.add(vid)
            unique.append((vid, src))

    # Skip videos already in the archive
    already_archived = await archive_db.get_archived_by_video_ids([v for v, _ in unique])
    new_items = [(vid, src) for vid, src in unique if vid not in already_archived]
    skipped = len(already_archived)
    if skipped:
        log.info("Batch skipping %d already-archived video(s)", skipped)

    batch_id = batch_store.create(filter_criteria=req.filter_criteria, skipped=skipped)
    await archive_db.create_batch(batch_id, filter_criteria=req.filter_criteria)

    job_ids: list[str] = []
    for video_id, source_url in new_items:
        job = await store.create(video_id=video_id, batch_id=batch_id, source_url=source_url)
        batch_store.add_job(batch_id, job.id)
        job_ids.append(job.id)
        await runner.submit(job, filter_criteria=req.filter_criteria)

    return BatchSubmitResponse(batch_id=batch_id, job_ids=job_ids, skipped=skipped)


@app.get("/api/batches/{batch_id}")
async def get_batch_status(batch_id: str) -> BatchStatus:
    batch = batch_store.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    jobs = []
    for jid in batch["job_ids"]:
        job = await store.get(jid)
        if job:
            jobs.append(JobStatusResponse(
                id=job.id,
                video_id=job.video_id,
                batch_id=job.batch_id,
                status=job.status,
                progress=job.progress,
                title=job.title,
                duration=job.duration,
                error=job.error,
                summary=job.summary,
                relevance_score=job.relevance_score,
            ))

    total = len(batch["job_ids"])
    in_progress = sum(1 for j in jobs if j.status not in (JobStatus.completed, JobStatus.failed))
    # Use the DB as source of truth for completed — covers jobs evicted from the in-memory store
    completed = await archive_db.count_batch(batch_id)
    failed = max(0, total - completed - in_progress)

    if in_progress > 0:
        status = "processing"
    elif total == 0:
        status = "pending"
    elif failed == total:
        status = "failed"
    else:
        status = "complete"

    return BatchStatus(
        batch_id=batch_id,
        filter_criteria=batch["filter_criteria"],
        total=total,
        completed=completed,
        failed=failed,
        in_progress=in_progress,
        skipped=batch.get("skipped", 0),
        status=status,
        jobs=jobs,
    )


# ── Job retry ─────────────────────────────────────────────────────────────────


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "failed":
        raise HTTPException(status_code=409, detail=f"Job status is '{job.status}', not failed")
    batch = batch_store.get(job.batch_id)
    filter_criteria = batch["filter_criteria"] if batch else ""
    await runner.retry(job, filter_criteria=filter_criteria)
    return {"job_id": job_id, "status": "queued"}


# ── Summarize route ───────────────────────────────────────────────────────────

_summarize_running: set[str] = set()


async def _run_summarize_batch(batch_id: str) -> None:
    loop = asyncio.get_running_loop()
    try:
        rows = await archive_db.get_batch_texts(batch_id)
        log.info("Re-summarizing %d transcripts for batch %s", len(rows), batch_id)
        for row in rows:
            try:
                result = await loop.run_in_executor(
                    None, llm.summarize, row["full_text"], settings.summary_max_words
                )
                summary = result.get("summary", "") if isinstance(result, dict) else str(result)
                takeaways = result.get("takeaways", []) if isinstance(result, dict) else []
                await archive_db.update_summary(
                    row["id"], summary,
                    key_takeaways=json.dumps(takeaways) if takeaways else None,
                )
            except Exception:
                log.warning("Failed to summarize row %d", row["id"], exc_info=True)
    finally:
        _summarize_running.discard(batch_id)
    log.info("Re-summarization complete for batch %s", batch_id)


@app.post("/api/batches/{batch_id}/summarize", status_code=202)
async def summarize_batch(batch_id: str):
    rows = await archive_db.get_batch_texts(batch_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No transcripts found for this batch")
    if isinstance(llm, __import__('app.summarizer', fromlist=['NullLLM']).NullLLM):
        raise HTTPException(status_code=400, detail="No LLM provider configured (YTQUEUE_LLM_PROVIDER=none)")
    if batch_id in _summarize_running:
        return {"status": "already_running", "batch_id": batch_id, "count": len(rows)}
    _summarize_running.add(batch_id)
    asyncio.create_task(_run_summarize_batch(batch_id))
    return {"status": "started", "batch_id": batch_id, "count": len(rows)}


@app.get("/api/batches/{batch_id}/summarize")
async def summarize_batch_status(batch_id: str):
    return {"batch_id": batch_id, "running": batch_id in _summarize_running}


# ── Triage route ──────────────────────────────────────────────────────────────


def _triage_entry(r: dict, prev_deleted: set[str]) -> TriageEntry:
    return TriageEntry(
        id=r["id"],
        video_id=r["video_id"],
        title=r["title"],
        duration=r["duration"],
        summary=r["summary"] or "",
        key_takeaways=_parse_takeaways(r.get("key_takeaways")),
        relevance_score=r["relevance_score"],
        is_flagged=bool(r["is_flagged"]),
        is_marked_for_deletion=bool(r["is_marked_for_deletion"]),
        is_watched=bool(r.get("is_watched", 0)),
        youtube_url=r["youtube_url"],
        batch_id=r.get("batch_id"),
        category=r.get("category"),
        was_previously_deleted=r["video_id"] in prev_deleted,
        thumbnail_url=r.get("thumbnail_url", ""),
        archived_at=r.get("archived_at"),
    )


@app.get("/api/triage")
async def get_triage_global() -> list[TriageEntry]:
    rows = await archive_db.get_triage()
    video_ids = [r["video_id"] for r in rows]
    prev_deleted = await archive_db.get_previously_deleted(video_ids)
    return [_triage_entry(r, prev_deleted) for r in rows]


@app.get("/api/triage/{batch_id}")
async def get_triage(batch_id: str) -> list[TriageEntry]:
    rows = await archive_db.get_triage(batch_id)
    video_ids = [r["video_id"] for r in rows]
    prev_deleted = await archive_db.get_previously_deleted(video_ids)
    return [_triage_entry(r, prev_deleted) for r in rows]


@app.post("/api/archive/{row_id}/flag")
async def toggle_flag(row_id: int, flagged: bool = Query(...)):
    found = await archive_db.set_flagged(row_id, flagged)
    if not found:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return {"id": row_id, "is_flagged": flagged}


@app.post("/api/archive/{row_id}/mark_delete")
async def toggle_mark_delete(row_id: int, marked: bool = Query(...)):
    found = await archive_db.set_marked_for_deletion(row_id, marked)
    if not found:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return {"id": row_id, "is_marked_for_deletion": marked}


@app.post("/api/archive/{row_id}/watch")
async def toggle_watch(row_id: int, watched: bool = Query(...)):
    found = await archive_db.set_watched(row_id, watched)
    if not found:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return {"id": row_id, "is_watched": watched}


# ── Archive routes ────────────────────────────────────────────────────────────


@app.get("/api/archive")
async def list_archive(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    category: str | None = Query(None),
    tag: str | None = Query(None),
    batch_id: str | None = Query(None),
    sort_col: str = Query("archived_at"),
    sort_dir: str = Query("desc"),
    search: str | None = Query(None),
) -> ArchiveListResponse:
    items = await archive_db.list_transcripts(
        limit=limit, offset=offset, category=category, tag=tag,
        batch_id=batch_id, sort_col=sort_col, sort_dir=sort_dir,
        search=search,
    )
    total = await archive_db.count(category=category, tag=tag, batch_id=batch_id, search=search)
    video_ids = [item["video_id"] for item in items]
    prev_deleted = await archive_db.get_previously_deleted(video_ids) if video_ids else set()
    entries = [
        ArchiveEntry(
            **{k: v for k, v in item.items() if k not in ("audio_path", "key_takeaways", "thumbnail_url")},
            key_takeaways=_parse_takeaways(item.get("key_takeaways")),
            has_audio=bool(item.get("audio_path")),
            thumbnail_url=item.get("thumbnail_url", ""),
            was_previously_deleted=item["video_id"] in prev_deleted,
        )
        for item in items
    ]
    return ArchiveListResponse(items=entries, total=total)


@app.get("/api/archive/{row_id}")
async def get_archive_transcript(row_id: int) -> ArchiveTranscriptResponse:
    record = await archive_db.get_transcript(row_id)
    if not record:
        raise HTTPException(status_code=404, detail="Archived transcript not found")
    audio_url = None
    if record.get("audio_path"):
        audio_file = Path(settings.audio_dir).parent / record["audio_path"]
        if audio_file.exists():
            audio_url = f"/api/archive/{row_id}/audio"
    return ArchiveTranscriptResponse(
        id=record["id"],
        video_id=record["video_id"],
        title=record["title"],
        duration=record["duration"],
        youtube_url=record["youtube_url"],
        full_text=record["full_text"],
        segments=[TranscriptSegment(**s) for s in record["segments"]],
        summary=record.get("summary"),
        key_takeaways=_parse_takeaways(record.get("key_takeaways")),
        relevance_score=record.get("relevance_score"),
        is_flagged=bool(record.get("is_flagged", 0)),
        batch_id=record.get("batch_id"),
        created_at=record["created_at"],
        archived_at=record["archived_at"],
        audio_url=audio_url,
    )


@app.get("/api/archive/{row_id}/audio")
async def get_archive_audio(row_id: int):
    record = await archive_db.get_transcript(row_id)
    if not record or not record.get("audio_path"):
        raise HTTPException(status_code=404, detail="Audio not available")
    audio_file = Path(settings.audio_dir).parent / record["audio_path"]
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(audio_file, media_type="audio/ogg")


class ArchiveScoreRequest(BaseModel):
    criteria: str
    ids: list[int] = []  # empty = score everything
    label: str = ""


_score_running: set[str] = set()


async def _run_score_archive(key: str, ids: list[int], criteria: str, label: str = "") -> None:
    loop = asyncio.get_running_loop()
    await archive_db.set_setting("score_criteria", criteria)
    await archive_db.set_setting("score_criteria_label", label or criteria)
    try:
        rows = await archive_db.get_summaries_by_ids(ids) if ids else await archive_db.get_all_summaries()
        log.info("Scoring %d transcripts against criteria: %s", len(rows), criteria)
        for row in rows:
            text = f"{row['title']}\n\n{row['summary'] or row['full_text'][:1000]}"
            if not text:
                continue
            try:
                score = await loop.run_in_executor(
                    None, llm.score_relevance, text, criteria
                )
                await archive_db.update_relevance_score(row["id"], score)
            except Exception:
                log.warning("Failed to score row %d", row["id"], exc_info=True)
    finally:
        _score_running.discard(key)
    log.info("Archive scoring complete")


@app.post("/api/archive/score", status_code=202)
async def score_archive(req: ArchiveScoreRequest):
    if not req.criteria.strip():
        raise HTTPException(status_code=400, detail="No criteria provided")
    from .summarizer import NullLLM
    if isinstance(llm, NullLLM):
        raise HTTPException(status_code=400, detail="No LLM provider configured")
    key = f"score-{hash(tuple(sorted(req.ids)))}"
    if key in _score_running:
        return {"status": "already_running", "count": len(req.ids)}
    _score_running.add(key)
    asyncio.create_task(_run_score_archive(key, req.ids, req.criteria, req.label))
    return {"status": "started", "count": len(req.ids), "key": key}


@app.get("/api/archive/score/status")
async def score_archive_status():
    return {"running": len(_score_running) > 0}


@app.get("/api/archive/score/criteria")
async def get_score_criteria():
    label = await archive_db.get_setting("score_criteria_label")
    return {"label": label or ""}


@app.post("/api/archive/delete")
async def delete_archive(req: ArchiveDeleteRequest) -> ArchiveDeleteResponse:
    if not req.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    deleted, audio_paths = await archive_db.delete_transcripts(req.ids)
    for ap in audio_paths:
        try:
            (Path(settings.audio_dir).parent / ap).unlink(missing_ok=True)
        except Exception:
            log.warning("Failed to delete audio file: %s", ap)
    return ArchiveDeleteResponse(deleted=deleted)


@app.post("/api/archive/check")
async def check_archived(req: dict):
    """Return the subset of video_ids that are already in the archive."""
    video_ids = req.get("video_ids", [])
    if not video_ids:
        return {"archived": []}
    archived = await archive_db.get_archived_by_video_ids(video_ids)
    return {"archived": sorted(archived)}


# ── Category generation ───────────────────────────────────────────────────────

_categorize_state: dict = {"running": False, "done": 0, "total": 0, "error": ""}


@app.post("/api/categories/generate", status_code=202)
async def generate_categories():
    from .summarizer import NullLLM
    if isinstance(llm, NullLLM):
        raise HTTPException(status_code=400, detail="No LLM provider configured")
    if _categorize_state["running"]:
        raise HTTPException(status_code=409, detail="Categorization already running")
    asyncio.create_task(_run_categorization())
    return {"status": "started"}


@app.get("/api/categories/status")
async def get_categorize_status():
    return _categorize_state


@app.get("/api/categories")
async def list_categories():
    return await archive_db.get_all_categories()


async def _run_categorization():
    _categorize_state.update(running=True, done=0, total=0, error="")
    try:
        loop = asyncio.get_running_loop()

        # Step 1: derive taxonomy from a random sample of summaries
        samples = await archive_db.get_summaries_for_taxonomy(150)
        if not samples:
            _categorize_state["error"] = "No summaries available — run a batch first"
            return
        summaries = [s["summary"] for s in samples if s["summary"]]
        cats = await loop.run_in_executor(None, lambda: llm.derive_taxonomy(summaries, 12))
        if not cats:
            _categorize_state["error"] = "LLM returned an empty taxonomy"
            return
        await archive_db.save_categories(cats)
        category_names = [c["name"] for c in cats]
        log.info("Taxonomy derived: %s", category_names)

        # Step 2: assign every transcript in batches of 25
        all_videos = await archive_db.get_all_for_categorization()
        _categorize_state["total"] = len(all_videos)
        batch_size = 25
        for i in range(0, len(all_videos), batch_size):
            chunk = all_videos[i : i + batch_size]
            assignments = await loop.run_in_executor(
                None, lambda c=chunk: llm.assign_categories_bulk(c, category_names)
            )
            if assignments:
                await archive_db.bulk_assign_categories(assignments)
            _categorize_state["done"] = min(i + batch_size, len(all_videos))
    except Exception as e:
        log.warning("Categorization failed: %s", e, exc_info=True)
        _categorize_state["error"] = str(e)
    finally:
        _categorize_state["running"] = False


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}


# ── Batch preview (dry run) ────────────────────────────────────────────────────

_previews: dict[str, dict] = {}


@app.post("/api/batches/preview")
async def preview_batch(req: BatchSubmitRequest):
    urls = parse_urls(req.urls)
    parsed: list[tuple[str, str]] = []
    errors: list[str] = []
    for url in urls:
        try:
            parsed.append(parse_video_url(url))
        except ValueError as e:
            errors.append(str(e))
    seen: set[str] = set()
    unique = [(vid, src) for vid, src in parsed if not (vid in seen or seen.add(vid))]
    preview_id = uuid.uuid4().hex[:16]
    _previews[preview_id] = {
        "count": len(unique),
        "duplicates": len(parsed) - len(unique),
        "video_ids": [vid for vid, _ in unique],
        "errors": errors,
    }
    return {"preview_id": preview_id}


@app.get("/api/batches/preview/{preview_id}")
async def get_preview(preview_id: str):
    data = _previews.get(preview_id)
    if not data:
        raise HTTPException(status_code=404, detail="Preview not found or expired")
    return data


# ── Bookmarklet ───────────────────────────────────────────────────────────────

_SOURCE_JS = PROJECT_DIR / "source.js"
_SOURCE_TEST_JS = PROJECT_DIR / "source-test.js"


@app.get("/bookmarklet.js")
async def serve_bookmarklet():
    src = _SOURCE_JS.read_text()
    js = src.replace("__SERVER__", settings.base_url.rstrip("/"))
    return Response(content=js, media_type="application/javascript")


@app.get("/bookmarklet-test.js")
async def serve_bookmarklet_test():
    src = _SOURCE_TEST_JS.read_text()
    js = src.replace("__SERVER__", settings.base_url.rstrip("/"))
    return Response(content=js, media_type="application/javascript")


# ── Static files (must be last) ───────────────────────────────────────────────

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
