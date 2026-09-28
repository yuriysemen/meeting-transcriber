"""Shared, plain (non-fixture) test helpers for the M1 audio-extraction suite.

Nothing here is a pytest fixture — fixtures that build real media files live in
tests/conftest.py. This module holds:

- thin wrappers around the real `ffmpeg`/`ffprobe` binaries, used by tests to
  build fixtures and to verify results (never imported by src/),
- the CLI invocation helper (`run_cli`), which always calls the package with
  `[sys.executable, "-m", "meeting_transcriber", ...]` so it does not depend on
  PATH — required for AC-M1-17 (empty PATH) while python itself must still be
  found by its absolute path,
- helpers to build "spy" and "flooding" fake `ffmpeg`/`ffprobe` binaries used
  to shadow the real ones via a PATH prefix (AC-M1-06, -14, -15, -17),
- `ScriptedRunner`: a fake `Runner` (see the spec's Interface section, and the
  "What a fake runner must do" clarification) used by the unit tests. It never
  touches ffmpeg/ffprobe; it is driven entirely by `ProbeStep`/`ConvertStep`
  scripts that the test supplies.

Contract this module assumes for a fake Runner (from the spec, clarified
2026-09-28):
- `args[0]` is the bare command name, `"ffprobe"` or `"ffmpeg"`.
- ffprobe is called with `-of json -show_streams -show_format`; it "succeeds"
  only if it returns 0 AND sends valid JSON through `on_stdout_line`.
- ffmpeg's last argument (`args[-1]`) is the temporary output file; a
  simulated success must return 0 AND leave a non-empty file there.
- ffmpeg is called with `-progress pipe:1 -nostats`; progress lines such as
  `out_time_us=2500000` / `progress=end` are sent through `on_stdout_line`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Callable

# --------------------------------------------------------------------------
# CLI invocation
# --------------------------------------------------------------------------

CLI_MODULE = "meeting_transcriber"


def cli_argv(*args: str) -> list[str]:
    """Build an argv list that runs the CLI via `python -m meeting_transcriber`.

    Using sys.executable (an absolute path) means the interpreter is always
    found even with an empty PATH (AC-M1-17); it never depends on a console
    script being on PATH.
    """
    return [sys.executable, "-m", CLI_MODULE, *args]


def run_cli(
    args: list[str],
    env: dict | None = None,
    timeout: float = 60,
    cwd: str | Path | None = None,
    input: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cli_argv(*args),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(cwd) if cwd is not None else None,
        input=input,
    )


# --------------------------------------------------------------------------
# PATH / environment helpers
# --------------------------------------------------------------------------


def env_with_path(path_value: str, base: dict | None = None) -> dict:
    """A copy of `base` (default: current environment) with PATH replaced."""
    env = dict(base if base is not None else os.environ)
    env["PATH"] = path_value
    return env


def env_with_prepended_path(extra_dir: Path, base: dict | None = None) -> dict:
    """A copy of `base` with `extra_dir` prepended to PATH."""
    env = dict(base if base is not None else os.environ)
    env["PATH"] = str(extra_dir) + os.pathsep + env.get("PATH", "")
    return env


def empty_path_env(base: dict | None = None) -> dict:
    """Env with PATH cleared, everything else kept (e.g. HOME, needed by python)."""
    return env_with_path("", base=base)


# --------------------------------------------------------------------------
# Real ffmpeg / ffprobe (used only to build & verify fixtures, never imported
# by src/)
# --------------------------------------------------------------------------


def which_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found on PATH - required to build test fixtures")
    return path


def which_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise RuntimeError("ffprobe not found on PATH - required to build test fixtures")
    return path


def run_ffmpeg(args: list[str], timeout: float = 120) -> None:
    """Run real ffmpeg to build a fixture. Raises with full stderr on failure."""
    ffmpeg = which_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg fixture generation failed: args={args!r} "
            f"rc={proc.returncode} stderr={proc.stderr}"
        )


def probe_json(path: Path, timeout: float = 30) -> dict:
    ffprobe = which_ffprobe()
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {proc.stderr}")
    return json.loads(proc.stdout)


def probe_duration_seconds(path: Path) -> float:
    info = probe_json(path)
    fmt_duration = info.get("format", {}).get("duration")
    if fmt_duration is not None:
        return float(fmt_duration)
    for stream in info.get("streams", []):
        if stream.get("duration"):
            return float(stream["duration"])
    raise AssertionError(f"no duration found for {path}: {info!r}")


def max_volume_db(path: Path, timeout: float = 60) -> float:
    """dB reported by ffmpeg's volumedetect filter (-inf for true digital silence)."""
    ffmpeg = which_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    match = re.search(r"max_volume:\s*(-inf|-?\d+(?:\.\d+)?)\s*dB", proc.stderr)
    if not match:
        raise AssertionError(f"no max_volume found in ffmpeg output for {path}: {proc.stderr!r}")
    value = match.group(1)
    return float("-inf") if value == "-inf" else float(value)


