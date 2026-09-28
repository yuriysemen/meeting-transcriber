"""Unit tests for `meeting_transcriber.audio.extract_audio` against a fake
Runner (see the spec's Interface section and "What a fake runner must do").

No real ffmpeg/ffprobe is invoked here — everything is driven by
ScriptedRunner from tests/utils.py, scripted per-call with ProbeStep /
ConvertStep. These tests never read src/; they only import the public
`meeting_transcriber.audio` module per the Interface contract.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from tests.utils import (
    ConvertStep,
    ProbeStep,
    ScriptedRunner,
    failed_probe_step,
    no_audio_probe_step,
    ok_probe_step,
    progress_lines_partial,
    progress_lines_success,
    stderr_and_logs_text,
    unknown_duration_probe_step,
)

audio = pytest.importorskip(
    "meeting_transcriber.audio", reason="developer's meeting_transcriber.audio not implemented yet"
)
extract_audio = audio.extract_audio
ExtractionError = audio.ExtractionError


def _dummy_src(tmp_path: Path, name: str = "in.mp4") -> Path:
    src = tmp_path / name
    src.write_bytes(b"dummy input bytes - ScriptedRunner never reads this")
    return src


def _expected_log_path(src: Path, dst: Path) -> Path:
    # Q6: log path is <output dir>/<input stem>.ffmpeg.log
    return dst.parent / f"{src.stem}.ffmpeg.log"


# --------------------------------------------------------------------------
# AC-M1-06: no audio stream -> clear error, no conversion attempt
# --------------------------------------------------------------------------


def test_no_audio_stream_rejected_before_conversion(tmp_path):
    """AC-M1-06: probe reports no audio stream -> exit code 3 (Q4), message
    matches /no audio stream/i, and the ffmpeg runner is never called for
    conversion (probe step only)."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(probe_plan=[no_audio_probe_step()])

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(src, dst, runner=runner)

    assert exc_info.value.exit_code == 3
    assert runner.convert_calls == [], "ffmpeg must not be invoked when there is no audio stream"
    assert not dst.exists()


def test_no_audio_stream_error_message_matches_pattern(tmp_path):
    """AC-M1-06: the error message names the problem clearly."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(probe_plan=[no_audio_probe_step()])

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(src, dst, runner=runner)

    assert re.search(r"no audio stream", str(exc_info.value), re.IGNORECASE)


# --------------------------------------------------------------------------
# AC-M1-07: first conversion attempt fails -> tolerant retry
# --------------------------------------------------------------------------


def test_first_attempt_failure_triggers_tolerant_retry(tmp_path, capsys, caplog):
    """AC-M1-07: a failing first ffmpeg attempt is retried once with
    `-fflags +discardcorrupt+genpts`, `-err_detect ignore_err`, and larger
    `-analyzeduration`/`-probesize` than the first attempt. A warning
    matching /retry/i is printed. Exit 0 if the retry succeeds."""
    caplog.set_level(logging.DEBUG)
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=5.0)],
        convert_plan=[
            ConvertStep(exit_code=1, write_output=False, stderr="Error while decoding\n"),
            ConvertStep(exit_code=0, write_output=True),
        ],
    )

    result = extract_audio(src, dst, runner=runner)

    assert result == dst
    assert len(runner.convert_calls) == 2

    first_args = [str(a) for a in runner.convert_calls[0]]
    second_args = [str(a) for a in runner.convert_calls[1]]
    assert "-fflags" in second_args
    assert "+discardcorrupt+genpts" in second_args
    assert "-err_detect" in second_args
    assert "ignore_err" in second_args

    def _value_after(args: list[str], flag: str) -> int | None:
        if flag not in args:
            return None
        return int(args[args.index(flag) + 1])

    first_analyzeduration = _value_after(first_args, "-analyzeduration")
    second_analyzeduration = _value_after(second_args, "-analyzeduration")
    first_probesize = _value_after(first_args, "-probesize")
    second_probesize = _value_after(second_args, "-probesize")
    if first_analyzeduration is not None and second_analyzeduration is not None:
        assert second_analyzeduration > first_analyzeduration
    if first_probesize is not None and second_probesize is not None:
        assert second_probesize > first_probesize
    assert (
        first_analyzeduration is not None or first_probesize is not None
    ), "expected the retry to raise -analyzeduration and/or -probesize per PLAN.md step 3"

    text = stderr_and_logs_text(capsys, caplog)
    assert re.search(r"retry", text, re.IGNORECASE)


# --------------------------------------------------------------------------
# AC-M1-08 / AC-M1-13: both attempts fail
# --------------------------------------------------------------------------


def test_both_attempts_failing_produces_clear_error_and_ordered_log(tmp_path):
    """AC-M1-08: both conversion attempts fail -> clear error, exactly 2
    attempts (no more), and a saved log file.
    AC-M1-13: the log contains, for each attempt, the full command line and
    that attempt's stderr, in order."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=5.0)],
        convert_plan=[
            ConvertStep(exit_code=1, write_output=False, stderr="ATTEMPT-1-STDERR-MARKER\n"),
            ConvertStep(exit_code=1, write_output=False, stderr="ATTEMPT-2-STDERR-MARKER\n"),
        ],
    )

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(src, dst, runner=runner)

    assert exc_info.value.exit_code == 4
    assert len(runner.convert_calls) == 2, "there must be exactly 2 conversion attempts, no more"
    assert not dst.exists()

    log_path = exc_info.value.log_path
    assert log_path is not None, "a failed extraction must save a log (Q6)"
    log_path = Path(log_path)
    assert log_path == _expected_log_path(src, dst)
    assert log_path.exists()

    log_text = log_path.read_text()
    idx1 = log_text.find("ATTEMPT-1-STDERR-MARKER")
    idx2 = log_text.find("ATTEMPT-2-STDERR-MARKER")
    assert idx1 != -1, "log must contain attempt 1's stderr"
    assert idx2 != -1, "log must contain attempt 2's stderr"
    assert idx1 < idx2, "log must record attempts in order"


