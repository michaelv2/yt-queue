# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

yt-queue is a sibling app to DePuzzle. It accepts a batch of YouTube URLs, runs them through yt-dlp + faster-whisper, optionally summarizes and scores their relevance via a pluggable LLM, and presents a triage card view sorted by relevance score.

## Running the Server

**Prerequisites:** Node.js (used by yt-dlp for YouTube signature decryption). NVM-managed installs are auto-detected.

```bash
python -m venv .venv && source .venv/bin/activate
.venv/bin/python3 -m pip install -r requirements.txt  # always use venv pip, not bare pip

# Development
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> **Pip + pyenv pitfall:** With pyenv active, bare `pip install` may install into pyenv's global Python instead of the venv. Always use `.venv/bin/python3 -m pip install` to be safe.

## Environment Configuration

All settings use the `YTQUEUE_` prefix (see `app/config.py`):

| Variable | Default | Notes |
|---|---|---|
| `YTQUEUE_BASE_URL` | `http://localhost:8000` | Server base URL |
| `YTQUEUE_WHISPER_MODEL` | `base` | tiny / base / small / medium / large |
| `YTQUEUE_WHISPER_DEVICE` | `auto` | cpu / cuda / auto |
| `YTQUEUE_MAX_CONCURRENT_JOBS` | `2` | Parallel transcriptions |
| `YTQUEUE_MAX_DURATION_SECONDS` | `7200` | Reject videos longer than this |
| `YTQUEUE_DB_PATH` | `data/ytqueue.db` | SQLite archive |
| `YTQUEUE_AUDIO_DIR` | `data/audio` | Persistent OGG files |
| `YTQUEUE_LLM_PROVIDER` | `none` | none / anthropic / openai / ollama |
| `YTQUEUE_LLM_MODEL` | `""` | e.g. `claude-haiku-4-5-20251001` |
| `YTQUEUE_LLM_API_KEY` | `""` | API key for anthropic/openai |
| `YTQUEUE_LLM_BASE_URL` | `""` | Custom base URL (Ollama: `http://localhost:11434`) |
| `YTQUEUE_SUMMARY_MAX_WORDS` | `80` | Word budget for LLM summaries |

## Architecture

### Pipeline (per video)
1. **Download** — yt-dlp (subprocess CLI), WAV via ffmpeg. Requires Node.js for YouTube JS challenge solving.
2. **Transcribe** — faster-whisper with VAD
3. **Summarize** — LLM.summarize(full_text); non-fatal, empty string on failure
4. **Score** — LLM.score_relevance(summary, criteria) → 0.0–1.0; only if criteria provided
5. **Audio encode** — WAV → OGG Opus (non-fatal)
6. **Archive** — SQLite upsert (non-fatal)

### Core Modules

- **`app/config.py`** — Settings with `YTQUEUE_` prefix
- **`app/models.py`** — Pydantic schemas: Job, Batch, TriageEntry, etc.
- **`app/summarizer.py`** — LLM abstraction: NullLLM, AnthropicLLM, OpenAILLM, OllamaLLM + `get_llm()` factory
- **`app/jobs.py`** — JobStore (in-memory) + BatchStore (in-memory) + JobRunner (pipeline)
- **`app/database.py`** — ArchiveDB: async SQLite, FTS5, `get_triage()`, `set_flagged()`
- **`app/downloader.py`** — yt-dlp wrapper (subprocess CLI, not Python API — the API has player variant bugs). Auto-discovers Node.js via NVM paths for systemd compatibility.
- **`app/transcriber.py`** — Copied from DePuzzle; faster-whisper wrapper
- **`app/main.py`** — FastAPI routes + lifespan

### API Summary

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/batches` | Submit URL list → `{batch_id, job_ids}` |
| GET | `/api/batches/{id}` | Batch status + per-job progress |
| GET | `/api/triage/{batch_id}` | Triage entries sorted by relevance |
| POST | `/api/archive/{id}/flag` | Toggle is_flagged (`?flagged=true/false`) |
| GET | `/api/archive` | Paginated archive |
| GET | `/api/archive/{id}` | Single transcript |
| GET | `/api/archive/{id}/audio` | Stream OGG |
| POST | `/api/archive/delete` | Bulk delete `{ids: []}` |
| GET | `/api/health` | Health check |

### Database Schema

```sql
batches (id, created_at, filter_criteria, status)

transcripts (
  id, video_id UNIQUE, title, duration, youtube_url,
  full_text, segments_json, created_at, archived_at,
  audio_path, summary, keywords,
  relevance_score REAL,    -- 0.0–1.0, NULL if no criteria
  is_flagged BOOLEAN,
  batch_id TEXT
)
```

FTS5 index on `(title, full_text, summary)`.

### Frontend

- `static/index.html` + `app.js` — Batch URL input + criteria + progress polling
- `static/triage.html` + `triage.js` — Card grid by relevance, flag toggle, filter/sort
- `static/archive.html` + `archive.js` — Paginated table, bulk delete

## LLM Setup Examples

```bash
# Anthropic
YTQUEUE_LLM_PROVIDER=anthropic \
YTQUEUE_LLM_API_KEY=sk-ant-... \
YTQUEUE_LLM_MODEL=claude-haiku-4-5-20251001 \
uvicorn app.main:app --reload

# OpenAI
YTQUEUE_LLM_PROVIDER=openai \
YTQUEUE_LLM_API_KEY=sk-... \
YTQUEUE_LLM_MODEL=gpt-4o-mini \
uvicorn app.main:app --reload

# Ollama (local)
YTQUEUE_LLM_PROVIDER=ollama \
YTQUEUE_LLM_MODEL=llama3.2 \
uvicorn app.main:app --reload
```

## Ecosystem

yt-queue is part of a broader personal knowledge and research stack:

- **Memoize** (downstream): Transcribed and summarized video content is a natural information funnel into memoize's second-brain knowledge system, feeding structured learnings, ideas, and decisions into the entity graph.
- **Active projects** (upstream, via `recommend.py`): The `recommend.py` CLI scans `~/projects` and `~/projects_safe` for project directories, extracts descriptions from CLAUDE.md/README.md, combines them with optional goals from `goals.md`, and submits the result as scoring criteria to yt-queue's `/api/archive/score` endpoint. Run on-demand to re-score the archive against current research interests.
