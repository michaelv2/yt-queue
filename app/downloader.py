"""yt-dlp wrapper — download video audio as WAV (YouTube, Vimeo, etc.)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)


def _find_ffmpeg() -> str | None:
    """Find ffmpeg binary — prefer system install, fall back to imageio-ffmpeg."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def _ytdlp_cmd() -> list[str]:
    """Return the command prefix to invoke yt-dlp from the current Python env."""
    return [sys.executable, "-m", "yt_dlp"]


def _find_node() -> str | None:
    """Find node binary — check common NVM paths if not on PATH."""
    path = shutil.which("node")
    if path:
        return path
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.is_dir():
        versions = sorted(nvm_dir.iterdir(), reverse=True)
        for v in versions:
            candidate = v / "bin" / "node"
            if candidate.is_file():
                return str(candidate)
    return None


def _base_args() -> list[str]:
    """Common yt-dlp CLI args for JS runtime and ffmpeg."""
    node_path = _find_node()
    if node_path:
        args = ["--js-runtimes", f"node:{node_path}", "--remote-components", "ejs:github"]
    else:
        log.warning("node not found — YouTube signature solving may fail")
        args = ["--remote-components", "ejs:github"]
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        args += ["--ffmpeg-location", ffmpeg_path]
    return args


def _run_ytdlp(cmd: list[str], *, need_stdout: bool = False) -> subprocess.CompletedProcess:
    """Run yt-dlp, tolerating exit code 2 (non-fatal warnings)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 1:
        stderr = result.stderr.strip()
        raise RuntimeError(f"yt-dlp failed: {stderr or 'unknown error'}")
    if result.returncode not in (0, 2):
        stderr = result.stderr.strip()
        raise RuntimeError(f"yt-dlp exited with code {result.returncode}: {stderr or 'unknown error'}")
    if result.returncode == 2 and result.stderr:
        log.warning("yt-dlp warnings: %s", result.stderr.strip()[:500])
    if need_stdout and not result.stdout.strip():
        stderr = result.stderr.strip()
        raise RuntimeError(f"yt-dlp produced no output: {stderr or 'unknown error'}")
    return result


def fetch_info(url: str) -> dict:
    """Fetch title, duration, and thumbnail without downloading."""
    cmd = [
        *_ytdlp_cmd(), *_base_args(),
        "--no-warnings",
        "--dump-json", "--no-download",
        url,
    ]
    result = _run_ytdlp(cmd, need_stdout=True)
    info = json.loads(result.stdout)
    return {
        "title": info.get("title", ""),
        "duration": float(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail", ""),
    }


def download_audio(url: str, video_id: str, output_dir: Path) -> tuple[Path, str, float, str]:
    """Download audio for a video (YouTube, Vimeo, or any yt-dlp-supported site).

    Returns (audio_path, title, duration_seconds, thumbnail_url).
    Raises ValueError if the video exceeds max duration.
    """
    output_template = str(output_dir / f"{video_id}.%(ext)s")

    # First pass: extract info to check duration
    info = fetch_info(url)
    duration = info["duration"]
    title = info.get("title", video_id)
    thumbnail = info.get("thumbnail", "")

    if duration > settings.max_duration_seconds:
        raise ValueError(
            f"Video is {duration}s, exceeds max of {settings.max_duration_seconds}s"
        )

    # Second pass: download audio
    cmd = [
        *_ytdlp_cmd(), *_base_args(),
        "--format", "bestaudio/best",
        "--extract-audio", "--audio-format", "wav", "--audio-quality", "0",
        "--output", output_template,
        "--no-warnings",
        url,
    ]
    _run_ytdlp(cmd)

    audio_path = output_dir / f"{video_id}.wav"
    if not audio_path.exists():
        candidates = list(output_dir.glob(f"{video_id}.*"))
        if candidates:
            audio_path = candidates[0]
        else:
            raise FileNotFoundError(f"Downloaded audio not found for {video_id}")

    log.info("Downloaded '%s' (%ds) → %s", title, duration, audio_path)
    return audio_path, title, float(duration), thumbnail
