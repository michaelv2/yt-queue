# yt-queue

Self-hosted YouTube (and Vimeo) video triage system. Submit a playlist or any page via bookmarklet, transcribe every video locally with Whisper, summarize and score them with an LLM, then triage — keep, flag, or delete — from a clean interface.

YouTube's own tools are terrible for bulk playlist management. yt-queue lets you ingest an entire playlist in one click, process it in the background, and surface only the videos worth watching — sorted by relevance to whatever you're working on.

---

## Features

- **Bookmarklet ingestion** — works on any YouTube page (playlist, single video, channel). One click submits all visible videos; a dry-run preview bookmarklet lets you inspect what would be ingested first
- **Live progress view** — bookmarklet opens a dedicated progress tab showing per-job status, progress bars, queue position, and a "View results" button when done
- **Local transcription** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with VAD filtering; audio is cached as OGG Opus so retries skip re-downloading
- **LLM pipeline** — per-video summarization, relevance scoring against custom criteria, and LLM-derived category taxonomy across your full library
- **Triage UI** — review completed batches sorted by relevance score; flag, mark for deletion, or mark watched; previously-deleted videos surface a warning if re-imported
- **Archive** — searchable, sortable, paginated table with category filter, bulk delete, and per-video transcript and audio access
- **Settings UI** — change Whisper model, LLM provider, and auth settings live from the browser — no restart needed for most changes
- **Password protection** — optional session-based auth; enable/disable and change password from the Settings page or via `setup.sh`
- **Multi-GPU** — configurable device pool distributes concurrent jobs across GPUs
- **Job cancellation** — cancel in-progress transcriptions from the progress page
- **Light/dark theme** — theme toggle in Settings; preference saved locally

<img width="1900" height="1774" alt="Screenshot 2026-02-27 140023" src="https://github.com/user-attachments/assets/75275bc4-d73c-4c85-8d29-a83374c3679d" />

---

## Requirements

