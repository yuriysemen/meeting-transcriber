"""AC-M1-18: one parametrized CLI test across the input formats typical of
meeting apps and recorders. Fixtures come from the session-scoped
`format_matrix_media` fixture in tests/conftest.py (built once with lavfi
testsrc/sine, real ffmpeg).
"""

from __future__ import annotations

import pytest

from tests.utils import assert_wav_format_ok, probe_duration_seconds, run_cli

# MP4 H.264+AAC (Teams/Meet/Zoom), M4A AAC (Zoom audio-only), MKV H.264+AAC
# (OBS), WebM VP8/VP9+Opus (browser recorders), MOV H.264+AAC (QuickTime),
# MP3 (voice memos), WAV 44.1 kHz stereo (already audio, needs resample and
# downmix).
FORMATS = ["mp4", "m4a", "mkv", "webm", "mov", "mp3", "wav"]


@pytest.mark.parametrize("ext", FORMATS)
def test_format_matrix(ext, format_matrix_media, tmp_path):
    """AC-M1-18: for every format, exit 0, WAV format check passes, duration
    matches the source +/- 0.5 s. If an encoder is missing from the local
    ffmpeg build, that one case is skipped with a clear reason (never a
    silent pass or an unrelated failure)."""
    media = format_matrix_media[ext]
    if isinstance(media, str):
        pytest.skip(media)

    src = media
    dst = tmp_path / f"out.{ext}.wav"
    src_duration = probe_duration_seconds(src)

    result = run_cli([str(src), "--extract-only", "-o", str(dst)])

    assert result.returncode == 0, f"format={ext} stderr={result.stderr!r}"
    assert_wav_format_ok(dst)
    out_duration = probe_duration_seconds(dst)
    assert abs(out_duration - src_duration) <= 0.5
