"""AC-M1-14: an ffmpeg that writes >= 5 MB to stderr and then exits 0 must
not deadlock the CLI on a full pipe, and must finish within 30 s.

The fake ffmpeg forwards all arguments to the real ffmpeg (so the conversion
is genuinely correct) and then floods its own stderr with >= 6 MB of text
before exiting with the real ffmpeg's exit code. It is placed first on PATH
so the real runner's subprocess call resolves "ffmpeg" to it.

The two `@pytest.mark.slow` variants below both use a 2 h input (recording
length is supported up to 8 h, tested up to 2 h per the spec) but differ in
source encoding:
- `long_wav_2h` is already the 16 kHz mono PCM WAV target format, so ffmpeg
  does no real decode work.
- `long_m4a_2h` is AAC-in-M4A (audio only, low bitrate to keep fixture
  generation fast), so it actually exercises decoding a long compressed
  recording -- unlike the WAV variant.
Both assert the full WAV format check and that duration is preserved
(7200 s +/- 0.5 s), not just exit 0 and file existence.
"""

from __future__ import annotations

import subprocess

import pytest

from tests.utils import (
    assert_wav_format_ok,
    cli_argv,
    env_with_prepended_path,
    make_flooding_ffmpeg_dir,
    probe_duration_seconds,
)


def test_ffmpeg_flooding_stderr_does_not_deadlock(valid_mp4_5s, real_ffmpeg_path, tmp_path):
    """AC-M1-14: finishes within 30 s with exit 0; no deadlock on a full
    pipe (PLAN.md step 5). subprocess's own `timeout=` turns a deadlock into
    a clean test failure (TimeoutExpired) instead of an actual hang."""
    bin_dir = tmp_path / "fakebin"
    make_flooding_ffmpeg_dir(bin_dir, real_ffmpeg_path)
    env = env_with_prepended_path(bin_dir)
    dst = tmp_path / "out.wav"

    result = subprocess.run(
        cli_argv(str(valid_mp4_5s), "--extract-only", "-o", str(dst)),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, f"stderr(tail)={result.stderr[-2000:]!r}"
    assert dst.exists()


def _run_2h_flood_case(src, real_ffmpeg_path, tmp_path, *, timeout: float) -> None:
    bin_dir = tmp_path / "fakebin"
    make_flooding_ffmpeg_dir(bin_dir, real_ffmpeg_path)
    env = env_with_prepended_path(bin_dir)
    dst = tmp_path / "out.wav"

    result = subprocess.run(
        cli_argv(str(src), "--extract-only", "-o", str(dst)),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )

    assert result.returncode == 0, f"stderr(tail)={result.stderr[-2000:]!r}"
    assert_wav_format_ok(dst)
    out_duration = probe_duration_seconds(dst)
    assert abs(out_duration - 7200.0) <= 0.5, f"duration={out_duration}"


@pytest.mark.slow
def test_ffmpeg_flooding_stderr_2h_audio_does_not_deadlock(
    real_ffmpeg_path, long_wav_2h, tmp_path
):
    """AC-M1-14 (slow variant, PCM input): a 2 h, already-16kHz-mono-PCM WAV
    combined with the flooding fake ffmpeg still finishes without deadlock,
    passes the WAV format check, and preserves duration (7200 s +/- 0.5 s)."""
    _run_2h_flood_case(long_wav_2h, real_ffmpeg_path, tmp_path, timeout=300)


@pytest.mark.slow
def test_ffmpeg_flooding_stderr_2h_m4a_audio_does_not_deadlock(
    real_ffmpeg_path, long_m4a_2h, tmp_path
):
    """AC-M1-14 (slow variant, compressed input): a 2 h AAC-in-M4A,
    low-bitrate, audio-only recording -- unlike the WAV variant, this
    exercises real decoding of a long compressed file -- combined with the
    flooding fake ffmpeg still finishes without deadlock, passes the WAV
    format check, and preserves duration (7200 s +/- 0.5 s)."""
    _run_2h_flood_case(long_m4a_2h, real_ffmpeg_path, tmp_path, timeout=600)
