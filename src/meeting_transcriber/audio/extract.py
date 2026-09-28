"""Robust extraction of 16 kHz mono 16-bit PCM WAV from any recording (spec M1).

Pipeline: ffprobe (one retry with larger probe settings) -> reject files without
audio -> ffmpeg normal attempt -> one tolerant retry -> clear error + saved log.
"""

from __future__ import annotations

import errno
import io
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Callable

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
from meeting_transcriber.audio.runner import Runner, default_runner

logger = logging.getLogger(__name__)

# ffmpeg's own defaults, stated explicitly so the retry is visibly larger (AC-M1-07).
NORMAL_PROBE = ["-analyzeduration", "5000000", "-probesize", "5000000"]
LARGE_PROBE = ["-analyzeduration", "100000000", "-probesize", "100000000"]
TOLERANT_INPUT = ["-fflags", "+discardcorrupt+genpts", "-err_detect", "ignore_err"]

# PLAN.md target: -vn -ac 1 -ar 16000 -c:a pcm_s16le; -rf64 auto lifts the 4 GB cap (AC-M1-22).
OUTPUT_OPTS = [
    "-map", "0:a:0",
    "-vn",
    "-ac", "1",
    "-ar", "16000",
    "-c:a", "pcm_s16le",
    "-rf64", "auto",
    "-f", "wav",
]

DISK_FULL_MARKERS = ("no space left on device", "disk full", "disk quota exceeded")
MAX_PROGRESS_BEFORE_DONE = 0.99


def extract_audio(
    src: Path,
    dst: Path,
    runner: Runner | None = None,
    on_progress: Callable[[float], None] | None = None,
    *,
    on_elapsed: Callable[[float], None] | None = None,
) -> Path:
    """Convert ``src`` into a 16 kHz mono 16-bit PCM WAV at ``dst`` and return ``dst``.

    ``on_progress`` receives non-decreasing fractions in [0.0, 1.0]; 1.0 only on success.
    ``on_elapsed`` (optional) receives seconds of audio converted so far, for display
    when the duration is unknown.
    Raises an ``ExtractionError`` subclass on failure; no WAV is left at ``dst`` then.
    """
    src = Path(src)
    dst = Path(dst)
    job = _Job(src, dst, runner or default_runner, on_progress, on_elapsed)
    return job.run()


