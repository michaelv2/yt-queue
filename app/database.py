"""SQLite archive — persistent transcript + batch storage via aiosqlite."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS batches (
    id            TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    filter_criteria TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    duration        REAL NOT NULL,
    youtube_url     TEXT NOT NULL,
    full_text       TEXT NOT NULL,
    segments_json   TEXT NOT NULL,
    created_at      REAL NOT NULL,
    archived_at     REAL NOT NULL,
    audio_path      TEXT,
    summary         TEXT NOT NULL DEFAULT '',
    keywords        TEXT,
    relevance_score REAL,
    is_flagged      INTEGER NOT NULL DEFAULT 0,
    batch_id        TEXT REFERENCES batches(id)
);

CREATE INDEX IF NOT EXISTS idx_transcripts_archived_at ON transcripts(archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_transcripts_batch_id ON transcripts(batch_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_relevance ON transcripts(relevance_score DESC);
"""

_FTS_SCHEMA = """\
CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    title, full_text, summary,
    content='transcripts', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
    INSERT INTO transcripts_fts(rowid, title, full_text, summary)
    VALUES (new.id, new.title, new.full_text, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, title, full_text, summary)
    VALUES ('delete', old.id, old.title, old.full_text, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, title, full_text, summary)
    VALUES ('delete', old.id, old.title, old.full_text, old.summary);
    INSERT INTO transcripts_fts(rowid, title, full_text, summary)
    VALUES (new.id, new.title, new.full_text, new.summary);
END;
"""


