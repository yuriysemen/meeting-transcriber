# Changelog

All notable changes to this project are documented here. See `docs/PLAN.md` for the roadmap and
`docs/specs/` for per-milestone specs.

## Unreleased — M1 (audio extraction)

Spec: `docs/specs/M1-audio-extraction.md` · Test report: `docs/reports/M1-test-report.md`
(38/38 tests passed, all 23 acceptance criteria met).

### Added
- `transcribe INPUT --extract-only [-o/--output PATH]` CLI: extracts 16 kHz mono 16-bit PCM WAV
  audio from any local video/audio file ffmpeg can read. Running without `--extract-only` exits
  with an error, since transcription (M2) doesn't exist yet.
- Public API `meeting_transcriber.audio.extract_audio(src, dst, runner=None, on_progress=None, *, on_elapsed=None) -> Path`.
- Robust extraction pipeline: `ffprobe` first (rejects files with no audio stream before any
  conversion is attempted; explicit first-audio-track selection via `-map 0:a:0`), one tolerant
  retry on conversion failure (`-fflags +discardcorrupt+genpts -err_detect ignore_err`, larger
  `-analyzeduration`/`-probesize`), and a clear error with a saved ffmpeg log
  (`<output dir>/<input stem>.ffmpeg.log`) when extraction cannot succeed.
- `-rf64 auto` on every conversion attempt, so WAV output over 4 GB (~37 h) does not break.
- Self-updating terminal progress line when stderr is a TTY; silent otherwise. Falls back to
  elapsed time when the source duration is unknown.
- Exit codes: `0` success, `1` unexpected error (one-line message; set
  `MEETING_TRANSCRIBER_DEBUG=1` for the full traceback), `2` usage error / input not found /
  output path same as input, `3` no audio stream, `4` file unreadable or extraction failed after
  retry (including disk full), `5` ffmpeg/ffprobe missing, `130` interrupted with Ctrl-C (temp
  files cleaned up).
- Refuses to overwrite the input file: if the default (or explicit `-o`) output path is the same
  as the input, exits 2 instead of converting (spec decision Q11).
- A missing output directory is created automatically (Q12).
- No ffmpeg log is saved for the "no audio stream" case (Q14): it's a clean detection, not a
  failed ffprobe/ffmpeg run.
- Disk-full detection skips the tolerant retry and leaves no partial output.
- Support for input formats typical of common meeting apps and recorders: MP4 (Teams/Meet/Zoom),
  M4A (Zoom audio-only), MKV (OBS), WebM (browser recorders), MOV (QuickTime), MP3 (voice
  memos), WAV.
- `docs/troubleshooting-ffmpeg.md`: recognise/behavior/action guide for broken-input cases
  (truncated, corrupted, zero-byte, misnamed, no-audio-stream), plus a note on unsupported
  legacy Webex ARF/WRF recordings.
- README: status, supported inputs, extraction quick start with exit codes, limits, privacy note.

### Known limitations (tracked for later milestones)
- Transcription, diarization, and export formats are not implemented yet (M2/M3).
- No real (previously failing) recordings have been collected yet; broken-input tests use
  synthetic fixtures generated with ffmpeg `lavfi` (spec decision Q9).
- Recording length is supported up to 8 h; tested up to 2 h. Benchmarks (processing time, peak
  RAM) are deferred to M4.
