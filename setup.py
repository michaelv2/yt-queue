#!/usr/bin/env python3
"""
yt-queue setup wizard.

Phase 1 (any python3): create venv, install deps, re-exec through venv.
Phase 2 (venv python):  full TUI with rich + questionary.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve()
ROOT   = SCRIPT.parent
VENV   = ROOT / ".venv"
ENV    = ROOT / ".env"
REEXEC = "--_tui"          # flag set when already running inside the venv


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 1 – bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def _phase1():
    """Create venv, install requirements + TUI libs, then re-exec."""
    _plain_header()

    pip = VENV / "bin" / "pip"

    # ── venv ──────────────────────────────────────────────────────────────────
    if VENV.exists():
        _print("  ✓ Virtual environment already exists")
    else:
        _print("  → Creating virtual environment…")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        _print("  ✓ Created .venv/")

    # ── pip install ────────────────────────────────────────────────────────────
    _print("  → Installing dependencies (may take a minute)…")
    req_result = subprocess.run(
        [str(pip), "install", "-q", "-r", str(ROOT / "requirements.txt")],
        capture_output=True, text=True,
    )
    if req_result.returncode != 0:
        _print("  ✗ pip install failed:\n" + req_result.stderr)
        sys.exit(1)

    _print("  → Installing TUI helpers (rich, questionary)…")
    tui_result = subprocess.run(
        [str(pip), "install", "-q", "rich>=13", "questionary>=2"],
        capture_output=True, text=True,
    )
    if tui_result.returncode != 0:
        _print("  ✗ TUI install failed:\n" + tui_result.stderr)
        sys.exit(1)

    _print("  ✓ All dependencies ready\n")

    # ── re-exec through venv python ────────────────────────────────────────────
    venv_python = VENV / "bin" / "python"
    os.execv(str(venv_python), [str(venv_python), str(SCRIPT), REEXEC])


def _plain_header():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║           yt-queue  Setup Wizard             ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("  Step 1/5  Python environment")
    print()


def _print(msg: str):
    print(msg, flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2 – TUI
# ─────────────────────────────────────────────────────────────────────────────

def _phase2():
    """Full TUI wizard — runs inside the venv with rich + questionary."""
    import questionary
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import print as rprint
    from rich.rule import Rule
    from rich.text import Text

    console = Console()

    # ── welcome ───────────────────────────────────────────────────────────────
    console.clear()
    console.print()
    console.print(Panel.fit(
        "[bold cyan]yt-queue[/bold cyan]  [dim]Video transcription & triage system[/dim]\n"
        "[dim]────────────────────────────────────────[/dim]\n"
        "  This wizard will configure your installation.\n"
        "  Press [bold]Ctrl+C[/bold] at any time to quit without saving.",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()

    env = _load_env()

    # ── step 2: data dirs ─────────────────────────────────────────────────────
    _step(console, 2, 5, "Data directories")
    db_dir    = Path(env.get("YTQUEUE_DB_PATH",  "data/ytqueue.db")).parent
    audio_dir = Path(env.get("YTQUEUE_AUDIO_DIR", "data/audio"))
    for d in (db_dir, audio_dir):
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"  [green]✓[/green] {d}/")
    console.print()

    # ── step 3: server ────────────────────────────────────────────────────────
    _step(console, 3, 5, "Server")
    base_url = questionary.text(
        "Base URL  (used in bookmarklets):",
        default=env.get("YTQUEUE_BASE_URL", "http://localhost:8000"),
        style=_qstyle(),
    ).ask()
    if base_url is None:
        _abort(console)
    env["YTQUEUE_BASE_URL"] = base_url
    port = base_url.rstrip("/").rsplit(":", 1)[-1] if ":" in base_url else "8000"
    console.print()

    # ── step 4: transcription ─────────────────────────────────────────────────
    _step(console, 4, 5, "Transcription")

    whisper_model = questionary.select(
        "Whisper model:",
        choices=[
            questionary.Choice("tiny    — fastest, ~75 MB",   value="tiny"),
            questionary.Choice("base    — balanced, ~150 MB (recommended)", value="base"),
            questionary.Choice("small   — better accuracy, ~500 MB",  value="small"),
            questionary.Choice("medium  — high accuracy, ~1.5 GB",    value="medium"),
            questionary.Choice("large   — best accuracy, ~3 GB",      value="large"),
        ],
        default=env.get("YTQUEUE_WHISPER_MODEL", "base"),
        style=_qstyle(),
    ).ask()
    if whisper_model is None:
        _abort(console)
    env["YTQUEUE_WHISPER_MODEL"] = whisper_model

    whisper_device = questionary.select(
        "Compute device:",
        choices=[
            questionary.Choice("auto  — detect GPU automatically (recommended)", value="auto"),
            questionary.Choice("cpu   — force CPU",                               value="cpu"),
            questionary.Choice("cuda  — NVIDIA GPU",                              value="cuda"),
            questionary.Choice("mps   — Apple Silicon (transcription uses CPU)",  value="mps"),
        ],
        default=env.get("YTQUEUE_WHISPER_DEVICE", "auto"),
        style=_qstyle(),
    ).ask()
    if whisper_device is None:
        _abort(console)
    env["YTQUEUE_WHISPER_DEVICE"] = whisper_device

    concurrency = questionary.text(
        "Max concurrent transcription jobs:",
        default=env.get("YTQUEUE_MAX_CONCURRENT_JOBS", "2"),
        validate=lambda v: v.isdigit() and int(v) >= 1 or "Must be a positive integer",
        style=_qstyle(),
    ).ask()
    if concurrency is None:
        _abort(console)
    env["YTQUEUE_MAX_CONCURRENT_JOBS"] = concurrency

    max_dur = questionary.text(
        "Max video duration to accept (seconds):",
        default=env.get("YTQUEUE_MAX_DURATION_SECONDS", "7200"),
        validate=lambda v: v.isdigit() and int(v) >= 60 or "Must be ≥ 60",
        style=_qstyle(),
    ).ask()
    if max_dur is None:
        _abort(console)
    env["YTQUEUE_MAX_DURATION_SECONDS"] = max_dur
    console.print()

    # ── step 5a: LLM ─────────────────────────────────────────────────────────
    _step(console, 5, 5, "LLM  (optional — enables summaries & relevance scoring)")

    llm_provider = questionary.select(
        "Provider:",
        choices=[
            questionary.Choice("none       — transcription only",   value="none"),
            questionary.Choice("anthropic  — Anthropic (Claude)",   value="anthropic"),
            questionary.Choice("openai     — OpenAI (GPT)",         value="openai"),
            questionary.Choice("ollama     — local Ollama models",  value="ollama"),
        ],
        default=env.get("YTQUEUE_LLM_PROVIDER", "none"),
        style=_qstyle(),
    ).ask()
    if llm_provider is None:
        _abort(console)
    env["YTQUEUE_LLM_PROVIDER"] = llm_provider

    if llm_provider != "none":
        _model_defaults = {
            "anthropic": "claude-haiku-4-5-20251001",
            "openai":    "gpt-4o-mini",
            "ollama":    "llama3.2",
        }
        llm_model = questionary.text(
            "Model name:",
            default=env.get("YTQUEUE_LLM_MODEL") or _model_defaults.get(llm_provider, ""),
            style=_qstyle(),
        ).ask()
        if llm_model is None:
            _abort(console)
        env["YTQUEUE_LLM_MODEL"] = llm_model

        if llm_provider in ("anthropic", "openai"):
            current_key = env.get("YTQUEUE_LLM_API_KEY", "")
            masked = f"{'*' * 8}{current_key[-4:]}" if len(current_key) > 4 else ""
            hint = f"(current: {masked} — press Enter to keep)" if masked else "(required)"
            api_key = questionary.password(
                f"API key {hint}:",
                style=_qstyle(),
            ).ask()
            if api_key is None:
                _abort(console)
            if api_key:
                env["YTQUEUE_LLM_API_KEY"] = api_key
            elif not current_key:
                console.print("  [yellow]![/yellow] No API key set — LLM features won't work until one is provided")

        if llm_provider == "ollama":
            base = questionary.text(
                "Ollama base URL:",
                default=env.get("YTQUEUE_LLM_BASE_URL") or "http://localhost:11434",
                style=_qstyle(),
            ).ask()
            if base is None:
                _abort(console)
            env["YTQUEUE_LLM_BASE_URL"] = base

        words = questionary.text(
            "Summary word budget:",
            default=env.get("YTQUEUE_SUMMARY_MAX_WORDS", "80"),
            validate=lambda v: v.isdigit() and int(v) >= 10 or "Must be a positive integer",
            style=_qstyle(),
        ).ask()
        if words is None:
            _abort(console)
        env["YTQUEUE_SUMMARY_MAX_WORDS"] = words
    else:
        for k in ("YTQUEUE_LLM_MODEL", "YTQUEUE_LLM_API_KEY", "YTQUEUE_LLM_BASE_URL"):
            env.pop(k, None)
    console.print()

    # ── step 5b: authentication ───────────────────────────────────────────────
    console.print(Rule("[bold]Authentication[/bold]", style="dim"))
    console.print()

    currently_enabled = env.get("YTQUEUE_AUTH_ENABLED", "false").lower() == "true"
    has_hash          = bool(env.get("YTQUEUE_PASSWORD_HASH"))

    if currently_enabled and has_hash:
        console.print("  [green]✓[/green] Password protection is currently [bold green]enabled[/bold green]")
        change_auth = questionary.confirm(
            "Change password or auth settings?",
            default=False,
            style=_qstyle(),
        ).ask()
        if change_auth is None:
            _abort(console)
        if not change_auth:
            _finish(console, env, port)
            return

    enable_auth = questionary.confirm(
        "Enable password protection?",
        default=True,
        style=_qstyle(),
    ).ask()
    if enable_auth is None:
        _abort(console)
    env["YTQUEUE_AUTH_ENABLED"] = "true" if enable_auth else "false"

    if enable_auth:
        import bcrypt
        console.print()
        while True:
            pw = questionary.password("Password:", style=_qstyle()).ask()
            if pw is None:
                _abort(console)
            if not pw:
                console.print("  [yellow]![/yellow] Password cannot be empty")
                continue
            pw2 = questionary.password("Confirm password:", style=_qstyle()).ask()
            if pw2 is None:
                _abort(console)
            if pw != pw2:
                console.print("  [yellow]![/yellow] Passwords do not match — try again")
                continue
            break
        pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        env["YTQUEUE_PASSWORD_HASH"] = pw_hash
        console.print("  [green]✓[/green] Password hashed and saved")
    else:
        env.pop("YTQUEUE_PASSWORD_HASH", None)
        console.print("  [yellow]![/yellow] Authentication disabled — app will be publicly accessible")

    console.print()
    _finish(console, env, port)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _step(console, n: int, total: int, title: str):
    from rich.rule import Rule
    console.print(Rule(f"[bold]Step {n}/{total}[/bold]  {title}", style="cyan"))
    console.print()


def _finish(console, env: dict, port: str):
    from rich.panel import Panel
    _save_env(env)
    url = env.get("YTQUEUE_BASE_URL", f"http://localhost:{port}")
    login_line = f"\n  [dim]Login page:[/dim]  [cyan]{url}/login[/cyan]" if env.get("YTQUEUE_AUTH_ENABLED") == "true" else ""
    console.print(Panel(
        f"[bold green]✓ Setup complete![/bold green]  Configuration saved to [cyan].env[/cyan]\n\n"
        f"  [bold]Start the server:[/bold]\n\n"
        f"    [cyan]source .venv/bin/activate[/cyan]\n"
        f"    [cyan]uvicorn app.main:app --host 0.0.0.0 --port {port}[/cyan]\n\n"
        f"  [bold]Open:[/bold]  [cyan bold]{url}[/cyan bold]"
        f"{login_line}",
        border_style="green",
        padding=(1, 4),
    ))
    console.print()


def _abort(console):
    console.print("\n  [yellow]Aborted — no changes written.[/yellow]\n")
    sys.exit(0)


def _qstyle():
    from questionary import Style
    return Style([
        ("qmark",        "fg:#6c7cff bold"),
        ("question",     "bold"),
        ("answer",       "fg:#3ecf8e bold"),
        ("pointer",      "fg:#6c7cff bold"),
        ("highlighted",  "fg:#6c7cff bold"),
        ("selected",     "fg:#3ecf8e"),
        ("separator",    "fg:#586069"),
        ("instruction",  "fg:#8b90a8"),
    ])


def _load_env() -> dict:
    env: dict = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _save_env(env: dict):
    lines = [f"{k}={v}" for k, v in env.items()]
    ENV.write_text("\n".join(lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        if REEXEC in sys.argv:
            _phase2()
        else:
            _phase1()
    except KeyboardInterrupt:
        print("\n\n  Aborted.\n")
        sys.exit(0)
