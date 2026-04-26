"""yt-dlp wrapper — download video audio as WAV (YouTube, Vimeo, etc.)."""

from __future__ import annotations

import logging
import shutil
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
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except (ImportError, Exception):
        pass

    # Last resort: try to install imageio-ffmpeg inline if possible
    try:
        import subprocess
        log.warning("ffmpeg not found in PATH, attempting to install imageio-ffmpeg...")
        subprocess.run(["pip", "install", "imageio-ffmpeg>=0.5.0"], check=True, capture_output=True)
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            log.info("ffmpeg installed and located at: %s", exe)
            return exe
    except Exception as e:
        log.error("Failed to install imageio-ffmpeg: %s", e)

    return None


def fetch_info(url: str) -> dict:
    """Fetch title, duration, and thumbnail without downloading."""
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
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
    import yt_dlp

    output_template = str(output_dir / f"{video_id}.%(ext)s")
    ffmpeg_path = _find_ffmpeg()

    # First pass: extract info to check duration
    base_opts: dict = {"quiet": True, "no_warnings": True}
    if ffmpeg_path:
        base_opts["ffmpeg_location"] = ffmpeg_path
    with yt_dlp.YoutubeDL(base_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    duration = info.get("duration") or 0
    title = info.get("title", video_id)
    thumbnail = info.get("thumbnail", "")

    if duration > settings.max_duration_seconds:
        raise ValueError(
            f"Video is {duration}s, exceeds max of {settings.max_duration_seconds}s"
        )

    # Second pass: download audio
    opts: dict = {
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
    }
    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    audio_path = output_dir / f"{video_id}.wav"
    if not audio_path.exists():
        # yt-dlp may produce a different extension; find the actual file
        candidates = list(output_dir.glob(f"{video_id}.*"))
        if candidates:
            audio_path = candidates[0]
        else:
            raise FileNotFoundError(f"Downloaded audio not found for {video_id}")

    log.info("Downloaded '%s' (%ds) → %s", title, duration, audio_path)
    return audio_path, title, float(duration), thumbnail
