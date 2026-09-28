"""Audio extraction: any recording -> 16 kHz mono 16-bit PCM WAV."""

from meeting_transcriber.audio.errors import (
    ConversionFailedError,
    DiskFullError,
    ExtractionError,
    FFmpegNotFoundError,
    InputNotFoundError,
    MediaUnreadableError,
    NoAudioStreamError,
    OutputError,
    UsageError,
)
from meeting_transcriber.audio.extract import extract_audio
from meeting_transcriber.audio.runner import Runner, default_runner

__all__ = [
    "ConversionFailedError",
    "DiskFullError",
    "ExtractionError",
    "FFmpegNotFoundError",
    "InputNotFoundError",
    "MediaUnreadableError",
    "NoAudioStreamError",
    "OutputError",
    "Runner",
    "UsageError",
    "default_runner",
    "extract_audio",
]
