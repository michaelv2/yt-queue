"""yt-dlp wrapper — download YouTube audio as WAV."""

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
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def download_audio(video_id: str, output_dir: Path) -> tuple[Path, str, float]:
    """Download audio for a YouTube video.

    Returns (audio_path, title, duration_seconds).
    Raises ValueError if the video exceeds max duration.
    """
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = str(output_dir / "%(id)s.%(ext)s")
    ffmpeg_path = _find_ffmpeg()

    # First pass: extract info to check duration
    base_opts: dict = {"quiet": True, "no_warnings": True}
    if ffmpeg_path:
        base_opts["ffmpeg_location"] = ffmpeg_path
    with yt_dlp.YoutubeDL(base_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    duration = info.get("duration") or 0
    title = info.get("title", video_id)

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
    return audio_path, title, float(duration)
