"""Regression tests for Vimeo support.

Covers: URL parsing, Job model, ArchiveDB thumbnail_url,
API batch/preview/triage/archive endpoints, and downloader signatures.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.database import ArchiveDB
from app.jobs import BatchStore, JobRunner, JobStore
from app.main import app, parse_video_url, parse_urls
from app.models import Job


# ── URL parsing ──────────────────────────────────────────────────────────────


class TestParseVideoUrl:
    """Tests for parse_video_url — the routing layer between raw URLs and
    (video_id, source_url) tuples."""

    # YouTube — standard formats

    def test_youtube_watch_url(self):
        vid, src = parse_video_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"
        assert src == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_short_url(self):
        vid, src = parse_video_url("https://youtu.be/dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"
        assert src == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_embed_url(self):
        vid, src = parse_video_url("https://www.youtube.com/embed/dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"
        assert src == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_watch_with_extra_params(self):
        vid, src = parse_video_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        )
        assert vid == "dQw4w9WgXcQ"

    def test_youtube_bare_id(self):
        vid, src = parse_video_url("dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"
        assert src == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_id_with_hyphens_underscores(self):
        vid, _ = parse_video_url("Ab-_C3d4E5f")
        assert vid == "Ab-_C3d4E5f"

    # Vimeo — standard formats

    def test_vimeo_standard_url(self):
        vid, src = parse_video_url("https://vimeo.com/1076370912")
        assert vid == "vimeo_1076370912"
        assert src == "https://vimeo.com/1076370912"

    def test_vimeo_player_embed(self):
        vid, src = parse_video_url("https://player.vimeo.com/video/1076370912")
        assert vid == "vimeo_1076370912"
        assert src == "https://vimeo.com/1076370912"

    def test_vimeo_with_trailing_path(self):
        """Vimeo URLs with hash/path suffixes (e.g., private links)."""
        vid, src = parse_video_url("https://vimeo.com/1076370912/abc123def")
        assert vid == "vimeo_1076370912"
        assert src == "https://vimeo.com/1076370912"

    def test_vimeo_http(self):
        vid, src = parse_video_url("http://vimeo.com/12345")
        assert vid == "vimeo_12345"
        assert src == "https://vimeo.com/12345"

    def test_vimeo_id_prefix_prevents_collision(self):
        """A Vimeo numeric ID must not collide with a YouTube ID."""
        yt_vid, _ = parse_video_url("dQw4w9WgXcQ")
        vm_vid, _ = parse_video_url("https://vimeo.com/12345")
        assert yt_vid != vm_vid
        assert vm_vid.startswith("vimeo_")

    # Edge cases

    def test_whitespace_stripped(self):
        vid, _ = parse_video_url("  https://vimeo.com/999  \n")
        assert vid == "vimeo_999"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Could not parse video URL"):
            parse_video_url("https://example.com/not-a-video")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_video_url("")

    def test_random_text_raises(self):
        with pytest.raises(ValueError):
            parse_video_url("hello world")


# ── Job model ────────────────────────────────────────────────────────────────


class TestJobModel:
    def test_create_with_source_url(self):
        job = Job.create(
            video_id="vimeo_1076370912",
            batch_id="batch123",
            source_url="https://vimeo.com/1076370912",
        )
        assert job.video_id == "vimeo_1076370912"
        assert job.source_url == "https://vimeo.com/1076370912"
        assert job.thumbnail_url == ""

    def test_create_defaults_source_url_empty(self):
        job = Job.create(video_id="dQw4w9WgXcQ", batch_id="batch123")
        assert job.source_url == ""

    def test_thumbnail_url_default_empty(self):
        job = Job.create(video_id="test", batch_id="b")
        assert job.thumbnail_url == ""


# ── ArchiveDB — thumbnail_url persistence ────────────────────────────────────


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create an in-memory ArchiveDB for testing."""
    db_path = str(tmp_path / "test.db")
    archive = ArchiveDB(db_path)
    await archive.init()
    yield archive
    await archive.close()


@pytest.mark.asyncio
async def test_save_transcript_stores_thumbnail(db):
    row_id = await db.save_transcript(
        video_id="vimeo_123",
        title="Test Vimeo Video",
        duration=120.0,
        youtube_url="https://vimeo.com/123",
        full_text="hello world",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://i.vimeocdn.com/video/123_640.jpg",
    )
    record = await db.get_transcript(row_id)
    assert record["thumbnail_url"] == "https://i.vimeocdn.com/video/123_640.jpg"