def assert_wav_format_ok(path: Path) -> dict:
    """The spec's "WAV format check": exactly one audio stream,
    codec_name=pcm_s16le, sample_rate=16000, channels=1, no video stream.
    """
    assert path.exists(), f"expected WAV output at {path}, nothing there"
    assert path.stat().st_size > 0, f"WAV output at {path} is empty"
    info = probe_json(path)
    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    assert not video_streams, f"unexpected video stream(s) in {path}: {video_streams!r}"
    assert len(streams) == 1, f"expected exactly one stream in {path}, got {streams!r}"
    assert len(audio_streams) == 1, f"expected exactly one audio stream in {path}, got {streams!r}"
    stream = audio_streams[0]
    assert stream.get("codec_name") == "pcm_s16le", (
        f"codec_name={stream.get('codec_name')!r} in {path}, expected pcm_s16le"
    )
    assert str(stream.get("sample_rate")) == "16000", (
        f"sample_rate={stream.get('sample_rate')!r} in {path}, expected 16000"
    )
    assert int(stream.get("channels")) == 1, (
        f"channels={stream.get('channels')!r} in {path}, expected 1"
    )
    return info


# --------------------------------------------------------------------------
# Fake ffmpeg/ffprobe *binaries* on disk, used to shadow the real ones via a
# PATH prefix (CLI / integration-level tests only — not the ScriptedRunner).
# --------------------------------------------------------------------------


def _write_script(path: Path, script: str) -> None:
    path.write_text(script)
    path.chmod(0o755)


def make_marker_spy_dir(
    bin_dir: Path,
    marker_file: Path,
    exit_code: int = 1,
    names: tuple[str, ...] = ("ffmpeg", "ffprobe"),
) -> Path:
    """A directory with fake scripts (named from `names`) that each record
    their invocation (args) to `marker_file` and exit `exit_code`.

    Used to prove ffmpeg/ffprobe were NOT invoked (AC-M1-06, AC-M1-15): after
    the CLI/extract call, assert `not marker_file.exists()`. Pass
    `names=("ffmpeg",)` to shadow only ffmpeg while leaving the real ffprobe
    reachable further down PATH (e.g. to prove the no-audio case is detected
    by a real probe and never reaches conversion).
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        script = (
            "#!/bin/sh\n"
            f"printf '%s invoked: %s\\n' {shlex.quote(name)} \"$*\" >> {shlex.quote(str(marker_file))}\n"
            f"exit {exit_code}\n"
        )
        _write_script(bin_dir / name, script)
    return bin_dir


def make_flooding_ffmpeg_dir(bin_dir: Path, real_ffmpeg: str) -> Path:
    """A directory with a fake `ffmpeg` that runs the real ffmpeg (so output is
    still valid) and then writes >= 5MB of garbage to stderr before exiting
    with the real ffmpeg's exit code (AC-M1-14: no deadlock on a full pipe).
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = (
        "#!/bin/sh\n"
        f"{shlex.quote(real_ffmpeg)} \"$@\"\n"
        "status=$?\n"
        "yes 'flood flood flood flood flood flood flood flood flood flood' "
        "| head -c 6000000 1>&2\n"
        "exit $status\n"
    )
    _write_script(bin_dir / "ffmpeg", script)
    return bin_dir


def find_log_path_in_text(text: str) -> Path:
    """Extract a `*.ffmpeg.log` path mentioned in a message (AC-M1-08, -10)."""
    match = re.search(r"(\S+\.ffmpeg\.log)", text)
    assert match, f"no *.ffmpeg.log path found in: {text!r}"
    return Path(match.group(1))


def stderr_and_logs_text(capsys, caplog) -> str:
    """Combine captured stdio stderr and Python logging output.

    extract_audio() is a library function; the spec says warnings/errors are
    "printed on stderr" but does not say whether that means a direct
    sys.stderr.write/print or the logging module configured with a stderr
    handler. Checking both keeps the test valid either way.
    """
    captured = capsys.readouterr()
    return captured.err + "\n" + caplog.text


# --------------------------------------------------------------------------
# Fake WAV output, used by ScriptedRunner to simulate a successful ffmpeg
# conversion per the "What a fake runner must do" contract: args[-1] must
# exist and be non-empty (and not "0 audio samples", Q8) on success.
# --------------------------------------------------------------------------


def write_fake_wav(path: Path, num_frames: int = 1600, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * num_frames)


# --------------------------------------------------------------------------
# ScriptedRunner: fake Runner for unit tests
# --------------------------------------------------------------------------


@dataclasses.dataclass
class ProbeStep:
    """One scripted response to a single ffprobe invocation."""

    exit_code: int = 0
    # Raw text sent line-by-line through on_stdout_line. None simulates a
    # probe that produced no/garbage JSON (a failed probe per the contract).
    stdout_json: str | None = None
    stderr: str = ""


