"""Session-scoped fixtures for the M1 audio-extraction test suite.

All real media is generated on the fly with ffmpeg `lavfi` sources (never
committed, never a real recording — see CLAUDE.md). Fixtures are session
scoped via `tmp_path_factory` so each is built once per test run.

This file also registers the `slow` marker used for the one real, longer
running scenario in AC-M1-14 (2h audio slow variant).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.utils import run_ffmpeg, which_ffmpeg, which_ffprobe

VIDEO_SRC = "testsrc=size=320x240:rate=15:duration={duration}"
SINE_SRC = "sine=frequency=440:sample_rate=48000:duration={duration}"
ANULLSRC = "anullsrc=channel_layout=stereo:sample_rate=48000:duration={duration}"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: real, longer-running scenario (real Whisper / multi-hour media); "
        "deselect with -m \"not slow\"",
    )


# --------------------------------------------------------------------------
# Binary availability (session scope; individual tests still guard themselves
# so a missing binary produces a clear skip, not a confusing collection error)
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def real_ffmpeg_path() -> str:
    return which_ffmpeg()


@pytest.fixture(scope="session")
def real_ffprobe_path() -> str:
    return which_ffprobe()


# --------------------------------------------------------------------------
# AC-M1-14 slow variants: 2 h audio-only inputs. Two encodings so the slow
# suite exercises both "already the target PCM format" (no decode work) and
# "long compressed recording" (real AAC decode over 2 h) cases.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def long_wav_2h(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """AC-M1-14 (slow): 2 h, already 16 kHz mono PCM WAV — ffmpeg only
    re-wraps/copies samples, no real decode of a long compressed input."""
    out_dir = tmp_path_factory.mktemp("two-hour-wav")
    out_path = out_dir / "long.wav"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=7200",
            "-c:a", "pcm_s16le",
            str(out_path),
        ],
        timeout=300,
    )
    return out_path


@pytest.fixture(scope="session")
def long_m4a_2h(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """AC-M1-14 (slow): 2 h AAC-in-M4A, audio only, low bitrate (24k, keeps
    fixture generation fast) — exercises decoding a long compressed
    recording, which long_wav_2h (already PCM) never does."""
    out_dir = tmp_path_factory.mktemp("two-hour-m4a")
    out_path = out_dir / "long.m4a"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=7200",
            "-c:a", "aac", "-b:a", "24k",
            str(out_path),
        ],
        timeout=300,
    )
    return out_path


# --------------------------------------------------------------------------
# AC-M1-01 / AC-M1-19 / AC-M1-20: valid Teams-like MP4 (H.264 + AAC)
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def valid_mp4_5s(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """AC-M1-01: 5 s, H.264 video + AAC sine audio."""
    out_dir = tmp_path_factory.mktemp("valid-mp4-5s")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
            "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
    )
    return out_path


@pytest.fixture(scope="session")
def valid_mp4_10s(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """AC-M1-19 / AC-M1-20: 10 s valid input, used where the spec calls for a
    longer clip (progress callback, terminal self-updating line)."""
    out_dir = tmp_path_factory.mktemp("valid-mp4-10s")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=10),
            "-f", "lavfi", "-i", SINE_SRC.format(duration=10),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
    )
    return out_path


@pytest.fixture(scope="session")
def non_ascii_space_mp4(valid_mp4_5s: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Edge case tied to AC-M1-01: a copy of the AC-M1-01 fixture at a path
    with spaces and non-ASCII characters ("my meeting ü.mp4")."""
    out_dir = tmp_path_factory.mktemp("non-ascii")
    out_path = out_dir / "my meeting ü.mp4"
    shutil.copyfile(valid_mp4_5s, out_path)
    return out_path


# --------------------------------------------------------------------------
# AC-M1-02: fragmented MP4
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fragmented_mp4_5s(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("fragmented-mp4")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
            "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            "-movflags", "frag_keyframe+empty_moov",
            str(out_path),
        ]
    )
    return out_path


# --------------------------------------------------------------------------
# AC-M1-03: MP4 whose audio is silent
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def silent_mp4_5s(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("silent-mp4")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
            "-f", "lavfi", "-i", ANULLSRC.format(duration=5),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
    )
    return out_path