@pytest.mark.asyncio
async def test_save_transcript_thumbnail_default_empty(db):
    row_id = await db.save_transcript(
        video_id="yt_abc",
        title="Test YT",
        duration=60.0,
        youtube_url="https://www.youtube.com/watch?v=abc",
        full_text="test",
        segments_json="[]",
        created_at=time.time(),
    )
    record = await db.get_transcript(row_id)
    assert record["thumbnail_url"] == ""


@pytest.mark.asyncio
async def test_upsert_preserves_thumbnail_when_empty(db):
    """On re-insert with empty thumbnail, the existing value should be kept."""
    await db.save_transcript(
        video_id="vimeo_456",
        title="First Insert",
        duration=90.0,
        youtube_url="https://vimeo.com/456",
        full_text="first",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://i.vimeocdn.com/456.jpg",
    )
    # Upsert with empty thumbnail
    row_id = await db.save_transcript(
        video_id="vimeo_456",
        title="Second Insert",
        duration=90.0,
        youtube_url="https://vimeo.com/456",
        full_text="second",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="",
    )
    record = await db.get_transcript(row_id)
    assert record["thumbnail_url"] == "https://i.vimeocdn.com/456.jpg"
    assert record["full_text"] == "second"  # other fields updated


@pytest.mark.asyncio
async def test_upsert_updates_thumbnail_when_provided(db):
    await db.save_transcript(
        video_id="vimeo_789",
        title="Original",
        duration=60.0,
        youtube_url="https://vimeo.com/789",
        full_text="text",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://old.jpg",
    )
    row_id = await db.save_transcript(
        video_id="vimeo_789",
        title="Updated",
        duration=60.0,
        youtube_url="https://vimeo.com/789",
        full_text="text",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://new.jpg",
    )
    record = await db.get_transcript(row_id)
    assert record["thumbnail_url"] == "https://new.jpg"


@pytest.mark.asyncio
async def test_get_triage_includes_thumbnail(db):
    batch_id = "testbatch"
    await db.create_batch(batch_id)
    await db.save_transcript(
        video_id="vimeo_triage",
        title="Triage Test",
        duration=30.0,
        youtube_url="https://vimeo.com/999",
        full_text="content",
        segments_json="[]",
        created_at=time.time(),
        batch_id=batch_id,
        thumbnail_url="https://thumb.jpg",
    )
    rows = await db.get_triage(batch_id)
    assert len(rows) == 1
    assert rows[0]["thumbnail_url"] == "https://thumb.jpg"


@pytest.mark.asyncio
async def test_get_triage_global_includes_thumbnail(db):
    await db.save_transcript(
        video_id="vimeo_global",
        title="Global Triage",
        duration=30.0,
        youtube_url="https://vimeo.com/global",
        full_text="content",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://global-thumb.jpg",
    )
    rows = await db.get_triage()
    assert any(r["thumbnail_url"] == "https://global-thumb.jpg" for r in rows)


@pytest.mark.asyncio
async def test_list_transcripts_includes_thumbnail(db):
    await db.save_transcript(
        video_id="vimeo_list",
        title="List Test",
        duration=30.0,
        youtube_url="https://vimeo.com/list",
        full_text="content",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://list-thumb.jpg",
    )
    rows = await db.list_transcripts()
    assert len(rows) >= 1
    assert any(r["thumbnail_url"] == "https://list-thumb.jpg" for r in rows)


@pytest.mark.asyncio
async def test_save_vimeo_url_in_youtube_url_column(db):
    """The youtube_url column stores any video URL, including Vimeo."""
    row_id = await db.save_transcript(
        video_id="vimeo_555",
        title="Vimeo URL Test",
        duration=45.0,
        youtube_url="https://vimeo.com/555",
        full_text="text",
        segments_json="[]",
        created_at=time.time(),
    )
    record = await db.get_transcript(row_id)
    assert record["youtube_url"] == "https://vimeo.com/555"


# ── JobStore ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_job_store_create_with_source_url():
    store = JobStore()
    job = await store.create(
        video_id="vimeo_100",
        batch_id="b1",
        source_url="https://vimeo.com/100",
    )
    assert job.source_url == "https://vimeo.com/100"
    retrieved = await store.get(job.id)
    assert retrieved.source_url == "https://vimeo.com/100"


