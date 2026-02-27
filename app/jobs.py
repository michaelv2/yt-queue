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


class JobStore:
    """Thread/async-safe in-memory job store with video_id-per-batch deduplication."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def create(self, video_id: str, batch_id: str) -> Job:
        async with self._lock:
            job = Job.create(video_id=video_id, batch_id=batch_id)
            self._jobs[job.id] = job
            return job

    async def update(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def cleanup_expired(self) -> int:
        now = time.time()
        expired = [
            jid
            for jid, j in self._jobs.items()
            if j.status in (JobStatus.completed, JobStatus.failed)
            and (now - j.created_at) > settings.job_ttl_seconds
        ]
        for jid in expired:
            self._jobs.pop(jid, None)
        return len(expired)


class BatchStore:
    """In-memory mapping of batch_id → list[job_id] + filter_criteria."""

    def __init__(self):
        self._batches: dict[str, dict] = {}  # batch_id → {job_ids, filter_criteria}

    def create(self, filter_criteria: str = "") -> str:
        batch_id = uuid.uuid4().hex[:16]
        self._batches[batch_id] = {"job_ids": [], "filter_criteria": filter_criteria}
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
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def submit(self, job: Job, filter_criteria: str = "") -> None:
        asyncio.create_task(self._run(job, filter_criteria))

    async def _run(self, job: Job, filter_criteria: str = "") -> None:
        async with self._semaphore:
            tmp_dir = Path(tempfile.mkdtemp(prefix="ytqueue_", dir=settings.temp_dir))
            try:
                await self._pipeline(job, tmp_dir, filter_criteria)
            except Exception as exc:
                log.exception("Job %s failed: %s", job.id, exc)
                job.status = JobStatus.failed
                job.error = str(exc)
                await self.store.update(job)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    async def _pipeline(self, job: Job, tmp_dir: Path, filter_criteria: str) -> None:
        import json
        from . import downloader, transcriber

        loop = asyncio.get_running_loop()

        # Phase 1: Download
        job.status = JobStatus.downloading
        job.progress = 0.1
        await self.store.update(job)

        audio_path, title, duration = await loop.run_in_executor(
            None, downloader.download_audio, job.video_id, tmp_dir
        )
        job.title = title
        job.duration = duration
        job.progress = 0.35
        await self.store.update(job)

        # Phase 2: Transcribe
        job.status = JobStatus.transcribing
        job.progress = 0.4
        await self.store.update(job)

        segments = await loop.run_in_executor(
            None, transcriber.transcribe, audio_path
        )
        job.segments = segments
        job.progress = 0.7
        await self.store.update(job)

        full_text = " ".join(s.text for s in segments)

        # Phase 3: Summarize (non-fatal)
        job.status = JobStatus.summarizing
        job.progress = 0.75
        await self.store.update(job)

        summary = ""
        relevance_score = None
        if self.llm is not None:
            try:
                llm = self.llm
                summary = await loop.run_in_executor(
                    None, llm.summarize, full_text, settings.summary_max_words
                )
                job.summary = summary
                await self.store.update(job)
            except Exception:
                log.warning("Summarization failed for job %s", job.id, exc_info=True)

            # Phase 4: Score relevance (non-fatal)
            if summary and filter_criteria:
                try:
                    relevance_score = await loop.run_in_executor(
                        None, llm.score_relevance, summary, filter_criteria
                    )
                    job.relevance_score = relevance_score
                    await self.store.update(job)
                except Exception:
                    log.warning("Relevance scoring failed for job %s", job.id, exc_info=True)

        job.status = JobStatus.completed
        job.progress = 1.0
        await self.store.update(job)
        log.info("Job %s completed: %d segments", job.id, len(segments))

        # Phase 5: Convert WAV → OGG Opus (non-fatal)
        saved_audio_path: str | None = None
        try:
            from .downloader import _find_ffmpeg
            ffmpeg_bin = _find_ffmpeg() or "ffmpeg"
            audio_dir = Path(settings.audio_dir)
            audio_dir.mkdir(parents=True, exist_ok=True)
            ogg_file = audio_dir / f"{job.video_id}.ogg"
            await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ffmpeg_bin, "-y", "-i", str(audio_path), "-c:a", "libopus", "-b:a", "96k", str(ogg_file)],
                    check=True, capture_output=True,
                ),
            )
            saved_audio_path = f"audio/{job.video_id}.ogg"
            log.info("Job %s audio saved: %s", job.id, ogg_file)
        except Exception:
            log.warning("Failed to save audio for job %s", job.id, exc_info=True)

        # Phase 6: Archive to SQLite (non-fatal)
        if self.archive_db is not None:
            try:
                segments_json = json.dumps(
                    [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
                )
                await self.archive_db.save_transcript(
                    video_id=job.video_id,
                    title=job.title or job.video_id,
                    duration=job.duration or 0.0,
                    youtube_url=f"https://www.youtube.com/watch?v={job.video_id}",
                    full_text=full_text,
                    segments_json=segments_json,
                    created_at=job.created_at,
                    audio_path=saved_audio_path,
                    summary=summary,
                    relevance_score=relevance_score,
                    batch_id=job.batch_id,
                )
                log.info("Job %s archived to DB", job.id)
            except Exception:
                log.warning("Failed to archive job %s to DB", job.id, exc_info=True)


async def cleanup_loop(store: JobStore, interval: float = 300) -> None:
    """Periodically remove expired jobs."""
    while True:
        await asyncio.sleep(interval)
        removed = await store.cleanup_expired()
        if removed:
            log.info("Cleaned up %d expired jobs", removed)