class ArchiveDB:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        try:
            await self._db.executescript(_FTS_SCHEMA)
        except Exception:
            log.warning("FTS5 not available — full-text search disabled")
        # Tombstone table for deleted videos
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS deleted_urls (
                video_id    TEXT PRIMARY KEY,
                youtube_url TEXT NOT NULL,
                title       TEXT,
                deleted_at  REAL NOT NULL
            )
        """)
        # Global category taxonomy
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                name        TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL
            )
        """)
        await self._db.commit()
        # Migrations
        for col, definition in [
            ("is_marked_for_deletion", "INTEGER NOT NULL DEFAULT 0"),
            ("category", "TEXT"),
        ]:
            try:
                await self._db.execute(
                    f"ALTER TABLE transcripts ADD COLUMN {col} {definition}"
                )
                await self._db.commit()
                log.info("Added column %s to transcripts", col)
            except Exception:
                pass  # column already exists
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.commit()
        log.info("Archive DB ready: %s", self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ── Batch methods ─────────────────────────────────────────────────────────

    async def create_batch(self, batch_id: str, filter_criteria: str = "") -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO batches (id, created_at, filter_criteria) VALUES (?, ?, ?)",
            (batch_id, time.time(), filter_criteria),
        )
        await self._db.commit()

    async def update_batch_status(self, batch_id: str, status: str) -> None:
        await self._db.execute(
            "UPDATE batches SET status = ? WHERE id = ?", (status, batch_id)
        )
        await self._db.commit()

    async def list_batches(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM batches ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_batches(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM batches") as cur:
            row = await cur.fetchone()
        return row[0]

    async def count_batch(self, batch_id: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM transcripts WHERE batch_id = ?", (batch_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0]

    async def sample_batch_titles(self, batch_id: str, n: int = 3) -> list[str]:
        async with self._db.execute(
            "SELECT title FROM transcripts WHERE batch_id = ? ORDER BY archived_at DESC LIMIT ?",
            (batch_id, n),
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    # ── Transcript methods ────────────────────────────────────────────────────

    async def save_transcript(
        self,
        video_id: str,
        title: str,
        duration: float,
        youtube_url: str,
        full_text: str,
        segments_json: str,
        created_at: float,
        audio_path: str | None = None,
        summary: str = "",
        relevance_score: float | None = None,
        batch_id: str | None = None,
    ) -> int:
        """Upsert a transcript. Returns the row id."""
        now = time.time()
        async with self._db.execute(
            """INSERT INTO transcripts
                   (video_id, title, duration, youtube_url,
                    full_text, segments_json, created_at, archived_at,
                    audio_path, summary, relevance_score, batch_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(video_id) DO UPDATE SET
                   title=excluded.title,
                   duration=excluded.duration,
                   youtube_url=excluded.youtube_url,
                   full_text=excluded.full_text,
                   segments_json=excluded.segments_json,
                   archived_at=excluded.archived_at,
                   audio_path=COALESCE(excluded.audio_path, transcripts.audio_path),
                   summary=COALESCE(NULLIF(excluded.summary,''), transcripts.summary),
                   relevance_score=COALESCE(excluded.relevance_score, transcripts.relevance_score),
                   batch_id=transcripts.batch_id
               RETURNING id""",
            (video_id, title, duration, youtube_url,
             full_text, segments_json, created_at, now,
             audio_path, summary, relevance_score, batch_id),
        ) as cur:
            row = await cur.fetchone()
        await self._db.commit()
        return row[0]

    async def list_transcripts(
        self, limit: int = 50, offset: int = 0, category: str | None = None
    ) -> list[dict]:
        if category == "_none_":
            where, params = "WHERE category IS NULL", (limit, offset)
            sql = f"""SELECT id, video_id, title, duration, youtube_url,
                      summary, relevance_score, is_flagged, is_marked_for_deletion,
                      batch_id, created_at, archived_at, audio_path, category
               FROM transcripts {where} ORDER BY archived_at DESC LIMIT ? OFFSET ?"""
        elif category is not None:
            where, params = "WHERE category = ?", (category, limit, offset)
            sql = f"""SELECT id, video_id, title, duration, youtube_url,
                      summary, relevance_score, is_flagged, is_marked_for_deletion,
                      batch_id, created_at, archived_at, audio_path, category
               FROM transcripts {where} ORDER BY archived_at DESC LIMIT ? OFFSET ?"""
        else:
            sql = """SELECT id, video_id, title, duration, youtube_url,
                      summary, relevance_score, is_flagged, is_marked_for_deletion,
                      batch_id, created_at, archived_at, audio_path, category
               FROM transcripts ORDER BY archived_at DESC LIMIT ? OFFSET ?"""
            params = (limit, offset)
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_transcript(self, row_id: int) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM transcripts WHERE id = ?", (row_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["segments"] = json.loads(d.pop("segments_json"))
        return d

    async def get_triage(self, batch_id: str) -> list[dict]:
        """Return triage entries for a batch, sorted by relevance_score DESC."""
        async with self._db.execute(
            """SELECT id, video_id, title, duration, summary,
                      relevance_score, is_flagged, is_marked_for_deletion,
                      youtube_url, batch_id
               FROM transcripts
               WHERE batch_id = ?
               ORDER BY relevance_score DESC NULLS LAST, archived_at DESC""",
            (batch_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_batch_texts(self, batch_id: str) -> list[dict]:
        """Return id + full_text for all transcripts in a batch."""
        async with self._db.execute(
            "SELECT id, full_text FROM transcripts WHERE batch_id = ?",
            (batch_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_relevance_score(self, row_id: int, score: float) -> None:
        await self._db.execute(
            "UPDATE transcripts SET relevance_score = ? WHERE id = ?",
            (score, row_id),
        )
        await self._db.commit()

    async def get_summaries_by_ids(self, ids: list[int]) -> list[dict]:
        """Return id, summary, full_text for scoring."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        async with self._db.execute(
            f"SELECT id, summary, full_text FROM transcripts WHERE id IN ({placeholders})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_summary(self, row_id: int, summary: str) -> None:
        await self._db.execute(
            "UPDATE transcripts SET summary = ? WHERE id = ?",
            (summary, row_id),
        )
        await self._db.commit()

    async def set_flagged(self, row_id: int, flagged: bool) -> bool:
        """Toggle is_flagged for a transcript. Returns True if row was found."""
        async with self._db.execute(
            "UPDATE transcripts SET is_flagged = ? WHERE id = ? RETURNING id",
            (1 if flagged else 0, row_id),
        ) as cur:
            row = await cur.fetchone()
        await self._db.commit()
        return row is not None

    async def set_marked_for_deletion(self, row_id: int, marked: bool) -> bool:
        """Toggle is_marked_for_deletion. Returns True if row was found."""
        async with self._db.execute(
            "UPDATE transcripts SET is_marked_for_deletion = ? WHERE id = ? RETURNING id",
            (1 if marked else 0, row_id),
        ) as cur:
            row = await cur.fetchone()
        await self._db.commit()
        return row is not None

    async def delete_transcripts(self, ids: list[int]) -> tuple[int, list[str]]:
        if not ids:
            return 0, []
        placeholders = ",".join("?" * len(ids))
        async with self._db.execute(
            f"SELECT audio_path FROM transcripts WHERE id IN ({placeholders}) AND audio_path IS NOT NULL",
            ids,
        ) as cur:
            audio_rows = await cur.fetchall()
        audio_paths = [r[0] for r in audio_rows]
        # Save tombstones before deleting
        async with self._db.execute(
            f"SELECT video_id, youtube_url, title FROM transcripts WHERE id IN ({placeholders})",
            ids,
        ) as cur:
            to_tombstone = await cur.fetchall()
        now = time.time()
        await self._db.executemany(
            "INSERT OR REPLACE INTO deleted_urls (video_id, youtube_url, title, deleted_at) VALUES (?,?,?,?)",
            [(r[0], r[1], r[2], now) for r in to_tombstone],
        )
        async with self._db.execute(
            f"DELETE FROM transcripts WHERE id IN ({placeholders}) RETURNING id",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        await self._db.commit()
        return len(rows), audio_paths

    async def get_previously_deleted(self, video_ids: list[str]) -> set[str]:
        """Return the subset of video_ids that appear in deleted_urls."""
        if not video_ids:
            return set()
        placeholders = ",".join("?" * len(video_ids))
        async with self._db.execute(
            f"SELECT video_id FROM deleted_urls WHERE video_id IN ({placeholders})",
            video_ids,
        ) as cur:
            rows = await cur.fetchall()
        return {r[0] for r in rows}

    async def count(self, category: str | None = None) -> int:
        if category == "_none_":
            sql, params = "SELECT COUNT(*) FROM transcripts WHERE category IS NULL", ()
        elif category is not None:
            sql, params = "SELECT COUNT(*) FROM transcripts WHERE category = ?", (category,)
        else:
            sql, params = "SELECT COUNT(*) FROM transcripts", ()
        async with self._db.execute(sql, params) as cur:
            row = await cur.fetchone()
        return row[0]

    async def get_archived_video_ids(self) -> set[str]:
        """Return the set of video_ids that have an archived transcript."""
        async with self._db.execute("SELECT video_id FROM transcripts") as cur:
            rows = await cur.fetchall()
        return {r[0] for r in rows}

    async def get_archived_by_video_ids(self, video_ids: list[str]) -> set[str]:
        """Return the subset of video_ids that are already archived."""
        if not video_ids:
            return set()
        placeholders = ",".join("?" * len(video_ids))
        async with self._db.execute(
            f"SELECT video_id FROM transcripts WHERE video_id IN ({placeholders})",
            video_ids,
        ) as cur:
            rows = await cur.fetchall()
        return {r[0] for r in rows}

    # ── Category methods ──────────────────────────────────────────────────────

    async def save_categories(self, cats: list[dict]) -> None:
        """Replace the entire category taxonomy."""
        await self._db.execute("DELETE FROM categories")
        now = time.time()
        await self._db.executemany(
            "INSERT INTO categories (name, description, created_at) VALUES (?, ?, ?)",
            [(c["name"], c.get("description", ""), now) for c in cats],
        )
        await self._db.commit()

    async def get_all_categories(self) -> list[dict]:
        async with self._db.execute(
            "SELECT name, description FROM categories ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def bulk_assign_categories(self, assignments: dict[int, str]) -> None:
        """Update category for multiple transcripts by row id."""
        await self._db.executemany(
            "UPDATE transcripts SET category = ? WHERE id = ?",
            [(cat, tid) for tid, cat in assignments.items()],
        )
        await self._db.commit()

    async def get_summaries_for_taxonomy(self, limit: int = 150) -> list[dict]:
        """Return a random sample of summaries for taxonomy derivation."""
        async with self._db.execute(
            "SELECT id, title, summary FROM transcripts WHERE summary != '' ORDER BY RANDOM() LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_all_for_categorization(self) -> list[dict]:
        """Return id, title, summary for every transcript."""
        async with self._db.execute(
            "SELECT id, title, summary FROM transcripts ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