# --------------------------------------------------------------------------
# AC-M1-22: -rf64 auto on every conversion attempt
# --------------------------------------------------------------------------


def test_rf64_auto_present_on_every_conversion_attempt(tmp_path):
    """AC-M1-22: both the normal and the retry ffmpeg attempt include
    `-rf64 auto` (removes the 4 GB / ~37 h WAV cap)."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=5.0)],
        convert_plan=[
            ConvertStep(exit_code=1, write_output=False, stderr="boom\n"),
            ConvertStep(exit_code=0, write_output=True),
        ],
    )

    extract_audio(src, dst, runner=runner)

    assert len(runner.convert_calls) == 2
    for call in runner.convert_calls:
        args = [str(a) for a in call]
        assert "-rf64" in args, f"-rf64 missing from attempt args: {args!r}"
        assert args[args.index("-rf64") + 1] == "auto"


# --------------------------------------------------------------------------
# AC-M1-23: disk full -> no retry, clear error, exit 4
# --------------------------------------------------------------------------


def test_disk_full_skips_retry_and_leaves_no_output(tmp_path):
    """AC-M1-23: a conversion failure whose stderr contains "No space left on
    device" gets exit code 4, a message matching /disk|space/i, exactly one
    conversion attempt (no tolerant retry), and no WAV/temp file left."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=5.0)],
        convert_plan=[
            ConvertStep(
                exit_code=1,
                write_output=False,
                stderr="Error writing trailer: No space left on device\n",
            ),
        ],
    )

    with pytest.raises(ExtractionError) as exc_info:
        extract_audio(src, dst, runner=runner)

    assert exc_info.value.exit_code == 4
    assert re.search(r"disk|space", str(exc_info.value), re.IGNORECASE)
    assert len(runner.convert_calls) == 1, "disk-full must not trigger the tolerant retry"
    assert not dst.exists()
    assert not any(dst.parent.glob("*.wav")), "no partial/temp WAV may be left behind"


