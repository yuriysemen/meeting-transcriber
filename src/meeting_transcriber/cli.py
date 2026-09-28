"""Command-line entry point: ``transcribe INPUT --extract-only [-o OUTPUT]`` (spec M1, Q1)."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import TextIO

from meeting_transcriber.audio import ExtractionError, extract_audio
from meeting_transcriber.audio.errors import EXIT_USAGE

DEBUG_ENV = "MEETING_TRANSCRIBER_DEBUG"
EXIT_UNEXPECTED = 1


class ProgressLine:
    """Single self-updating stderr line; only used when stderr is a terminal (AC-M1-20/21)."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.text = ""
        self.have_fraction = False

    def fraction(self, value: float) -> None:
        self.have_fraction = True
        self._show(f"{int(value * 100)}%")

    def elapsed(self, seconds: float) -> None:
        if self.have_fraction:
            return  # duration known: percentage is shown instead
        total = int(seconds)
        self._show(f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}")

    def _show(self, status: str) -> None:
        text = f"Extracting audio... {status}"
        if text != self.text:
            self.text = text
            self.stream.write(f"\r\033[K{text}")
            self.stream.flush()

    def end(self) -> None:
        if self.text:
            self.stream.write("\n")
            self.stream.flush()
            self.text = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description="Turn a meeting recording into a transcript. "
        "In this version only audio extraction (--extract-only) is available.",
    )
    parser.add_argument("input", type=Path, help="recording to process (video or audio file)")
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="only extract 16 kHz mono 16-bit PCM WAV audio",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output WAV path (default: <input dir>/<input name>.wav; overwritten if it exists)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.extract_only:
        print(
            "Error: transcription not implemented yet; use --extract-only to extract audio.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    src: Path = args.input
    dst: Path = args.output if args.output is not None else src.with_suffix(".wav")

    progress = ProgressLine(sys.stderr) if _is_tty(sys.stderr) else None
    try:
        result = extract_audio(
            src,
            dst,
            on_progress=progress.fraction if progress else None,
            on_elapsed=progress.elapsed if progress else None,
        )
    except ExtractionError as exc:
        if progress:
            progress.end()
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        if progress:
            progress.end()
        print(f"Interrupted; no output written for {src}.", file=sys.stderr)
        return 130
    except Exception as exc:  # last resort: a failure never shows a raw traceback
        if progress:
            progress.end()
        return _report_unexpected(exc, src)
    if progress:
        progress.end()
    print(result)
    return 0


def _report_unexpected(exc: Exception, src: Path) -> int:
    """Print a one-line error for a bug-type failure; full traceback only in debug mode.

    Temp output is already removed by extract_audio's ``finally`` blocks, and the final
    WAV is only ever created by an atomic rename, so no partial WAV can be left behind.
    """
    print(
        f"Error: unexpected error: {type(exc).__name__}: {exc} (while processing {src})",
        file=sys.stderr,
    )
    if os.environ.get(DEBUG_ENV, "").strip() not in ("", "0"):
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    else:
        print(f"Rerun with {DEBUG_ENV}=1 to see the full traceback.", file=sys.stderr)
    return EXIT_UNEXPECTED


def _is_tty(stream: TextIO) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


if __name__ == "__main__":
    sys.exit(main())