class _Job:
    def __init__(
        self,
        src: Path,
        dst: Path,
        runner: Runner,
        on_progress: Callable[[float], None] | None,
        on_elapsed: Callable[[float], None] | None,
    ) -> None:
        self.src = src
        self.dst = dst
        self.runner = runner
        self.on_progress = on_progress
        self.on_elapsed = on_elapsed
        self.log = io.StringIO()
        self.log_path = dst.parent / f"{src.stem}.ffmpeg.log"
        self.duration: float | None = None
        self.last_fraction = -1.0

    # ---- pipeline -------------------------------------------------------

    def run(self) -> Path:
        if not self.src.is_file():
            raise InputNotFoundError(f"Input file not found: {self.src}")
        if self.dst.exists() and self.dst.resolve() == self.src.resolve():
            raise UsageError(
                f"Output path is the same as the input file: {self.src}. "
                "Choose a different output with -o."
            )

        info = self._probe()
        audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        if not audio_streams:
            raise NoAudioStreamError(f"No audio stream found in {self.src}")
        if len(audio_streams) > 1:
            note = f"Found {len(audio_streams)} audio tracks in {self.src}; using the first one (0:a:0)."
            self.log.write(note + "\n")
            logger.info(note)
        self.duration = _duration(info, audio_streams[0])

        self._convert()
        _remove_quietly(self.log_path)  # a log from an earlier failed run is stale now
        self._report_progress(1.0, final=True)
        return self.dst

    def _probe(self) -> dict[str, Any]:
        base = ["ffprobe", "-hide_banner", "-show_streams", "-show_format", "-of", "json"]
        for attempt, probe_opts in enumerate((NORMAL_PROBE, LARGE_PROBE), start=1):
            self.log.write(f"=== ffprobe, attempt {attempt} ===\n")
            lines: list[str] = []
            code = self._run([*base, *probe_opts, str(self.src)], lines.append)
            if code == 0:
                try:
                    info = json.loads("\n".join(lines))
                    if isinstance(info, dict):
                        return info
                except ValueError:
                    pass
                self.log.write("[ffprobe output could not be parsed as JSON]\n")
        log_path = self._save_log()
        raise MediaUnreadableError(
            f"Cannot read media file {self.src}: it may be damaged, incomplete, "
            f"or not a media file.{_log_hint(log_path)}",
            log_path,
        )

    def _convert(self) -> None:
        tmp = self._make_temp()
        try:
            for attempt in (1, 2):
                tolerant = attempt == 2
                input_opts = [*TOLERANT_INPUT, *LARGE_PROBE] if tolerant else NORMAL_PROBE
                args = [
                    "ffmpeg", "-hide_banner", "-nostdin", "-y",
                    *input_opts,
                    "-i", str(self.src),
                    *OUTPUT_OPTS,
                    "-progress", "pipe:1", "-nostats",
                    str(tmp),
                ]
                self.log.write(f"=== ffmpeg, attempt {attempt}{' (tolerant)' if tolerant else ''} ===\n")
                attempt_log = io.StringIO()
                if not tolerant:
                    self._report_progress(0.0)
                code = self._run(args, self._on_ffmpeg_line, attempt_log)
                if code == 0 and _has_audio_samples(tmp):
                    self._finish(tmp)
                    return
                if code == 0:
                    attempt_log.write("[ffmpeg exited 0 but the output has no audio samples]\n")
                self.log.write(attempt_log.getvalue())
                if _is_disk_full(attempt_log.getvalue()):
                    _remove_quietly(tmp)
                    raise self._disk_full()
                if not tolerant:
                    _warn(
                        f"Warning: audio extraction from {self.src} failed; "
                        "retrying with tolerant settings for damaged files."
                    )
            log_path = self._save_log()
            raise ConversionFailedError(
                f"Could not extract audio from {self.src} (failed twice, including a "
                f"tolerant retry).{_log_hint(log_path)}",
                log_path,
            )
        finally:
            _remove_quietly(tmp)

    def _make_temp(self) -> Path:
        try:
            self.dst.parent.mkdir(parents=True, exist_ok=True)
            while True:
                tmp = self.dst.parent / f".{self.dst.stem}.{secrets.token_hex(4)}.part.wav"
                try:
                    # Unlike mkstemp, 0o666 lets the umask decide the final file mode.
                    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                except FileExistsError:
                    continue
                os.close(fd)
                return tmp
        except OSError as exc:
            raise self._output_error(exc) from None

    def _finish(self, tmp: Path) -> None:
        try:
            os.replace(tmp, self.dst)
        except OSError as exc:
            raise self._output_error(exc) from None

    # ---- helpers ---------------------------------------------------------

    def _run(
        self,
        args: list[str],
        on_line: Callable[[str], None] | None,
        log: io.StringIO | None = None,
    ) -> int:
        target = log if log is not None else self.log
        try:
            return self.runner(args, target, on_line)
        except FileNotFoundError:
            tool = args[0]
            raise FFmpegNotFoundError(
                f"{tool} not found while processing {self.src}. Install ffmpeg "
                "(which includes ffprobe), e.g. `brew install ffmpeg` or "
                "`sudo apt install ffmpeg`, and make sure it is on your PATH."
            ) from None

    def _on_ffmpeg_line(self, line: str) -> None:
        # Progress is cosmetic: never let a parsing problem fail the extraction.
        try:
            key, _, value = line.strip().partition("=")
            if key not in ("out_time_us", "out_time_ms"):
                return
            seconds = int(value) / 1_000_000
        except ValueError:
            return
        if seconds < 0:
            return
        if self.on_elapsed is not None:
            self.on_elapsed(seconds)
        if self.duration:
            self._report_progress(min(seconds / self.duration, MAX_PROGRESS_BEFORE_DONE))

    def _report_progress(self, fraction: float, final: bool = False) -> None:
        if self.on_progress is None:
            return
        if not final and not self.duration:
            return  # unknown duration: only the final 1.0 is reported
        if fraction <= self.last_fraction:
            return
        self.last_fraction = fraction
        self.on_progress(fraction)

    def _save_log(self) -> Path | None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text(self.log.getvalue(), encoding="utf-8")
        except OSError:
            return None
        return self.log_path

    def _disk_full(self) -> DiskFullError:
        log_path = self._save_log()
        return DiskFullError(
            f"Not enough disk space to write the audio extracted from {self.src} "
            f"to {self.dst}. Free up space or choose another output location with -o."
            f"{_log_hint(log_path, saved_only=True)}",
            log_path,
        )

    def _output_error(self, exc: OSError) -> ExtractionError:
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            return self._disk_full()
        return OutputError(
            f"Cannot write the output for {self.src} to {self.dst}: {exc.strerror or exc}"
        )


def _duration(info: dict[str, Any], stream: dict[str, Any]) -> float | None:
    for raw in (info.get("format", {}).get("duration"), stream.get("duration")):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _has_audio_samples(path: Path) -> bool:
    """False if the WAV is missing, empty, or its data chunk is empty (spec Q8).

    A non-empty file that is not a recognizable WAV is given the benefit of the doubt.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        with path.open("rb") as f:
            header = f.read(12)
            if header[:4] not in (b"RIFF", b"RF64") or header[8:12] != b"WAVE":
                return True
            while True:
                chunk = f.read(8)
                if len(chunk) < 8:
                    return False
                chunk_id, chunk_size = chunk[:4], int.from_bytes(chunk[4:], "little")
                if chunk_id == b"data":
                    return chunk_size > 0 and size - f.tell() > 0
                f.seek(chunk_size + (chunk_size & 1), os.SEEK_CUR)
    except OSError:
        return False


def _is_disk_full(stderr_text: str) -> bool:
    lowered = stderr_text.lower()
    return any(marker in lowered for marker in DISK_FULL_MARKERS)


def _log_hint(log_path: Path | None, saved_only: bool = False) -> str:
    if log_path is not None:
        return f" ffmpeg log saved to: {log_path}"
    return "" if saved_only else " (the ffmpeg log could not be saved)"


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _warn(message: str) -> None:
    stream = sys.stderr
    try:
        prefix = "\r\033[K" if stream.isatty() else ""
    except (AttributeError, ValueError):
        prefix = ""
    print(prefix + message, file=stream, flush=True)