# ── Downloader signatures ───────────────────────────────────────────────────


class TestDownloaderSignatures:
    """Verify the downloader functions accept the new parameter shapes."""

    def test_fetch_info_accepts_url(self):
        from app.downloader import fetch_info
        sig = inspect.signature(fetch_info)
        params = list(sig.parameters.keys())
        assert params == ["url"]

    def test_download_audio_accepts_url_and_video_id(self):
        from app.downloader import download_audio
        sig = inspect.signature(download_audio)
        params = list(sig.parameters.keys())
        assert params == ["url", "video_id", "output_dir"]

    def test_download_audio_returns_4_tuple(self):
        """Return annotation should be a 4-tuple (Path, str, float, str)."""
        from app.downloader import download_audio
        ann = inspect.signature(download_audio).return_annotation
        # tuple[Path, str, float, str]
        assert "str" in str(ann)
        assert "float" in str(ann)
        assert "Path" in str(ann)


# ── API integration tests (with mocked runner) ──────────────────────────────


@pytest_asyncio.fixture
async def client():
    """Create a test client with the runner mocked so no downloads happen."""
    from httpx import ASGITransport, AsyncClient

    # Use an in-memory DB for the test
    test_db = ArchiveDB(":memory:")
    await test_db.init()

    # Patch globals
    original_db = app.state if hasattr(app, "state") else None
    import app.main as main_mod

    old_db = main_mod.archive_db
    old_store = main_mod.store
    old_batch_store = main_mod.batch_store
    old_runner = main_mod.runner

    main_mod.archive_db = test_db
    main_mod.store = JobStore()
    main_mod.batch_store = BatchStore()
    main_mod.runner = MagicMock()
    main_mod.runner.submit = AsyncMock()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await test_db.close()
    main_mod.archive_db = old_db
    main_mod.store = old_store
    main_mod.batch_store = old_batch_store
    main_mod.runner = old_runner


