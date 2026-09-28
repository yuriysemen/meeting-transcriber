# M1 — Robust audio extraction — Test report

**Spec:** `docs/specs/M1-audio-extraction.md`
**Suite:** `tests/` (unit, integration, cli)
**Run against:** `.venv/bin/pytest` (project venv, `meeting-transcriber 0.1.0` installed), Python 3.12.10, ffmpeg 8.0.1 (libx264, libvpx, libopus, aac, libmp3lame, pcm_s16le all present).
**Date:** 2026-09-28 (round 2)

## Summary

| Run | Command | Passed | Failed | Skipped | Deselected | Total collected |
|---|---|---|---|---|---|---|
| Fast | `.venv/bin/pytest -q` | 39 | 0 | 0 | 2 (slow) | 41 |
| Slow | `.venv/bin/pytest -q -m slow` | 2 | 0 | 0 | 39 (not slow) | 41 |
| **Combined** | | **41** | **0** | **0** | | **41** |

Slow-test timings (`--durations=0`, `-m slow`): `test_ffmpeg_flooding_stderr_2h_audio_does_not_deadlock` (WAV input) — 0.57 s setup + 0.66 s call; `test_ffmpeg_flooding_stderr_2h_m4a_audio_does_not_deadlock` (AAC/M4A input) — 8.95 s setup (fixture generation) + 1.23 s call. Both well inside their timeouts (300 s / 600 s) and the whole `-m slow` run finishes in ~11 s.

All 24 acceptance criteria pass. No product bugs found. No test fixes were needed — every test written against the spec passed as written, with no attribute-name or path-equality mismatches.

## Changes in round 2

Orchestrator review of `cli/test_stderr_robustness_cli.py::test_ffmpeg_flooding_stderr_2h_audio_does_not_deadlock` found two weaknesses, both fixed:
1. **Weak assertions.** The test only checked exit 0 and file existence. It now also asserts the full WAV format check (`assert_wav_format_ok`) and that output duration is 7200 s ± 0.5 s. The fast AC-M1-14 test and the new slow test share this via a `_run_2h_flood_case` helper.
2. **No compressed-input coverage.** The original 2 h fixture was already a 16 kHz mono PCM WAV, so decoding a long compressed recording was never exercised. Added `test_ffmpeg_flooding_stderr_2h_m4a_audio_does_not_deadlock` (also `@pytest.mark.slow`): a 2 h AAC-in-M4A, audio-only, low-bitrate (24k) input, same assertions. The two 2 h fixture builders were extracted into session-scoped fixtures `long_wav_2h` / `long_m4a_2h` in `tests/conftest.py` (each built once per run).

Also added tests for the new **AC-M1-24** (unexpected exception in the CLI → exit 1, one-line message, no traceback; `MEETING_TRANSCRIBER_DEBUG=1` → traceback shown), per the developer finishing that row: `tests/cli/test_unexpected_error_cli.py`, following the spec's own test idea — a subprocess script that patches `meeting_transcriber.audio.extract_audio` before importing the CLI, then calls `runpy.run_module("meeting_transcriber", run_name="__main__")`. Both the default and `MEETING_TRANSCRIBER_DEBUG=1` modes are covered and pass; no internals had to be guessed at beyond what the spec row states.

## AC → test mapping