@dataclasses.dataclass
class ConvertStep:
    """One scripted response to a single ffmpeg (conversion) invocation."""

    exit_code: int = 0
    # Whether to write a non-empty fake WAV at args[-1] (the temp output
    # file). Per the fake-runner contract this is required for a call to
    # count as a success, regardless of exit_code.
    write_output: bool = True
    stderr: str = ""
    progress_lines: list[str] = dataclasses.field(default_factory=list)


class ScriptedRunner:
    """A fake `Runner` (see spec Interface + "What a fake runner must do").

    Distinguishes ffprobe vs ffmpeg calls by `args[0]` (must be exactly the
    bare string "ffprobe" or "ffmpeg" per the clarified contract). Every call
    is recorded (in `calls`, `probe_calls`, `convert_calls`) for assertions on
    argument contents and call counts. Responses are taken from
    `probe_plan`/`convert_plan` in order; the last scripted step repeats if
    the runner is invoked more times than scripted (so a test can assert on
    "called more than N times" by checking call counts explicitly, without
    the fake raising a confusing error).
    """

    def __init__(
        self,
        probe_plan: list[ProbeStep] | None = None,
        convert_plan: list[ConvertStep] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.probe_calls: list[list[str]] = []
        self.convert_calls: list[list[str]] = []
        self._probe_plan = list(probe_plan or [ProbeStep()])
        self._convert_plan = list(convert_plan or [ConvertStep()])

    def __call__(self, args: list, log, on_stdout_line: Callable[[str], None] | None = None) -> int:
        args = list(args)
        self.calls.append(args)
        command = str(args[0]) if args else ""
        if command == "ffprobe":
            return self._run_probe(args, log, on_stdout_line)
        if command == "ffmpeg":
            return self._run_convert(args, log, on_stdout_line)
        raise AssertionError(
            f"ScriptedRunner got an unexpected args[0]={command!r}; the spec's "
            "fake-runner contract says it must be exactly 'ffprobe' or 'ffmpeg'"
        )

    def _run_probe(self, args, log, on_stdout_line) -> int:
        self.probe_calls.append(args)
        idx = min(len(self.probe_calls) - 1, len(self._probe_plan) - 1)
        step = self._probe_plan[idx]
        log.write("$ " + " ".join(str(a) for a in args) + "\n")
        log.write(step.stderr)
        if on_stdout_line is not None and step.stdout_json is not None:
            for line in step.stdout_json.splitlines():
                on_stdout_line(line)
        return step.exit_code

    def _run_convert(self, args, log, on_stdout_line) -> int:
        self.convert_calls.append(args)
        idx = min(len(self.convert_calls) - 1, len(self._convert_plan) - 1)
        step = self._convert_plan[idx]
        log.write("$ " + " ".join(str(a) for a in args) + "\n")
        log.write(step.stderr)
        if on_stdout_line is not None:
            for line in step.progress_lines:
                on_stdout_line(line)
        if step.write_output:
            write_fake_wav(Path(str(args[-1])))
        return step.exit_code


# --------------------------------------------------------------------------
# ProbeStep / ConvertStep convenience builders
# --------------------------------------------------------------------------


def ok_probe_step(has_video: bool = True, audio_streams: int = 1, duration: float = 5.0) -> ProbeStep:
    streams = []
    if has_video:
        streams.append({"codec_type": "video", "codec_name": "h264"})
    for _ in range(audio_streams):
        streams.append(
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            }
        )
    payload = {"streams": streams, "format": {"duration": f"{duration:.6f}"}}
    return ProbeStep(exit_code=0, stdout_json=json.dumps(payload), stderr="")


def no_audio_probe_step(duration: float = 5.0) -> ProbeStep:
    return ok_probe_step(has_video=True, audio_streams=0, duration=duration)


def unknown_duration_probe_step(has_video: bool = True, audio_streams: int = 1) -> ProbeStep:
    streams = []
    if has_video:
        streams.append({"codec_type": "video", "codec_name": "h264"})
    for _ in range(audio_streams):
        streams.append(
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2}
        )
    payload = {"streams": streams, "format": {}}
    return ProbeStep(exit_code=0, stdout_json=json.dumps(payload), stderr="")


def failed_probe_step(stderr: str = "Invalid data found when processing input\n") -> ProbeStep:
    return ProbeStep(exit_code=1, stdout_json=None, stderr=stderr)


def progress_lines_success(total_seconds: float = 5.0, steps: int = 3) -> list[str]:
    lines: list[str] = []
    for i in range(1, steps + 1):
        t_us = int(total_seconds * 1_000_000 * i / steps)
        lines.append(f"out_time_us={t_us}")
        lines.append("progress=continue" if i < steps else "progress=end")
    return lines


def progress_lines_partial(total_seconds: float = 5.0, fraction: float = 0.4) -> list[str]:
    t_us = int(total_seconds * 1_000_000 * fraction)
    return [f"out_time_us={t_us}", "progress=continue"]
