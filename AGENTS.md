# Repository Guidelines

## Project Structure & Module Organization
- `app/` contains the FastAPI backend and processing pipeline.
- Key backend modules: `main.py` (routes + app lifecycle), `jobs.py` (queue/pipeline), `database.py` (SQLite archive), `summarizer.py` (LLM providers), `downloader.py` and `transcriber.py` (media pipeline).
- `static/` contains the frontend pages and scripts (`index.html`, `triage.html`, `archive.html` and matching `*.js`, `style.css`).
- Root utilities: `startup.sh` (opinionated runtime bootstrap), `source.js` / `source-test.js` (bookmarklet scripts), `data/` (runtime DB/audio artifacts).

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` creates/activates the local environment.
- `pip install -r requirements.txt` installs backend dependencies.
- `uvicorn app.main:app --reload` runs local development server with auto-reload.
- `./startup.sh` runs the app with project defaults (LLM/provider and port settings preconfigured).
- `curl http://localhost:9000/api/health` is a quick smoke check when using `startup.sh`.

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints for public functions, snake_case for functions/variables, PascalCase for Pydantic models/classes.
- JavaScript in `static/` and bookmarklets follows existing project style: semicolons, single quotes, compact functions, and defensive DOM checks.
- Keep modules focused; prefer small helper functions instead of large route handlers.
- Match existing file naming patterns (`archive.js`, `triage.js`, etc.) when adding new frontend pages.

## Testing Guidelines
- No full automated test suite is committed yet; validate changes with targeted smoke tests.
- For backend changes, verify affected endpoints via `curl` or browser flows (`/api/batches`, `/api/triage/{batch_id}`, `/api/archive`).
- For bookmarklet/frontend changes, test both `source.js` and `source-test.js` behavior on representative YouTube playlist pages.
- Include reproducible verification steps in PR descriptions for non-trivial changes.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style used in history (example: `feat: add batch summarize status endpoint`).
- Keep commits scoped to one logical change and include context for pipeline/data-impacting edits.
- PRs should include: summary, why the change is needed, manual test evidence, and screenshots/GIFs for UI updates.
- Link related issues/tasks and call out new environment variables or migration steps explicitly.
