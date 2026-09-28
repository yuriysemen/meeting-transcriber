"""CLI tests (subprocess): `python -m meeting_transcriber INPUT --extract-only
[-o OUT]`, matching the CLI form from the spec's Decisions (Q1) and AC-M1-01.

Always invoked via [sys.executable, "-m", "meeting_transcriber", ...]
(tests.utils.run_cli / cli_argv) so these tests never depend on PATH for
finding the *package* — only for finding ffmpeg/ffprobe, which some tests
deliberately manipulate (AC-M1-15, -17).
"""

from __future__ import annotations

import re
import shutil

import pytest

from tests.utils import (
    assert_wav_format_ok,
    empty_path_env,
    env_with_prepended_path,
    make_marker_spy_dir,
    probe_duration_seconds,
    run_cli,
)


def test_valid_mp4_extract_only(valid_mp4_5s, tmp_path):
    """AC-M1-01: `transcribe in.mp4 --extract-only -o out.wav` -> exit 0,
    out.wav exists, passes the WAV format check, duration matches the source
    audio duration +/- 0.5 s.
    AC-M1-22 is also exercised here: a small output still passes the WAV
    format check with -rf64 auto in effect."""
    dst = tmp_path / "out.wav"
    src_duration = probe_duration_seconds(valid_mp4_5s)

    result = run_cli([str(valid_mp4_5s), "--extract-only", "-o", str(dst)])

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert dst.exists()
    assert_wav_format_ok(dst)
    out_duration = probe_duration_seconds(dst)
    assert abs(out_duration - src_duration) <= 0.5


def test_missing_input_path(tmp_path):
    """AC-M1-15: input path does not exist -> exit 2, stderr matches
    /not found/i, and ffprobe/ffmpeg are never invoked (checked via spy
    binaries shadowing both on PATH: no marker file should appear)."""
    missing = tmp_path / "missing.mp4"
    marker = tmp_path / "invoked.marker"
    spy_dir = tmp_path / "spybin"
    make_marker_spy_dir(spy_dir, marker, exit_code=1)
    env = env_with_prepended_path(spy_dir)

    result = run_cli([str(missing), "--extract-only"], env=env)

    assert result.returncode == 2
    assert re.search(r"not found", result.stderr, re.IGNORECASE)
    assert not marker.exists(), f"ffprobe/ffmpeg must not run; marker: {marker.read_text() if marker.exists() else None}"


def test_no_audio_stream_cli_never_invokes_ffmpeg(no_audio_mp4_5s, tmp_path):
    """AC-M1-06 (CLI level, optional per the spec's test idea): the real
    ffprobe detects no audio stream and the CLI exits 3 with a clear message
    without ever invoking ffmpeg for conversion (ffmpeg is shadowed by a spy
    that would leave a marker file if called; ffprobe is left real)."""
    marker = tmp_path / "ffmpeg-invoked.marker"
    spy_dir = tmp_path / "spybin"
    make_marker_spy_dir(spy_dir, marker, exit_code=1, names=("ffmpeg",))
    env = env_with_prepended_path(spy_dir)
    dst = tmp_path / "out.wav"

    result = run_cli([str(no_audio_mp4_5s), "--extract-only", "-o", str(dst)], env=env)

    assert result.returncode == 3
    assert re.search(r"no audio stream", result.stderr, re.IGNORECASE)
    assert not marker.exists(), "ffmpeg must not be invoked when there is no audio stream"
    assert not dst.exists()


def test_default_output_path_without_o_flag(valid_mp4_5s, tmp_path):
    """AC-M1-16: no -o -> output defaults to <input dir>/<input stem>.wav
    (Q2); exit 0; stdout prints the resulting WAV path on success."""
    work_dir = tmp_path / "dir"
    work_dir.mkdir()
    in_path = work_dir / "in.mp4"
    shutil.copyfile(valid_mp4_5s, in_path)
    expected_wav = work_dir / "in.wav"

    result = run_cli([str(in_path), "--extract-only"])

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert expected_wav.exists()
    assert_wav_format_ok(expected_wav)
    assert "in.wav" in result.stdout, f"expected the WAV path on stdout, got: {result.stdout!r}"


def test_missing_ffmpeg_and_ffprobe_on_path(valid_mp4_5s, tmp_path):
    """AC-M1-17: ffprobe/ffmpeg not on PATH -> clear error, exit 5, stderr
    matches /ffmpeg|ffprobe/ and /not found|install/i. PATH is emptied while
    python is still launched by its absolute path (sys.executable)."""
    dst = tmp_path / "out.wav"
    env = empty_path_env()

    result = run_cli([str(valid_mp4_5s), "--extract-only", "-o", str(dst)], env=env, timeout=30)

    assert result.returncode == 5, f"stderr={result.stderr!r}"
    assert re.search(r"ffmpeg|ffprobe", result.stderr, re.IGNORECASE)
    assert re.search(r"not found|install", result.stderr, re.IGNORECASE)
    assert not dst.exists()


def test_stderr_clean_on_success_when_not_a_tty(valid_mp4_5s, tmp_path):
    """AC-M1-21: stderr is not a terminal (plain subprocess pipe) -> no
    progress output on stderr on a successful run."""
    dst = tmp_path / "out.wav"

    result = run_cli([str(valid_mp4_5s), "--extract-only", "-o", str(dst)])

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "%" not in result.stderr
    assert not re.search(r"extracting audio", result.stderr, re.IGNORECASE)


def test_stderr_clean_on_failure_when_not_a_tty(no_audio_mp4_5s, tmp_path):
    """AC-M1-21: stderr is not a terminal -> no progress noise on failure
    either; the "one message" rule for errors stays clean (no traceback)."""
    dst = tmp_path / "out.wav"

    result = run_cli([str(no_audio_mp4_5s), "--extract-only", "-o", str(dst)])

    assert result.returncode == 3
    assert "%" not in result.stderr
    assert not re.search(r"extracting audio", result.stderr, re.IGNORECASE)
    assert "Traceback" not in result.stderr
