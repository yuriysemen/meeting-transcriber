# Troubleshooting: audio extraction (FFmpeg)

`transcribe INPUT --extract-only` runs `ffprobe` then `ffmpeg` under the hood (see
[docs/specs/M1-audio-extraction.md](specs/M1-audio-extraction.md) for the full pipeline: probe →
convert → tolerant retry → clear error + saved log). This page explains what each kind of broken
input looks like, what the tool does about it, and what you can do next.

To inspect any input file yourself the same way the tool does:

```bash
ffprobe -hide_banner -show_streams -show_format -of json meeting.mp4
```

**Status of the cases below:** these are the synthetic broken fixtures from `docs/PLAN.md` →
"Test strategy → Broken files" (per decision Q9 in the M1 spec: no real failing recordings have
been collected yet, so the synthetic fixtures stand in for them). Error lines were captured by
generating each fixture with ffmpeg `lavfi` and running `.venv/bin/transcribe` against it.

## Truncated MP4 (cut off partway through, e.g. an interrupted transfer)

**How to recognise it** — `ffprobe`/`ffmpeg` report:

```
[mov,mp4,m4a,3gp,3g2,mj2 @ 0x...] moov atom not found
truncated.mp4: Invalid data found when processing input
```

The `moov atom` (MP4's index, usually written last) is missing because the file ends before it
was written.

**What the tool does:** the probe step runs twice (normal, then with larger
`-analyzeduration`/`-probesize`); both fail identically since no amount of extra buffering
recovers a missing atom. The tool never attempts a conversion. It exits with **code 4** and a
message naming the input file and the saved log at `<output dir>/<input stem>.ffmpeg.log`
(command lines + full stderr of both probe attempts).

**What you can do:** the file is genuinely incomplete — ffmpeg cannot reconstruct data that was
never written. Re-export or re-copy the recording from its source; if it came from a cloud
meeting app, check the app's own recording library for a complete copy.

## Corrupted bytes mid-file (media data damaged, header intact)

**How to recognise it** — no probe error; the file still identifies as valid MP4/H.264/AAC.
Decode-time warnings appear only during conversion, e.g.:

```
[aac @ 0x...] channel element 0.0 is not allocated
[aist#0:1/aac @ 0x...] Error submitting packet to decoder: Invalid data found when processing input
```

**What the tool does:** the probe succeeds (the container index is intact), so conversion is
attempted. `ffmpeg` decodes around the damaged packets on its own; in testing, a single ~4 KB
corrupted region in a 5 s clip still converted successfully on the **first** attempt, producing a
WAV about 93% of the source duration (silence/skips where packets were undecodable). If the
damage is heavier, the first attempt can fail outright — the tool then automatically retries with
`-fflags +discardcorrupt+genpts -err_detect ignore_err` and larger probe sizes; a `retry` warning
is printed to stderr for that case. Either way, when a usable WAV is produced the exit code is
**0** and no log file is written.

**What you can do:** nothing needed on a successful exit — check the resulting WAV's duration
against the source recording's expected length (`ffprobe -show_format`) if you're unsure how much
was skipped. If both attempts fail, you get the exit-4 error and log as in the other cases below;
re-export the recording from its original source.

## Zero-byte file

**How to recognise it** — `ffprobe` reports:

```
[mov,mp4,m4a,3gp,3g2,mj2 @ 0x...] Format mov,mp4,m4a,3gp,3g2,mj2 detected only with low score of 1, misdetection possible!
[mov,mp4,m4a,3gp,3g2,mj2 @ 0x...] moov atom not found
empty.mp4: Invalid data found when processing input
```

**What the tool does:** same as a truncated file — both probe attempts fail, no conversion is
attempted, exit **code 4**, log saved with both attempts' command lines and stderr.

**What you can do:** the recording never actually produced output (recording stopped
immediately, disk was full during capture, or an upload/export failed silently). Re-record or
re-export; check free disk space on the recording device beforehand.

## Text file renamed to `.mp4`

**How to recognise it** — same error shape as the zero-byte case (ffprobe cannot find any known
container signature, regardless of the extension):

```
[mov,mp4,m4a,3gp,3g2,mj2 @ 0x...] Format mov,mp4,m4a,3gp,3g2,mj2 detected only with low score of 1, misdetection possible!
[mov,mp4,m4a,3gp,3g2,mj2 @ 0x...] moov atom not found
notes.mp4: Invalid data found when processing input
```

**What the tool does:** identical to the zero-byte case — exit **code 4**, log saved with both
probe attempts.

**What you can do:** the file's extension doesn't match its actual content. Check what the file
really is (`file notes.mp4` on macOS/Linux) and pass the tool the real recording instead.

## No audio stream (video-only file)

**How to recognise it** — `ffprobe` succeeds and returns valid JSON, but the `streams` array has
no entry with `"codec_type": "audio"` — for example a video-only capture has only:

```json
{"streams": [{"codec_type": "video", ...}], "format": {...}}
```

**What the tool does:** rejected immediately after the (single, successful) probe — no `ffmpeg`
conversion is attempted at all. Exit **code 3**; stderr reads
`No audio stream found in <path>`. No log file is written, since nothing failed at the ffmpeg
level.

**What you can do:** check whether audio was actually captured (muted microphone/system audio,
or a screen-recording tool configured for video only). Re-record with audio enabled. If you
believe the file does contain audio that another player recognises, run
`ffprobe -hide_banner -show_streams -of json` on it yourself and check the `codec_type` of every
stream before reporting an issue.

## Unexpected errors

If something goes wrong outside the ffprobe/ffmpeg pipeline itself (a bug, not a bad input file),
`transcribe` still never prints a raw Python traceback by default. It exits with **code 1** and a
one-line message: `Error: unexpected error: <ExceptionType>: <message> (while processing <path>)`,
followed by a hint to set `MEETING_TRANSCRIBER_DEBUG=1` and rerun. With that variable set, the
full traceback is printed to stderr as well, which is what to include when reporting a bug. No
partial WAV or temp file is left behind in either case.

## Webex legacy ARF/WRF recordings

Classic Cisco Webex recordings saved as `.arf` or `.wrf` are a proprietary container ffmpeg
cannot read at all — `ffprobe` won't recognise them as media, and the error message from this
tool will look like the zero-byte/renamed-text case above (misdetection, no atom found), which is
misleading for this specific cause. This is **not supported** and is out of scope for M1 (see
`docs/PLAN.md` → "Out of scope"). Convert the recording to MP4 first with Cisco's own Webex
Network Recording Player / Recording Format Converter (exports the ARF/WRF to MP4), then pass the
resulting MP4 to `transcribe`.

## Adding real cases

The cases above are synthetic stand-ins (decision Q9 in the M1 spec). When a real recording
fails extraction:

1. Run `ffprobe -hide_banner -show_streams -show_format -of json <file>` on it and copy the
   **error output** (not the file) into a new section on this page, in the same
   recognise/tool-behavior/user-action shape as above.
2. Include the tool's own exit code and log excerpt (`<output dir>/<input stem>.ffmpeg.log`) if
   one was produced.
3. **Never commit the media file itself** — only the captured ffprobe/ffmpeg text output. This
   follows the project rule in `CLAUDE.md`: real meeting recordings are never committed.
