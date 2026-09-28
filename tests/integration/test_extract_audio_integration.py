"""Integration tests: real ffmpeg/ffprobe against lavfi-generated fixtures,
calling the public `meeting_transcriber.audio.extract_audio` API directly
(runner=None -> real subprocess runner). Per Q10, tests may target either the
API or the CLI; these exercise the API so failures are easy to localize to
extraction logic rather than argument parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.utils import assert_wav_format_ok, max_volume_db, probe_duration_seconds

audio = pytest.importorskip(
    "meeting_transcriber.audio", reason="developer's meeting_transcriber.audio not implemented yet"
)
extract_audio = audio.extract_audio
ExtractionError = audio.ExtractionError


def test_fragmented_mp4_extracts_like_valid_mp4(fragmented_mp4_5s, tmp_path):
    """AC-M1-02: fragmented MP4 (frag_keyframe+empty_moov) behaves like
    AC-M1-01: exit 0, WAV format check passes, duration matches source."""
    dst = tmp_path / "out.wav"
    src_duration = probe_duration_seconds(fragmented_mp4_5s)

    result = extract_audio(fragmented_mp4_5s, dst, runner=None)

    assert result == dst
    assert_wav_format_ok(dst)
    out_duration = probe_duration_seconds(dst)
    assert abs(out_duration - src_duration) <= 0.5


def test_silent_audio_is_not_an_error(silent_mp4_5s, tmp_path):
    """AC-M1-03: silent audio (anullsrc) is valid output, not an error."""
    dst = tmp_path / "out.wav"

    result = extract_audio(silent_mp4_5s, dst, runner=None)

    assert result == dst
    assert_wav_format_ok(dst)


def test_first_audio_track_selected_when_sine_is_first(two_track_mp4_sine_first, tmp_path):
    """AC-M1-04: with track 0 = sine, track 1 = anullsrc, the output comes
    from track 0: max_volume > -20 dB."""
    dst = tmp_path / "out.wav"

    extract_audio(two_track_mp4_sine_first, dst, runner=None)

    assert_wav_format_ok(dst)
    assert max_volume_db(dst) > -20.0


def test_first_audio_track_selected_when_silent_is_first(two_track_mp4_silent_first, tmp_path):
    """AC-M1-05: with track 0 = anullsrc, track 1 = sine (reversed order),
    the output still comes from track 0: max_volume <= -80 dB. This proves
    track 0 is picked explicitly (-map 0:a:0), not the "best"/loudest one."""
    dst = tmp_path / "out.wav"

    extract_audio(two_track_mp4_silent_first, dst, runner=None)

    assert_wav_format_ok(dst)
    assert max_volume_db(dst) <= -80.0


def test_no_audio_stream_real_ffprobe(no_audio_mp4_5s, tmp_path):
    """AC-M1-06 (integration variant with a real, video-only fixture): clear
    error with exit code 3, message matches /no audio stream/i."""
    dst = tmp_path / "out.wav"

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(no_audio_mp4_5s, dst, runner=None)

    assert exc_info.value.exit_code == 3
    assert re.search(r"no audio stream", str(exc_info.value), re.IGNORECASE)
    assert not dst.exists()


def test_corrupted_mid_file_still_extracts_most_of_the_audio(
    corrupted_mid_mp4, valid_mp4_5s, tmp_path
):
    """AC-M1-09: random bytes overwritten mid-file (media data, not header):
    exit 0, WAV format check passes, duration >= 50% of the source, whether
    it succeeds on attempt 1 or after the tolerant retry."""
    dst = tmp_path / "out.wav"
    reference_duration = probe_duration_seconds(valid_mp4_5s)

    result = extract_audio(corrupted_mid_mp4, dst, runner=None)

    assert result == dst
    assert_wav_format_ok(dst)
    out_duration = probe_duration_seconds(dst)
    assert out_duration >= 0.5 * reference_duration


def test_truncated_mp4_gives_clear_error_with_moov_atom_log(truncated_mp4, tmp_path):
    """AC-M1-10: truncated MP4 ("moov atom not found") -> clear error, a log
    file at the path in the error, and the log contains "moov atom not
    found".
    AC-M1-13: the log records the command line and stderr of each attempt."""
    dst = tmp_path / "out.wav"

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(truncated_mp4, dst, runner=None)

    assert exc_info.value.exit_code == 4
    log_path = exc_info.value.log_path
    assert log_path is not None
    log_path = Path(log_path)
    assert log_path.exists(), f"expected a saved log at {log_path}"
    log_text = log_path.read_text(errors="replace")
    assert "moov atom not found" in log_text.lower() or "moov atom not found" in log_text
    assert not dst.exists()


def test_zero_byte_file_gives_clear_error_and_log(zero_byte_mp4, tmp_path):
    """AC-M1-11: zero-byte file -> clear error, log file exists.
    AC-M1-13: the saved log is non-empty (records the failing attempt(s))."""
    dst = tmp_path / "out.wav"

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(zero_byte_mp4, dst, runner=None)

    assert exc_info.value.exit_code == 4
    log_path = exc_info.value.log_path
    assert log_path is not None
    log_path = Path(log_path)
    assert log_path.exists()
    assert log_path.stat().st_size > 0
    assert not dst.exists()


def test_text_file_renamed_to_mp4_gives_clear_error_and_log(text_as_mp4, tmp_path):
    """AC-M1-12: text file renamed to .mp4 -> clear error, log file exists.
    AC-M1-13: the saved log is non-empty (records the failing attempt(s))."""
    dst = tmp_path / "out.wav"

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(text_as_mp4, dst, runner=None)

    assert exc_info.value.exit_code == 4
    log_path = exc_info.value.log_path
    assert log_path is not None
    log_path = Path(log_path)
    assert log_path.exists()
    assert log_path.stat().st_size > 0
    assert not dst.exists()


def test_on_progress_with_real_ffmpeg(valid_mp4_10s, tmp_path):
    """AC-M1-19 (integration variant): real ffmpeg on a 10 s fixture calls
    on_progress >= 2 times, values in [0, 1], never decreasing, last is 1.0."""
    dst = tmp_path / "out.wav"
    values: list[float] = []

    extract_audio(valid_mp4_10s, dst, runner=None, on_progress=values.append)

    assert len(values) >= 2, f"on_progress called {len(values)} times, expected >= 2"
    for v in values:
        assert 0.0 <= v <= 1.0
    assert values == sorted(values)
    assert values[-1] == 1.0


def test_non_ascii_and_space_path(non_ascii_space_mp4, tmp_path):
    """Edge case tied to AC-M1-01: non-ASCII, space-containing input path
    ("my meeting ü.mp4") must work; args are passed as a list, not a shell
    string."""
    dst = tmp_path / "out ü.wav"

    result = extract_audio(non_ascii_space_mp4, dst, runner=None)

    assert result == dst
    assert_wav_format_ok(dst)