# --------------------------------------------------------------------------
# AC-M1-04 / AC-M1-05: two audio tracks (sine + silent, in each order)
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def two_track_mp4_sine_first(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """AC-M1-04: track 0 = sine (loud), track 1 = anullsrc (silent)."""
    out_dir = tmp_path_factory.mktemp("two-track-sine-first")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
            "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
            "-f", "lavfi", "-i", ANULLSRC.format(duration=5),
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
    )
    return out_path


@pytest.fixture(scope="session")
def two_track_mp4_silent_first(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """AC-M1-05: track 0 = anullsrc (silent), track 1 = sine (loud)."""
    out_dir = tmp_path_factory.mktemp("two-track-silent-first")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
            "-f", "lavfi", "-i", ANULLSRC.format(duration=5),
            "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
    )
    return out_path


# --------------------------------------------------------------------------
# AC-M1-06: MP4 with no audio stream at all
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def no_audio_mp4_5s(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("no-audio-mp4")
    out_path = out_dir / "in.mp4"
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
            str(out_path),
        ]
    )
    return out_path


# --------------------------------------------------------------------------
# AC-M1-09: random bytes overwritten mid-file (corrupted packets, not header)
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def corrupted_mid_mp4(valid_mp4_5s: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("corrupted-mid-mp4")
    out_path = out_dir / "in.mp4"
    data = bytearray(valid_mp4_5s.read_bytes())
    offset = len(data) // 2
    patch_len = min(4096, len(data) - offset)
    data[offset : offset + patch_len] = os.urandom(patch_len)
    out_path.write_bytes(bytes(data))
    return out_path


# --------------------------------------------------------------------------
# AC-M1-10: truncated MP4 (first half only -> "moov atom not found")
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def truncated_mp4(valid_mp4_5s: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("truncated-mp4")
    out_path = out_dir / "in.mp4"
    data = valid_mp4_5s.read_bytes()
    out_path.write_bytes(data[: len(data) // 2])
    return out_path


# --------------------------------------------------------------------------
# AC-M1-11: zero-byte file
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def zero_byte_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("zero-byte-mp4")
    out_path = out_dir / "empty.mp4"
    out_path.touch()
    return out_path


# --------------------------------------------------------------------------
# AC-M1-12: text file renamed to .mp4
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def text_as_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("text-as-mp4")
    out_path = out_dir / "notes.mp4"
    out_path.write_text(
        "These are meeting notes, not a video file.\n" * 20, encoding="utf-8"
    )
    return out_path


# --------------------------------------------------------------------------
# AC-M1-18: one fixture per format typical of meeting apps/recorders
# --------------------------------------------------------------------------

_FORMAT_BUILDERS: dict[str, list[str]] = {
    "mp4": [
        "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
        "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    ],
    "m4a": [
        "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
        "-c:a", "aac",
    ],
    "mkv": [
        "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
        "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    ],
    "webm": [
        "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
        "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
        "-c:v", "libvpx", "-pix_fmt", "yuv420p", "-c:a", "libopus", "-shortest",
    ],
    "mov": [
        "-f", "lavfi", "-i", VIDEO_SRC.format(duration=5),
        "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    ],
    "mp3": [
        "-f", "lavfi", "-i", SINE_SRC.format(duration=5),
        "-c:a", "libmp3lame",
    ],
    "wav": [
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=5",
        "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
    ],
}


@pytest.fixture(scope="session")
def format_matrix_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | str]:
    """AC-M1-18: {ext: Path} on success, or {ext: "skip reason"} if the local
    ffmpeg build is missing an encoder — the parametrized test skips that case
    with the reason rather than failing or silently omitting it.
    """
    out_dir = tmp_path_factory.mktemp("format-matrix")
    result: dict[str, Path | str] = {}
    for ext, args in _FORMAT_BUILDERS.items():
        out_path = out_dir / f"in.{ext}"
        try:
            run_ffmpeg([*args, str(out_path)])
            result[ext] = out_path
        except RuntimeError as exc:
            result[ext] = f"could not generate .{ext} fixture (missing encoder?): {exc}"
    return result
