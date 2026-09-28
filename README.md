# meeting-transcriber

> Turn meeting recordings into speaker-labeled transcripts — privately, on your own machine.

**Status:** M1 of 4 done (audio extraction); transcription coming in M2. See [docs/PLAN.md](docs/PLAN.md).

## Supported inputs

Any local video or audio recording file ffmpeg can read. Tested formats, and the meeting
apps/recorders that typically produce them (`AC-M1-18` in
[docs/specs/M1-audio-extraction.md](docs/specs/M1-audio-extraction.md)):

| Format | Typical codecs | Produced by |
|---|---|---|
| MP4 | H.264 + AAC | Microsoft Teams, Google Meet, Zoom (video) |
| M4A | AAC | Zoom (audio-only) |
| MKV | H.264 + AAC | OBS Studio |
| WebM | VP8/VP9 + Opus | Browser-based recorders |
| MOV | H.264 + AAC | QuickTime |
| MP3 | — | Voice memo apps |
| WAV | PCM (any sample rate/channels) | Already-extracted audio |

Other containers/codecs ffmpeg can decode generally work too, even if not explicitly tested.

- **Local files only.** There is no integration with meeting apps and no `--url` /
  download-from-a-link support (see "Out of scope" in `docs/PLAN.md`).
- **Legacy Webex ARF/WRF recordings are not supported.** These are proprietary formats ffmpeg
  cannot read; convert them with Webex's own recording-format converter to MP4 first, then pass
  the MP4 to `transcribe`.

## Quick start (audio extraction)

Transcription (M2+) is not implemented yet; M1 exposes audio extraction on its own so it can be
used and tested end to end:

```bash
pip install -e .
transcribe meeting.mp4 --extract-only
# -> meeting.wav (16 kHz mono 16-bit PCM), path printed on stdout
```

`-o/--output PATH` chooses a different destination (default: `<input dir>/<input name>.wav`,
overwritten if it already exists). If the default (or an explicit `-o`) output path would be the
same as the input file itself (e.g. `transcribe x.wav --extract-only`), the tool refuses with
exit 2 instead of overwriting the source. A missing output directory is created automatically.
Running `transcribe meeting.mp4` without `--extract-only` exits with an error, since
transcription doesn't exist yet.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Unexpected error: one-line message; set `MEETING_TRANSCRIBER_DEBUG=1` to see the full traceback |
| 2 | Usage error, e.g. input file not found, output path same as input, or `--extract-only` omitted |
| 3 | Input has no audio stream |
| 4 | File unreadable, or extraction failed after the tolerant retry (includes disk full) |
| 5 | `ffmpeg`/`ffprobe` not found on `PATH` |
| 130 | Interrupted with Ctrl-C; temp files are cleaned up, no partial output is left |

On failure, a human-readable message is printed to stderr; for code 4 it also names a saved
`<output dir>/<input stem>.ffmpeg.log` with the full `ffprobe`/`ffmpeg` command lines and their
stderr. See [docs/troubleshooting-ffmpeg.md](docs/troubleshooting-ffmpeg.md).

## Limits

- **Recording length:** supported up to 8 hours; tested up to 2 hours
  (`AC-M1-14` slow test, [docs/reports/M1-test-report.md](docs/reports/M1-test-report.md)).
- **Disk space:** the extracted WAV (16 kHz, mono, 16-bit PCM) is about 115 MB per hour of
  recording (16000 samples/s × 2 bytes × 1 channel × 3600 s), regardless of the source format or
  length of silence.
- A full disk during extraction is reported as a clear error; no partial WAV file is left behind.

## Privacy

Audio extraction runs entirely locally via `ffmpeg`; no recording or audio data leaves your
machine at this stage. Only process recordings you own or have the rights to, and only with the
participants' consent.

<!-- Sections to fill in as the project progresses (only for features that exist):
2. Demo GIF + sample output
5. Configuration (providers: local / remote-selfhosted / cloud)
6. Architecture diagram
7. Benchmarks (speed, peak RAM & accuracy per model size, CPU vs GPU; 1 h and 4 h recordings)
9. Troubleshooting: see docs/troubleshooting-ffmpeg.md (linked above); expand this section if
   transcription/diarization gain their own troubleshooting needs in M2/M3.
11. Roadmap
12. License & credits (Whisper MIT, pyannote model terms)

GitHub About / LinkedIn / Upwork texts are derived from this README: see docs/promo/ (written in M4).
-->
