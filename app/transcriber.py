"""faster-whisper wrapper — lazy model cache + VAD + artifact filter."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import settings
from .models import TranscriptSegment

log = logging.getLogger(__name__)

_models: dict = {}

# Known Whisper hallucinations from YouTube training data.
_ARTIFACT_TEXTS = {"you", "thank you", "thanks for watching"}


def get_model(
    name: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
):
    """Lazily load and cache a faster-whisper model."""
    name = name or settings.whisper_model
    device = device or settings.whisper_device
    compute_type = compute_type or settings.whisper_compute_type

    key = (name, device, compute_type)
    if key not in _models:
        from faster_whisper import WhisperModel

        log.info("Loading faster-whisper model '%s' (device=%s, compute=%s)...", name, device, compute_type)
        _models[key] = WhisperModel(name, device=device, compute_type=compute_type)
    return _models[key]


def transcribe(audio_path: Path, model=None) -> list[TranscriptSegment]:
    """Transcribe an audio file and return timestamped segments.

    Uses VAD to skip silence (prevents hallucination loops on long audio)
    and filters known YouTube training-data artifacts.
    """
    if model is None:
        model = get_model()

    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
    )
    seg_list = list(segments_iter)

    # Filter end-of-utterance artifact: a final short filler with high no_speech_prob
    if (
        len(seg_list) >= 2
        and seg_list[-1].text.strip().lower() in _ARTIFACT_TEXTS
        and seg_list[-1].no_speech_prob > 0.1
    ):
        seg_list = seg_list[:-1]

    return [
        TranscriptSegment(
            start=round(s.start, 3),
            end=round(s.end, 3),
            text=s.text.strip(),
        )
        for s in seg_list
        if s.text.strip()
    ]