| AC ID | Test(s) | Result |
|---|---|---|
| AC-M1-01 | `cli/test_extract_cli.py::test_valid_mp4_extract_only`, `integration/test_extract_audio_integration.py::test_non_ascii_and_space_path` (non-ASCII/space edge case) | PASS |
| AC-M1-02 | `integration/test_extract_audio_integration.py::test_fragmented_mp4_extracts_like_valid_mp4` | PASS |
| AC-M1-03 | `integration/test_extract_audio_integration.py::test_silent_audio_is_not_an_error` | PASS |
| AC-M1-04 | `integration/test_extract_audio_integration.py::test_first_audio_track_selected_when_sine_is_first` | PASS |
| AC-M1-05 | `integration/test_extract_audio_integration.py::test_first_audio_track_selected_when_silent_is_first` | PASS |
| AC-M1-06 | `unit/test_extract_audio_unit.py::test_no_audio_stream_rejected_before_conversion`, `unit/test_extract_audio_unit.py::test_no_audio_stream_error_message_matches_pattern`, `integration/test_extract_audio_integration.py::test_no_audio_stream_real_ffprobe`, `cli/test_extract_cli.py::test_no_audio_stream_cli_never_invokes_ffmpeg` | PASS |
| AC-M1-07 | `unit/test_extract_audio_unit.py::test_first_attempt_failure_triggers_tolerant_retry` | PASS |
| AC-M1-08 | `unit/test_extract_audio_unit.py::test_both_attempts_failing_produces_clear_error_and_ordered_log` | PASS |
| AC-M1-09 | `integration/test_extract_audio_integration.py::test_corrupted_mid_file_still_extracts_most_of_the_audio` | PASS |
| AC-M1-10 | `integration/test_extract_audio_integration.py::test_truncated_mp4_gives_clear_error_with_moov_atom_log` | PASS |
| AC-M1-11 | `integration/test_extract_audio_integration.py::test_zero_byte_file_gives_clear_error_and_log` | PASS |
| AC-M1-12 | `integration/test_extract_audio_integration.py::test_text_file_renamed_to_mp4_gives_clear_error_and_log` | PASS |
| AC-M1-13 | `unit/test_extract_audio_unit.py::test_both_attempts_failing_produces_clear_error_and_ordered_log` (ordering), `integration/test_extract_audio_integration.py::test_truncated_mp4_gives_clear_error_with_moov_atom_log`, `::test_zero_byte_file_gives_clear_error_and_log`, `::test_text_file_renamed_to_mp4_gives_clear_error_and_log` (content) | PASS |
| AC-M1-14 | `cli/test_stderr_robustness_cli.py::test_ffmpeg_flooding_stderr_does_not_deadlock` (fast), `::test_ffmpeg_flooding_stderr_2h_audio_does_not_deadlock` (slow, WAV input), `::test_ffmpeg_flooding_stderr_2h_m4a_audio_does_not_deadlock` (slow, AAC/M4A input) | PASS |
| AC-M1-15 | `cli/test_extract_cli.py::test_missing_input_path` | PASS |
| AC-M1-16 | `cli/test_extract_cli.py::test_default_output_path_without_o_flag` | PASS |
| AC-M1-17 | `cli/test_extract_cli.py::test_missing_ffmpeg_and_ffprobe_on_path` | PASS |
| AC-M1-18 | `cli/test_format_matrix_cli.py::test_format_matrix[mp4\|m4a\|mkv\|webm\|mov\|mp3\|wav]` (7 cases, all generated — no encoder was missing) | PASS |
| AC-M1-19 | `unit/test_extract_audio_unit.py::test_on_progress_called_at_least_twice_monotonic_ending_at_one`, `::test_on_progress_never_reaches_one_on_failure`, `::test_on_elapsed_called_when_duration_unknown`, `integration/test_extract_audio_integration.py::test_on_progress_with_real_ffmpeg` | PASS |
| AC-M1-20 | `cli/test_progress_tty_cli.py::test_progress_shown_as_self_updating_line_on_a_tty` | PASS |
| AC-M1-21 | `cli/test_extract_cli.py::test_stderr_clean_on_success_when_not_a_tty`, `::test_stderr_clean_on_failure_when_not_a_tty` | PASS |
| AC-M1-22 | `unit/test_extract_audio_unit.py::test_rf64_auto_present_on_every_conversion_attempt`, `cli/test_extract_cli.py::test_valid_mp4_extract_only` (small-output format check) | PASS |
| AC-M1-23 | `unit/test_extract_audio_unit.py::test_disk_full_skips_retry_and_leaves_no_output`, `::test_disk_full_error_still_shown_when_log_directory_unwritable` | PASS |
| AC-M1-24 | `cli/test_unexpected_error_cli.py::test_unexpected_error_default_mode_no_traceback`, `::test_unexpected_error_debug_mode_shows_traceback` | PASS |

## Test fixes

None. Every assumption documented when the suite was written (`ExtractionError.exit_code`/`.log_path` attribute names, the log-path formula, the ffprobe JSON shape fed to the fake runner, the retry-warning being observable via `capsys`/`caplog`, etc.) matched the implementation on the first run — no test needed adjustment. The round-2 additions (AC-M1-14 strengthening, AC-M1-24) also passed as written on the first run.

## Bug reports

None. No product failures were observed; all 24 acceptance criteria pass against the implementation in `src/meeting_transcriber`.
