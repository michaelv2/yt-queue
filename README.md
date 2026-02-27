# yt-queue

Self-hosted YouTube playlist manager with Whisper transcription, LLM summarization, and triage UI.

YouTube's own tools are terrible for bulk playlist management. yt-queue lets you ingest an entire playlist via bookmarklet, transcribe every video locally with Whisper, summarize and score them with an LLM, then triage — keep, flag, or delete — from a clean interface. Re-ingesting the same playlist is safe; already-transcribed videos are skipped automatically.

---

## Features

- **Bookmarklet ingestion** — one click on any YouTube playlist page sends all video IDs to yt-queue; a dry-run preview bookmarklet lets you inspect what would be ingested before committing
- **Local transcription** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with VAD filtering; audio is cached as OGG Opus so retries skip re-downloading
- **LLM pipeline** — per-video summarization, relevance scoring against custom criteria, and LLM-derived category taxonomy across your full library
- **Triage UI** — review completed batches sorted by relevance score; keep, flag, or mark for deletion; previously-deleted videos surface a warning if re-imported
- **Archive** — searchable, sortable, paginated table with category filter, bulk delete, and per-video transcript/audio access
- **Multi-GPU** — configurable device pool distributes concurrent jobs across GPUs

---

## Requirements

- Python 3.11+
- ffmpeg (system package)
- A Whisper-capable machine (CPU works; CUDA recommended for speed)
- An LLM endpoint: [Ollama](https://ollama.com), OpenAI-compatible API, or Anthropic API

---

## Setup

```bash
git clone https://github.com/michaelv2/yt-queue
cd yt-queue

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `startup.sh`, edit the environment variables for your setup, then run it:

```bash
./startup.sh
```

The server starts on port 9000. Open `http://localhost:9000`.

---

## Configuration

All settings use the `YTQUEUE_` prefix and can be set as environment variables.

| Variable | Default | Notes |
|---|---|---|
| `YTQUEUE_BASE_URL` | `http://localhost:8000` | Injected into bookmarklet JS |
| `YTQUEUE_WHISPER_MODEL` | `base` | `tiny` / `base` / `small` / `medium` / `large-v3` |
| `YTQUEUE_WHISPER_DEVICE` | `auto` | `cpu` / `cuda` / `auto` |
| `YTQUEUE_WHISPER_DEVICES` | _(unset)_ | e.g. `cuda:0,cuda:1` — enables multi-GPU, one job per device |
| `YTQUEUE_WHISPER_COMPUTE_TYPE` | `auto` | `float16` / `int8` / `auto` |
| `YTQUEUE_MAX_CONCURRENT_JOBS` | `2` | Ignored when `WHISPER_DEVICES` is set |
| `YTQUEUE_MAX_DURATION_SECONDS` | `7200` | Videos longer than this are rejected |
| `YTQUEUE_LLM_PROVIDER` | `none` | `none` / `ollama` / `openai` / `anthropic` |
| `YTQUEUE_LLM_MODEL` | _(unset)_ | e.g. `gemma3:27b`, `gpt-4o-mini`, `claude-haiku-4-5-20251001` |
| `YTQUEUE_LLM_BASE_URL` | _(unset)_ | Required for Ollama; optional for OpenAI-compatible endpoints |
| `YTQUEUE_LLM_API_KEY` | _(unset)_ | Required for OpenAI / Anthropic |
| `YTQUEUE_DB_PATH` | `data/ytqueue.db` | SQLite archive |
| `YTQUEUE_AUDIO_DIR` | `data/audio` | Cached OGG Opus files |

---

## Workflow

1. **Install the bookmarklets** — drag both links from the yt-queue home page to your bookmarks bar
2. **Preview** — on a YouTube playlist page, click **yt-queue Preview** to see all extractable video IDs with thumbnails before ingesting
3. **Ingest** — click **yt-queue Playlist** to submit the batch for transcription; already-archived videos are skipped
4. **Triage** — once processing completes you're redirected to the triage view; videos are sorted by relevance score; keep, flag, or mark for deletion
5. **Archive** — browse your full library, filter by category, score by criteria, bulk-delete, or read/copy any transcript

### Categories

After building up a library, click **Categorize** in the archive. The LLM derives ~12 categories from a random sample of your summaries, then assigns every video. Categories appear as filterable badges in the archive table. Re-run any time to regenerate.

---

## Architecture

```
POST /api/batches        →  JobRunner (asyncio, device pool)
                              ↓
                         download (yt-dlp)
                              ↓
                         encode WAV → OGG (ffmpeg, pre-cached)
                              ↓
                         transcribe (faster-whisper)
                              ↓
                         summarize + score (LLM)
                              ↓
                         archive (SQLite / aiosqlite)
```

- **Frontend** — vanilla HTML/CSS/JS, no build step
- **Backend** — FastAPI + aiosqlite (WAL mode, FTS5 full-text search)
- **Jobs** — in-memory; only completed transcripts persist across restarts
- **Audio** — OGG Opus files cached in `data/audio/`; survive transcription failures and enable retry without re-downloading

---

## License

MIT