@pytest.mark.asyncio
async def test_api_batch_vimeo_urls(client):
    resp = await client.post(
        "/api/batches",
        json={"urls": ["https://vimeo.com/1076370912"], "filter_criteria": ""},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert len(data["job_ids"]) == 1
    assert data["batch_id"]


@pytest.mark.asyncio
async def test_api_batch_youtube_urls_still_work(client):
    resp = await client.post(
        "/api/batches",
        json={
            "urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            "filter_criteria": "",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert len(data["job_ids"]) == 1


@pytest.mark.asyncio
async def test_api_batch_mixed_urls(client):
    resp = await client.post(
        "/api/batches",
        json={
            "urls": [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://vimeo.com/1076370912",
            ],
            "filter_criteria": "",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert len(data["job_ids"]) == 2


@pytest.mark.asyncio
async def test_api_batch_invalid_url_rejected(client):
    resp = await client.post(
        "/api/batches",
        json={"urls": ["https://example.com/not-a-video"], "filter_criteria": ""},
    )
    assert resp.status_code == 400
    assert "No valid video URLs" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_api_batch_mixed_valid_and_invalid(client):
    """Valid URLs should be accepted even if some are invalid."""
    resp = await client.post(
        "/api/batches",
        json={
            "urls": [
                "https://vimeo.com/100",
                "not-a-url",
            ],
            "filter_criteria": "",
        },
    )
    assert resp.status_code == 202
    data = resp.json()
    assert len(data["job_ids"]) == 1


@pytest.mark.asyncio
async def test_api_batch_deduplicates_vimeo(client):
    resp = await client.post(
        "/api/batches",
        json={
            "urls": [
                "https://vimeo.com/12345",
                "https://vimeo.com/12345",
            ],
            "filter_criteria": "",
        },
    )
    assert resp.status_code == 202
    assert len(resp.json()["job_ids"]) == 1


@pytest.mark.asyncio
async def test_api_batch_job_has_source_url(client):
    """Submitted job should carry source_url."""
    import app.main as main_mod

    resp = await client.post(
        "/api/batches",
        json={"urls": ["https://vimeo.com/42"], "filter_criteria": ""},
    )
    data = resp.json()
    job_id = data["job_ids"][0]
    job = await main_mod.store.get(job_id)
    assert job.source_url == "https://vimeo.com/42"
    assert job.video_id == "vimeo_42"


@pytest.mark.asyncio
async def test_api_preview_vimeo_urls(client):
    resp = await client.post(
        "/api/batches/preview",
        json={"urls": ["https://vimeo.com/100", "https://vimeo.com/200"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    preview_id = data["preview_id"]

    resp2 = await client.get(f"/api/batches/preview/{preview_id}")
    assert resp2.status_code == 200
    preview = resp2.json()
    assert preview["count"] == 2
    assert "vimeo_100" in preview["video_ids"]
    assert "vimeo_200" in preview["video_ids"]


@pytest.mark.asyncio
async def test_api_preview_mixed_urls(client):
    resp = await client.post(
        "/api/batches/preview",
        json={
            "urls": [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://vimeo.com/100",
            ]
        },
    )
    preview_id = resp.json()["preview_id"]
    resp2 = await client.get(f"/api/batches/preview/{preview_id}")
    preview = resp2.json()
    assert preview["count"] == 2
    assert "dQw4w9WgXcQ" in preview["video_ids"]
    assert "vimeo_100" in preview["video_ids"]


@pytest.mark.asyncio
async def test_api_triage_includes_thumbnail(client):
    """Triage endpoint should return thumbnail_url from the DB."""
    import app.main as main_mod

    # Seed a transcript directly
    batch_id = "triage_thumb_test"
    await main_mod.archive_db.create_batch(batch_id)
    await main_mod.archive_db.save_transcript(
        video_id="vimeo_triage_api",
        title="Triage Thumbnail Test",
        duration=60.0,
        youtube_url="https://vimeo.com/triage_api",
        full_text="text",
        segments_json="[]",
        created_at=time.time(),
        batch_id=batch_id,
        thumbnail_url="https://thumb.vimeo.com/triage.jpg",
    )

    resp = await client.get(f"/api/triage/{batch_id}")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 1
    assert entries[0]["thumbnail_url"] == "https://thumb.vimeo.com/triage.jpg"


@pytest.mark.asyncio
async def test_api_triage_global_includes_thumbnail(client):
    import app.main as main_mod

    await main_mod.archive_db.save_transcript(
        video_id="vimeo_global_api",
        title="Global Triage Thumb",
        duration=30.0,
        youtube_url="https://vimeo.com/global_api",
        full_text="text",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://global-thumb.vimeo.com/test.jpg",
    )

    resp = await client.get("/api/triage")
    assert resp.status_code == 200
    entries = resp.json()
    match = [e for e in entries if e["video_id"] == "vimeo_global_api"]
    assert len(match) == 1
    assert match[0]["thumbnail_url"] == "https://global-thumb.vimeo.com/test.jpg"


@pytest.mark.asyncio
async def test_api_archive_list_includes_thumbnail(client):
    import app.main as main_mod

    await main_mod.archive_db.save_transcript(
        video_id="vimeo_archive_api",
        title="Archive Thumb Test",
        duration=30.0,
        youtube_url="https://vimeo.com/archive_api",
        full_text="text",
        segments_json="[]",
        created_at=time.time(),
        thumbnail_url="https://archive-thumb.vimeo.com/test.jpg",
    )

    resp = await client.get("/api/archive")
    assert resp.status_code == 200
    data = resp.json()
    match = [i for i in data["items"] if i["video_id"] == "vimeo_archive_api"]
    assert len(match) == 1
    assert match[0]["thumbnail_url"] == "https://archive-thumb.vimeo.com/test.jpg"


@pytest.mark.asyncio
async def test_api_archive_youtube_still_works(client):
    """YouTube URLs submitted through the API should still work end-to-end."""
    import app.main as main_mod

    await main_mod.archive_db.save_transcript(
        video_id="dQw4w9WgXcQ",
        title="YouTube Test",
        duration=212.0,
        youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        full_text="never gonna give you up",
        segments_json="[]",
        created_at=time.time(),
    )

    resp = await client.get("/api/archive")
    assert resp.status_code == 200
    data = resp.json()
    match = [i for i in data["items"] if i["video_id"] == "dQw4w9WgXcQ"]
    assert len(match) == 1
    assert match[0]["youtube_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    # thumbnail_url defaults to empty for YouTube without explicit thumbnail
    assert match[0]["thumbnail_url"] == ""
