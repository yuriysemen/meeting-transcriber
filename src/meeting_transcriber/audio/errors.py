"""Extraction errors. Each carries the CLI exit code (spec M1, Q4) and the saved log path."""

from __future__ import annotations

from pathlib import Path

EXIT_USAGE = 2  # usage error / input not found
EXIT_NO_AUDIO = 3
EXIT_FAILED = 4  # unreadable file, extraction failed after retry, disk full
EXIT_FFMPEG_MISSING = 5


class ExtractionError(Exception):
    """Base class for all audio extraction failures.

    ``str(error)`` is a single user-facing line that names the input file.
    """

    exit_code: int = EXIT_FAILED

    def __init__(self, message: str, log_path: Path | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.log_path = log_path

    def __str__(self) -> str:
        return self.message


class UsageError(ExtractionError):
    """Invalid arguments, e.g. the output path is the input file itself."""

    exit_code = EXIT_USAGE


class InputNotFoundError(UsageError):
    """The input file does not exist."""


class NoAudioStreamError(ExtractionError):
    """The input has no audio stream."""

    exit_code = EXIT_NO_AUDIO


class MediaUnreadableError(ExtractionError):
    """ffprobe could not read the file, even with larger probe settings."""

    exit_code = EXIT_FAILED


class ConversionFailedError(ExtractionError):
    """ffmpeg failed on both the normal and the tolerant attempt."""

    exit_code = EXIT_FAILED


class DiskFullError(ExtractionError):
    """The output could not be written because the disk is full."""

    exit_code = EXIT_FAILED


class OutputError(ExtractionError):
    """The output location cannot be written (other than a full disk)."""

    exit_code = EXIT_FAILED


class FFmpegNotFoundError(ExtractionError):
    """ffmpeg or ffprobe is not installed / not on PATH."""

    exit_code = EXIT_FFMPEG_MISSING