- Python 3.11+
- `ffmpeg` (system package — `brew install ffmpeg` / `apt install ffmpeg`, or included via `imageio-ffmpeg`)
- A machine with enough RAM for the Whisper model you choose (CPU works; CUDA recommended)
- Optional: an LLM endpoint ([Ollama](https://ollama.com), OpenAI, or Anthropic) for summaries and scoring

### GPU Support

| Platform | Status | Notes |
|---|---|---|
| **NVIDIA (CUDA)** | ✅ Supported | Set device to `cuda` in Settings |
| **Apple Silicon (Metal)** | 🔄 Preview | Set device to `mps`; requires CTranslate2 5.0+ with MPS support (not yet released) |
| **Intel Arc** | ❌ Not tested | May work via CUDA or OpenCL |

---

## Quick setup

```bash
git clone https://github.com/michaelv2/yt-queue
cd yt-queue
./setup.sh
```

`setup.sh` runs an interactive TUI wizard that:
1. Creates a `.venv` and installs all dependencies
2. Prompts for server URL, Whisper model/device, LLM provider, and password
3. Writes your choices to `.env`
4. Prints the exact `uvicorn` command to start the server

Then start the server:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`, drag both bookmarklets to your bookmarks bar, and you're ready.

---

## Configuration

All settings use the `YTQUEUE_` prefix. They can be set as environment variables, in `.env`, or changed live from **Settings** in the UI (most take effect immediately without a restart).

| Variable | Default | Notes |
|---|---|---|
| `YTQUEUE_BASE_URL` | `http://localhost:8000` | Injected into bookmarklet JS |
| `YTQUEUE_WHISPER_MODEL` | `base` | `tiny` / `base` / `small` / `medium` / `large` |
| `YTQUEUE_WHISPER_DEVICE` | `auto` | `cpu` / `cuda` / `mps` / `auto` |
| `YTQUEUE_WHISPER_DEVICES` | _(unset)_ | e.g. `cuda:0,cuda:1` — multi-GPU, one job per device |
| `YTQUEUE_WHISPER_COMPUTE_TYPE` | `auto` | `float16` / `int8` / `auto` |
| `YTQUEUE_MAX_CONCURRENT_JOBS` | `2` | Ignored when `WHISPER_DEVICES` is set |
| `YTQUEUE_MAX_DURATION_SECONDS` | `7200` | Videos longer than this are rejected |
| `YTQUEUE_LLM_PROVIDER` | `none` | `none` / `ollama` / `openai` / `anthropic` |
| `YTQUEUE_LLM_MODEL` | _(unset)_ | e.g. `llama3.2`, `gpt-4o-mini`, `claude-haiku-4-5-20251001` |
| `YTQUEUE_LLM_BASE_URL` | _(unset)_ | Required for Ollama; optional for OpenAI-compatible endpoints |
| `YTQUEUE_LLM_API_KEY` | _(unset)_ | Required for OpenAI / Anthropic |
| `YTQUEUE_SUMMARY_MAX_WORDS` | `80` | Word budget for LLM summaries |
| `YTQUEUE_DB_PATH` | `data/ytqueue.db` | SQLite archive |
| `YTQUEUE_AUDIO_DIR` | `data/audio` | Cached OGG Opus files |
| `YTQUEUE_AUTH_ENABLED` | `false` | Enable password protection |
| `YTQUEUE_PASSWORD_HASH` | _(unset)_ | bcrypt hash — set via `setup.sh` or Settings UI |
| `YTQUEUE_API_TOKEN` | _(unset)_ | Bearer token injected into bookmarklets for cross-origin auth |

### API token (for bookmarklet + auth)

When `YTQUEUE_AUTH_ENABLED=true`, the bookmarklet needs a credential to submit batches from a YouTube page (cross-origin, no session cookie). Set `YTQUEUE_API_TOKEN` to a long random string and the server injects it into the bookmarklet automatically:

```bash
# Generate a token
python3 -c "import secrets; print(secrets.token_hex(32))"

# Add to .env
echo "YTQUEUE_API_TOKEN=<token>" >> .env
```

---

## Workflow

1. **Install bookmarklets** — drag both links from the yt-queue home page to your bookmarks bar
2. **Preview** — on any YouTube page, click **yt-queue Preview** to see all extractable videos before ingesting
3. **Ingest** — click **yt-queue Playlist** to submit; already-archived videos are skipped automatically; a progress tab opens immediately
4. **Monitor** — the Progress tab shows live per-job status, progress bars, queue position, and an ETA
5. **Triage** — once processing completes, click "View results"; videos are sorted by relevance score; flag, mark watched, or mark for deletion
6. **Archive** — browse your full library, filter by category, re-score by new criteria, bulk-delete, or read/copy any transcript

### Categories

After building up a library, click **Categorize** in the archive. The LLM derives ~12 categories from a sample of your summaries, then assigns every video. Categories appear as filterable badges. Re-run any time to regenerate.

---

## Architecture

```
POST /api/batches        →  JobRunner (asyncio, device pool)
                              ↓
                         download (yt-dlp)
                              ↓
                         transcribe (faster-whisper, VAD)
                              ↓
                         summarize + score (LLM, optional)
                              ↓
                         encode OGG Opus (ffmpeg, cached)
                              ↓
                         archive (SQLite / aiosqlite, FTS5)
```

- **Frontend** — vanilla HTML/CSS/JS, no build step
- **Backend** — FastAPI + aiosqlite (WAL mode, FTS5 full-text search)
- **Jobs** — in-memory; only completed transcripts persist across restarts
- **Audio** — OGG Opus cached in `data/audio/`; survives transcription failures and enables retry without re-downloading
- **Settings** — most settings hot-reload via PATCH `/api/settings`; Whisper model cache is cleared automatically on model/device change

---

## License

MIT
