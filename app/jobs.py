"""In-memory batch/job store + async pipeline runner."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .config import settings
from .models import Job, JobStatus

log = logging.getLogger(__name__)


class _Cancelled(Exception):
    pass


class JobStore:
    """Thread/async-safe in-memory job store with video_id-per-batch deduplication."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._cancel_flags: set[str] = set()

    def request_cancel(self, job_id: str) -> None:
        self._cancel_flags.add(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        return job_id in self._cancel_flags

    def clear_cancel(self, job_id: str) -> None:
        self._cancel_flags.discard(job_id)

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def create(self, video_id: str, batch_id: str, source_url: str = "") -> Job:
        async with self._lock:
            job = Job.create(video_id=video_id, batch_id=batch_id, source_url=source_url)
            self._jobs[job.id] = job
            return job

    async def update(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def cleanup_expired(self) -> int:
        now = time.time()
        expired = [
            jid
            for jid, j in self._jobs.items()
            if j.status in (JobStatus.completed, JobStatus.cancelled)
            and (now - j.created_at) > settings.job_ttl_seconds
        ]
        for jid in expired:
            self._jobs.pop(jid, None)
        return len(expired)


class BatchStore:
    """In-memory mapping of batch_id → list[job_id] + filter_criteria."""

    def __init__(self):
        self._batches: dict[str, dict] = {}  # batch_id → {job_ids, filter_criteria}

    def create(self, filter_criteria: str = "", skipped: int = 0) -> str:
        batch_id = uuid.uuid4().hex[:16]
        self._batches[batch_id] = {"job_ids": [], "filter_criteria": filter_criteria, "skipped": skipped}
        return batch_id

    def add_job(self, batch_id: str, job_id: str) -> None:
        if batch_id in self._batches:
            self._batches[batch_id]["job_ids"].append(job_id)

    def get(self, batch_id: str) -> dict | None:
        return self._batches.get(batch_id)

    def list_all(self) -> list[dict]:
        return [{"batch_id": k, **v} for k, v in self._batches.items()]


class JobRunner:
    """Runs download→transcribe→summarize→archive pipeline with concurrency limiting."""

    def __init__(self, store: JobStore, batch_store: BatchStore, archive_db=None, llm=None):
        self.store = store
        self.batch_store = batch_store
        self.archive_db = archive_db
        self.llm = llm

        # Build device pool — one slot per GPU (multi-GPU) or N slots for one device (single)
        if settings.whisper_devices:
            devices = [d.strip() for d in settings.whisper_devices.split(",") if d.strip()]
        else:
            devices = [settings.whisper_device] * settings.max_concurrent_jobs
        self._device_pool: asyncio.Queue[str] = asyncio.Queue()
        for d in devices:
            self._device_pool.put_nowait(d)
        log.info(
            "JobRunner device pool: %s",
            devices if len(set(devices)) > 1 else f"{devices[0]} ×{len(devices)}",
        )

    async def submit(self, job: Job, filter_criteria: str = "") -> None:
        asyncio.create_task(self._run(job, filter_criteria))

    async def _run(self, job: Job, filter_criteria: str = "") -> None:
        device = await self._device_pool.get()
        tmp_dir = Path(tempfile.mkdtemp(prefix="ytqueue_", dir=settings.temp_dir))
        try:
            if self.store.is_cancel_requested(job.id):
                raise _Cancelled()
            await self._pipeline(job, tmp_dir, filter_criteria, device=device)
        except _Cancelled:
            log.info("Job %s cancelled", job.id)
            job.status = JobStatus.cancelled
            job.error = None
            await self.store.update(job)
        except Exception as exc:
            log.exception("Job %s failed: %s", job.id, exc)
            job.status = JobStatus.failed
            job.error = str(exc)
            await self.store.update(job)
        finally:
            self.store.clear_cancel(job.id)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            self._device_pool.put_nowait(device)

    async def retry(self, job: Job, filter_criteria: str = "") -> None:
        """Re-queue a failed job. Skips download if the OGG is already cached."""
        job.status = JobStatus.queued
        job.error = None
        job.progress = 0.0
        await self.store.update(job)
        asyncio.create_task(self._run(job, filter_criteria))

    async def _pipeline(self, job: Job, tmp_dir: Path, filter_criteria: str, device: str = "auto") -> None:
        import json
        from . import downloader, transcriber
        from .downloader import _find_ffmpeg

        loop = asyncio.get_running_loop()
        audio_dir = Path(settings.audio_dir)
        audio_dir.mkdir(parents=True, exist_ok=True)
        ogg_file = audio_dir / f"{job.video_id}.ogg"

        def _check_cancel():
            if self.store.is_cancel_requested(job.id):
                raise _Cancelled()

        # Phase 1: Download — skip if a cached OGG already exists
        _check_cancel()
        if ogg_file.exists():
            log.info("Job %s: cached audio found at %s, skipping download", job.id, ogg_file)
            if not job.title or not job.duration:
                job.status = JobStatus.downloading
                job.progress = 0.05
                await self.store.update(job)
                info = await loop.run_in_executor(None, downloader.fetch_info, job.source_url)
                job.title = info["title"]
                job.duration = info["duration"]
                if not job.thumbnail_url and info.get("thumbnail"):
                    job.thumbnail_url = info["thumbnail"]
            transcribe_path = ogg_file
            job.progress = 0.35
            await self.store.update(job)
        else:
            job.status = JobStatus.downloading
            job.progress = 0.1
            await self.store.update(job)

            wav_path, title, duration, thumbnail = await loop.run_in_executor(
                None, downloader.download_audio, job.source_url, job.video_id, tmp_dir
            )
            job.title = title
            job.duration = duration
            job.thumbnail_url = thumbnail
            job.progress = 0.25
            await self.store.update(job)

            # Encode WAV → OGG immediately so audio survives a transcription failure
            ffmpeg_bin = _find_ffmpeg()
            if not ffmpeg_bin:
                log.warning("Job %s: ffmpeg not found, using WAV for transcription", job.id)
                transcribe_path = wav_path
            else:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            [ffmpeg_bin, "-y", "-i", str(wav_path),
                             "-c:a", "libopus", "-b:a", "96k", str(ogg_file)],
                            check=True, capture_output=True,
                        ),
                    )
                    log.info("Job %s: audio pre-cached → %s", job.id, ogg_file)
                    transcribe_path = ogg_file
                except Exception:
                    log.warning("Job %s: OGG encoding failed, falling back to WAV", job.id, exc_info=True)
                    transcribe_path = wav_path

            job.progress = 0.35
            await self.store.update(job)

        # Phase 2: Transcribe
        _check_cancel()
        job.status = JobStatus.transcribing
        job.progress = 0.4
        await self.store.update(job)
        _check_cancel()

        segments = await loop.run_in_executor(
            None, transcriber.transcribe, transcribe_path, device
        )
        _check_cancel()
        job.segments = segments
        job.progress = 0.7
        await self.store.update(job)

        full_text = " ".join(s.text for s in segments)

        # Phase 3: Summarize (non-fatal)
        _check_cancel()
        job.status = JobStatus.summarizing
        job.progress = 0.75
        await self.store.update(job)

        summary = ""
        key_takeaways = []
        relevance_score = None
        if self.llm is not None:
            try:
                llm = self.llm
                result = await loop.run_in_executor(
                    None, llm.summarize, full_text, settings.summary_max_words
                )
                summary = result.get("summary", "") if isinstance(result, dict) else str(result)
                key_takeaways = result.get("takeaways", []) if isinstance(result, dict) else []
                job.summary = summary
                job.key_takeaways = key_takeaways
                await self.store.update(job)
            except Exception:
                log.warning("Summarization failed for job %s", job.id, exc_info=True)

            # Phase 4: Score relevance (non-fatal)
            if summary and filter_criteria:
                try:
                    score_text = f"{job.title}\n\n{summary}" if job.title else summary
                    relevance_score = await loop.run_in_executor(
                        None, llm.score_relevance, score_text, filter_criteria
                    )
                    job.relevance_score = relevance_score
                    await self.store.update(job)
                except Exception:
                    log.warning("Relevance scoring failed for job %s", job.id, exc_info=True)

        job.status = JobStatus.completed
        job.progress = 1.0
        await self.store.update(job)
        log.info("Job %s completed: %d segments", job.id, len(segments))

        # Phase 5: Archive to SQLite (non-fatal)
        if self.archive_db is not None:
            try:
                segments_json = json.dumps(
                    [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
                )
                await self.archive_db.save_transcript(
                    video_id=job.video_id,
                    title=job.title or job.video_id,
                    duration=job.duration or 0.0,
                    youtube_url=job.source_url,
                    full_text=full_text,
                    segments_json=segments_json,
                    created_at=job.created_at,
                    audio_path=f"audio/{job.video_id}.ogg" if ogg_file.exists() else None,
                    summary=summary,
                    key_takeaways=json.dumps(key_takeaways) if key_takeaways else None,
                    relevance_score=relevance_score,
                    batch_id=job.batch_id,
                    thumbnail_url=job.thumbnail_url,
                )
                log.info("Job %s archived to DB", job.id)
            except Exception:
                log.warning("Failed to archive job %s to DB", job.id, exc_info=True)


async def cleanup_loop(store: JobStore, archive_db=None, interval: float = 300) -> None:
    """Periodically remove expired jobs and orphaned audio files."""
    while True:
        await asyncio.sleep(interval)
        removed = await store.cleanup_expired()
        if removed:
            log.info("Cleaned up %d expired jobs", removed)

        # Delete OGG files that have no DB record and no active job,
        # and are older than job_ttl_seconds (i.e. not from a recent failure).
        if archive_db is not None:
            try:
                audio_dir = Path(settings.audio_dir)
                if not audio_dir.exists():
                    continue
                archived_ids = await archive_db.get_archived_video_ids()
                active_ids = {j.video_id for j in store._jobs.values()}
                now = time.time()
                for ogg in audio_dir.glob("*.ogg"):
                    vid = ogg.stem
                    if vid not in archived_ids and vid not in active_ids:
                        if now - ogg.stat().st_mtime > settings.job_ttl_seconds:
                            ogg.unlink(missing_ok=True)
                            log.info("Deleted orphaned audio: %s", ogg.name)
            except Exception:
                log.warning("Orphaned audio cleanup failed", exc_info=True)