def test_disk_full_error_still_shown_when_log_directory_unwritable(tmp_path):
    """AC-M1-23: if the log's directory is not writable, the log cannot be
    saved, but the clear error must still be raised/shown."""
    out_dir = tmp_path / "readonly_out"
    out_dir.mkdir()
    src = _dummy_src(tmp_path)
    dst = out_dir / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=5.0)],
        convert_plan=[
            ConvertStep(
                exit_code=1,
                write_output=False,
                stderr="Error writing trailer: No space left on device\n",
            ),
        ],
    )

    out_dir.chmod(0o555)
    try:
        with pytest.raises(ExtractionError) as exc_info:
            extract_audio(src, dst, runner=runner)
        assert exc_info.value.exit_code == 4
        assert re.search(r"disk|space", str(exc_info.value), re.IGNORECASE)
    finally:
        out_dir.chmod(0o755)


# --------------------------------------------------------------------------
# AC-M1-19: on_progress contract
# --------------------------------------------------------------------------


def test_on_progress_called_at_least_twice_monotonic_ending_at_one(tmp_path):
    """AC-M1-19 (success path): on_progress is called >= 2 times, all values
    in [0.0, 1.0], never decreasing, last value is exactly 1.0."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=10.0)],
        convert_plan=[
            ConvertStep(
                exit_code=0,
                write_output=True,
                progress_lines=progress_lines_success(total_seconds=10.0, steps=4),
            )
        ],
    )
    values: list[float] = []

    extract_audio(src, dst, runner=runner, on_progress=values.append)

    assert len(values) >= 2, f"on_progress called {len(values)} times, expected >= 2"
    for v in values:
        assert 0.0 <= v <= 1.0, f"progress value out of range: {v}"
    assert values == sorted(values), "progress values must never decrease"
    assert values[-1] == 1.0, "the last progress value on success must be exactly 1.0"


def test_on_progress_never_reaches_one_on_failure(tmp_path):
    """AC-M1-19 (failure path): on failure, the last on_progress value is
    < 1.0 and 1.0 is never reported."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[ok_probe_step(duration=10.0)],
        convert_plan=[
            ConvertStep(
                exit_code=1,
                write_output=False,
                stderr="decoding error\n",
                progress_lines=progress_lines_partial(total_seconds=10.0, fraction=0.3),
            ),
            ConvertStep(
                exit_code=1,
                write_output=False,
                stderr="decoding error\n",
                progress_lines=progress_lines_partial(total_seconds=10.0, fraction=0.5),
            ),
        ],
    )
    values: list[float] = []

    with pytest.raises(ExtractionError):
        extract_audio(src, dst, runner=runner, on_progress=values.append)

    assert 1.0 not in values, "on_progress must never be called with 1.0 on failure"
    if values:
        assert values[-1] < 1.0


# --------------------------------------------------------------------------
# AC-M1-19 (unknown-duration edge case): on_elapsed
# --------------------------------------------------------------------------


def test_on_elapsed_called_when_duration_unknown(tmp_path):
    """Edge case from the spec (tied to AC-M1-19's progress family): when
    ffprobe reports no duration, on_progress cannot compute a fraction and is
    called only with the final 1.0 on success; on_elapsed receives elapsed
    audio time instead."""
    src = _dummy_src(tmp_path)
    dst = tmp_path / "out.wav"
    runner = ScriptedRunner(
        probe_plan=[unknown_duration_probe_step()],
        convert_plan=[
            ConvertStep(
                exit_code=0,
                write_output=True,
                progress_lines=[
                    "out_time_us=1000000",
                    "progress=continue",
                    "out_time_us=2000000",
                    "progress=continue",
                    "out_time_us=3000000",
                    "progress=end",
                ],
            )
        ],
    )
    progress_values: list[float] = []
    elapsed_values: list[float] = []

    extract_audio(
        src,
        dst,
        runner=runner,
        on_progress=progress_values.append,
        on_elapsed=elapsed_values.append,
    )

    assert elapsed_values, "on_elapsed must be called when duration is unknown"
    assert elapsed_values == sorted(elapsed_values), "elapsed values must never decrease"
    assert all(v >= 0 for v in elapsed_values)
    if progress_values:
        assert progress_values == [1.0], (
            "with unknown duration, on_progress must only ever be called with "
            f"the final 1.0, got {progress_values!r}"
        )
