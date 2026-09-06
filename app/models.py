from __future__ import annotations

import enum
import time
import uuid

from pydantic import BaseModel


class JobStatus(str, enum.Enum):
    queued = "queued"
    downloading = "downloading"
    transcribing = "transcribing"
    summarizing = "summarizing"
    completed = "completed"
    failed = "failed"


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class Job(BaseModel):
    id: str
    video_id: str
    batch_id: str
    source_url: str = ""
    status: JobStatus = JobStatus.queued
    progress: float = 0.0
    title: str | None = None
    duration: float | None = None
    error: str | None = None
    segments: list[TranscriptSegment] = []
    created_at: float
    summary: str = ""
    key_takeaways: list[str] = []
    relevance_score: float | None = None
    thumbnail_url: str = ""

    @staticmethod
    def create(video_id: str, batch_id: str, source_url: str = "") -> Job:
        return Job(
            id=uuid.uuid4().hex[:12],
            video_id=video_id,
            batch_id=batch_id,
            source_url=source_url,
            created_at=time.time(),
        )


class BatchSubmitRequest(BaseModel):
    urls: list[str]
    filter_criteria: str = ""


class BatchSubmitResponse(BaseModel):
    batch_id: str
    job_ids: list[str]
    skipped: int = 0


class JobStatusResponse(BaseModel):
    id: str
    video_id: str
    batch_id: str
    status: JobStatus
    progress: float
    title: str | None = None
    duration: float | None = None
    error: str | None = None
    summary: str = ""
    relevance_score: float | None = None


class BatchStatus(BaseModel):
    batch_id: str
    filter_criteria: str
    total: int
    completed: int
    failed: int
    in_progress: int
    skipped: int = 0
    status: str               # pending | processing | complete
    jobs: list[JobStatusResponse]


class TriageEntry(BaseModel):
    id: int
    video_id: str
    title: str
    duration: float
    summary: str
    key_takeaways: list[str] = []
    relevance_score: float | None
    is_flagged: bool
    is_marked_for_deletion: bool
    is_watched: bool = False
    youtube_url: str
    batch_id: str | None
    category: str | None = None
    was_previously_deleted: bool = False
    thumbnail_url: str = ""
    archived_at: float | None = None


# ── Archive models ────────────────────────────────────────────────────────────


class ArchiveEntry(BaseModel):
    id: int
    video_id: str
    title: str
    duration: float
    youtube_url: str
    summary: str | None = None
    key_takeaways: list[str] = []
    relevance_score: float | None = None
    is_flagged: bool = False
    is_marked_for_deletion: bool = False
    is_watched: bool = False
    batch_id: str | None = None
    created_at: float
    archived_at: float
    has_audio: bool = False
    category: str | None = None
    thumbnail_url: str = ""


class ArchiveListResponse(BaseModel):
    items: list[ArchiveEntry]
    total: int


class ArchiveTranscriptResponse(BaseModel):
    id: int
    video_id: str
    title: str
    duration: float
    youtube_url: str
    full_text: str
    segments: list[TranscriptSegment]
    summary: str | None = None
    key_takeaways: list[str] = []
    relevance_score: float | None = None
    is_flagged: bool = False
    batch_id: str | None = None
    created_at: float
    archived_at: float
    audio_url: str | None = None


class ArchiveDeleteRequest(BaseModel):
    ids: list[int]


class ArchiveDeleteResponse(BaseModel):
    deleted: int
