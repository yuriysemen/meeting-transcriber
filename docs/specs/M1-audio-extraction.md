# M1 — Robust audio extraction

**Status:** approved (2026-09-28). Q1–Q10 accepted with the proposed defaults.  
**Source:** docs/PLAN.md → "Audio extraction (FFmpeg robustness)", "Test strategy", "Scope", "Milestones" (1)

## Goal
A user can turn a meeting recording (video or audio-only, from any meeting app or recorder, e.g. Teams MP4, Zoom M4A, OBS MKV) into a 16 kHz mono 16-bit PCM WAV from the CLI. Files without audio are rejected up front, damaged files get one tolerant retry, and unrecoverable files end with a clear message plus a saved ffmpeg log. This is not a hang or a traceback.

> **Note on "previously failing files":** PLAN.md asks for 3–5 real failing files and their `ffprobe` output in `docs/troubleshooting-ffmpeg.md` before implementation. **None have been collected yet.** Until they are, the synthetic broken files from PLAN.md "Test strategy → Broken files" (truncated MP4, corrupted packets, zero-byte file, text renamed to `.mp4`) stand in for them. See Q9.

## User stories
- **US-1** As a user, I want to convert a recording into 16 kHz mono PCM WAV, so that it is ready for transcription.
- **US-2** As a user, I want a file with no audio stream rejected immediately with a clear message, so that I don't wait for a conversion that cannot work.
- **US-3** As a user with a multi-track recording, I want the audio track to be selected explicitly and predictably, so that the output is always from the same track.
- **US-4** As a user with a slightly damaged recording, I want the tool to retry with tolerant settings automatically, so that I still get usable audio.
- **US-5** As a user with an unrecoverable file, I want a clear error and a saved ffmpeg log, so that I can understand or report the problem.
- **US-6** As a user with a long (multi-hour) recording, I want extraction to finish without hanging, so that I can process full meetings.
- **US-7** As a developer/tester, I want a minimal CLI entry point that runs extraction only, so that M1 can be exercised end-to-end before ASR exists (M2).
- **US-8** As a user, I want to pass any common video or audio recording format (from Teams, Zoom, Meet, OBS, browser recorders, voice memos), so that I don't have to convert it myself first.
- **US-9** As a user with a long recording, I want to see extraction progress, so that I know the tool is working and roughly how long is left.
- **US-10** As a user with a very long recording or a nearly full disk, I want extraction to either succeed or fail with a clear message, so that I never get a broken or partial WAV.

## Interface (agreed contract for developer and tester)
The developer implements this and the tester codes unit tests against it. Neither needs to read the other's code.

```python
# meeting_transcriber.audio
Runner = Callable[[list[str], TextIO, Callable[[str], None] | None], int]
#        (args, log, on_stdout_line) -> exit code
#        Runs one ffprobe/ffmpeg command. Writes the full command line and all of its
#        stderr to `log`. Calls `on_stdout_line` for each stdout line if given.

def extract_audio(
    src: Path,
    dst: Path,
    runner: Runner | None = None,                     # None → real subprocess runner
    on_progress: Callable[[float], None] | None = None,  # fraction 0.0–1.0
) -> Path: ...
```

**What a fake runner must do** (clarified 2026-09-28, after implementation started):
- `args[0]` is the bare command name, `"ffprobe"` or `"ffmpeg"`, resolved through `PATH`.
- **ffprobe** is called with `-of json -show_streams -show_format`. It succeeds only if the runner returns 0 **and** sends valid JSON through `on_stdout_line`, e.g. `{"streams":[{"codec_type":"audio"}],"format":{"duration":"5.0"}}`. Anything else counts as a failed probe.
- **ffmpeg:** the **last argument** (`args[-1]`) is the temporary output file. A conversion succeeds only if the runner returns 0 **and** that file exists and is non-empty (Q8: output with 0 audio samples is a failure). A fake that simulates success must write a non-empty file there, e.g. by copying a real WAV fixture or exec'ing the real ffmpeg.
- **Progress:** ffmpeg is called with `-progress pipe:1 -nostats`. A fake can send lines such as `out_time_us=2500000` and `progress=end` through `on_stdout_line`.
- `extract_audio` also takes a keyword-only `on_elapsed: Callable[[float], None] | None`. It reports elapsed audio time when the duration is unknown (see "Unknown duration" below).

Errors are raised as subclasses of `meeting_transcriber.audio.ExtractionError`. Each one carries the exit code from Q4 and, when a log was saved, its path. The CLI maps them to the message and exit code; it never shows a traceback.

## Acceptance criteria
"WAV format check" means: `ffprobe` on the output reports exactly one audio stream with `codec_name=pcm_s16le`, `sample_rate=16000`, `channels=1`, and no video stream (PLAN.md target: `-vn -ac 1 -ar 16000 -c:a pcm_s16le`).
"Clear error" means: nonzero exit code, one human-readable message on stderr that names the input file, no Python traceback in stderr, and no WAV left at the output path.
The CLI form below uses the proposed defaults from Q1–Q4.

| ID | Given | When | Then | Test idea |
|---|---|---|---|---|
| AC-M1-01 | Valid Teams-like MP4 (H.264 + AAC), 5 s | `transcribe in.mp4 --extract-only -o out.wav` | Exit 0; `out.wav` exists; passes WAV format check; duration = source audio duration ±0.5 s | lavfi `testsrc` + `sine` |
| AC-M1-02 | Fragmented MP4 with audio | same | Same as AC-M1-01 | `-movflags frag_keyframe+empty_moov` |
| AC-M1-03 | MP4 whose audio is silent | same | Exit 0; passes WAV format check. Silence is not an error. | `anullsrc` |
| AC-M1-04 | MP4 with 2 audio tracks: track 0 = `sine`, track 1 = `anullsrc` | same | Exit 0; output is from track 0: `volumedetect` `max_volume` > −20 dB | two inputs, `-map` |
| AC-M1-05 | Same as AC-M1-04 but track order reversed (track 0 silent) | same | Exit 0; output is from track 0: `max_volume` ≤ −80 dB. This shows the first track is selected explicitly (`-map 0:a:0`), not the "best" stream. | two inputs, reversed `-map` |
| AC-M1-06 | MP4 with no audio stream | same | Clear error, with an exit code specific to "no audio" (Q4); stderr matches `/no audio stream/i`; no conversion attempt is made (probe step only) | `testsrc` only; optionally assert the ffmpeg runner was not called for conversion |
| AC-M1-07 | Valid MP4 where the **first** conversion attempt fails (runner mocked to return nonzero once) | extract | A second attempt is made whose ffmpeg arguments include `-fflags +discardcorrupt+genpts`, `-err_detect ignore_err`, and `-analyzeduration` / `-probesize` values larger than the first attempt's (PLAN.md step 3). A warning matching `/retry/i` is printed on stderr. Exit 0 if the retry succeeds. | Unit test with mocked subprocess runner |
| AC-M1-08 | Valid MP4 where **both** attempts fail (mocked) | extract | Clear error; stderr includes the path of the saved log file; exactly 2 attempts, no more | Mocked runner |
| AC-M1-09 | MP4 with random bytes overwritten mid-file (in the media data, not the header) | extract | Exit 0; passes WAV format check; duration ≥ 50% of the source. This holds whether it succeeds on attempt 1 or 2. | Copy of AC-M1-01 fixture, overwrite ~4 KB at 50% offset |
| AC-M1-10 | Truncated MP4 (first half of the file only, which gives "moov atom not found") | extract | Clear error; log file exists at the path printed in the message; log contains `moov atom not found` | Truncate AC-M1-01 fixture |
| AC-M1-11 | Zero-byte `empty.mp4` | extract | Clear error; log file exists | `touch` |
| AC-M1-12 | Text file renamed to `notes.mp4` | extract | Clear error; log file exists | write text, rename |
| AC-M1-13 | Any failure that produces a log (AC-M1-08, -10, -11, -12) | inspect the log | The log contains, for each attempt made (ffprobe and ffmpeg), the full command line and that attempt's complete stderr, in order | Parse log from the above cases |
| AC-M1-14 | An ffmpeg that writes ≥ 5 MB to stderr and then exits 0 | extract | Finishes within 30 s with exit 0. There is no deadlock on a full pipe (PLAN.md step 5). | Fake `ffmpeg` script put first on `PATH` (fast). Optional `@pytest.mark.slow`: 2 h audio-only lavfi file. |
| AC-M1-15 | Input path does not exist | `transcribe missing.mp4 --extract-only` | Exit 2; stderr matches `/not found/i`; ffprobe/ffmpeg are not invoked | tmp_path |
| AC-M1-16 | Valid MP4, no `-o` | `transcribe dir/in.mp4 --extract-only` | Exit 0; `dir/in.wav` created (Q2); on success stdout prints the WAV path | AC-M1-01 fixture |
| AC-M1-17 | `ffprobe` or `ffmpeg` not on `PATH` | extract | Clear error; stderr matches `/ffmpeg|ffprobe/` and `/not found|install/i` (Q7) | Run with an empty `PATH` |
| AC-M1-18 | A 5 s input in each format typical of meeting apps and recorders: **MP4** H.264+AAC (Teams, Meet, Zoom), **M4A** AAC (Zoom audio-only), **MKV** H.264+AAC (OBS), **WebM** VP8/VP9+Opus (browser recorders), **MOV** H.264+AAC (QuickTime), **MP3** (voice memos), **WAV** 44.1 kHz stereo (already audio, needs resample and downmix) | `transcribe in.<ext> --extract-only -o out.wav` | For every format: exit 0; passes WAV format check; duration = source ±0.5 s | One parametrized test; fixtures generated with lavfi `testsrc` + `sine`. If an encoder is missing from the local ffmpeg build, skip that case with a clear reason (never fail silently) |
| AC-M1-19 | Valid 10 s input | `extract_audio(..., on_progress=cb)` | `cb` is called at least twice; values are in [0.0, 1.0] and never decrease; the last value is exactly 1.0 on success. On failure the last value is < 1.0 and it is never called with 1.0 | Unit: fake runner that emits ffmpeg `-progress` lines (`out_time_us=…`, `progress=end`). Integration: real ffmpeg on the fixture |
| AC-M1-20 | Valid input; stderr **is** a terminal | CLI `--extract-only` | stderr shows a single self-updating line matching `/Extracting audio.*\d+%/` that ends at `100%` | Run the CLI under a pseudo-terminal (`pty`) |
| AC-M1-21 | Valid input; stderr is **not** a terminal (pipe, CI, file) | CLI `--extract-only` | No progress output on stderr, so logs and the "one message" rule for errors stay clean | Normal `subprocess` capture, same as other CLI tests |
| AC-M1-22 | Any valid input | extract | Every ffmpeg conversion attempt (normal and retry) includes `-rf64 auto`, so output over 4 GB (~37 h) does not break. Small outputs still pass the WAV format check | Unit: inspect args passed to fake runner. Integration: AC-M1-01 output still passes format check |
| AC-M1-23 | Conversion fails because the disk is full (runner mocked: exits nonzero, stderr contains `No space left on device`) | extract | Clear error with exit code 4; stderr matches `/disk|space/i`; **no** tolerant retry is attempted; no WAV (or temp file) left behind; log saved if its directory is still writable, and the error is still shown if it is not | Unit with mocked runner; check call count = 1 |
| AC-M1-24 | `meeting_transcriber.audio.extract_audio` raises an unexpected exception (e.g. `RuntimeError("boom")`) | CLI `--extract-only` on a valid input | Exit 1; stderr has one line matching `/^Error: unexpected error: RuntimeError: boom/` that names the input file, plus a hint mentioning `MEETING_TRANSCRIBER_DEBUG`; no `Traceback` in stderr; no WAV or temp file left. With `MEETING_TRANSCRIBER_DEBUG=1`: exit 1 and stderr contains `Traceback` (Q13) | Subprocess running a tiny script that patches `meeting_transcriber.audio.extract_audio` **before** importing the CLI, then runs `runpy.run_module("meeting_transcriber", run_name="__main__")` |

## Edge cases & error handling
- **ffprobe cannot read the container** (truncated, zero-byte, not media). ffprobe fails before audio selection is possible. The proposed behavior is in Q5. Either way, the result must be the "clear error + log" path, never a traceback.
- **Retry is bounded.** There is exactly one tolerant retry (PLAN.md step 3). There are no loops.
- **Partial output.** A failed or interrupted run must not leave a WAV at the output path that looks valid (Q6).
- **Stderr** from ffprobe and ffmpeg is always consumed, whether it is streamed to a file or read concurrently, on success and on failure (PLAN.md step 5).
- **Non-ASCII and space-containing paths** must work. Arguments are passed as a list, not a shell string. Covered by running AC-M1-01 with the file named `my meeting ü.mp4`.
- **Silent audio** is valid output. Detecting "no speech" is not M1's job.
- **Unknown duration.** If ffprobe reports no duration (some fragmented or damaged files), progress cannot be computed as a percentage: the terminal line shows elapsed audio time instead (e.g. `Extracting audio… 00:12:34`), and `on_progress` is called only with the final 1.0.
- **Progress is cosmetic.** A problem parsing progress output must never fail the extraction.
- **Recording length.** Supported up to 8 h, tested up to 2 h (AC-M1-14 slow test). WAV output is ≈115 MB/hour; `-rf64 auto` (AC-M1-22) removes the 4 GB / ~37 h WAV cap.
- **Disk full** is not a damaged-input problem, so it never triggers the tolerant retry (AC-M1-23).

## Out of scope
- Transcription, diarization, export formats, and the `--speakers` / `--format` flags (M2–M3).
- Pinning the ffmpeg version via Docker (M4). The PyAV / imageio-ffmpeg alternatives are "consider" only in PLAN.md and are not implemented in M1.
- Choosing an audio track other than the first, mixing multiple tracks, and channel selection (Q3).
- Downloading media from URLs or online video platforms. This is not planned (see the comment in PLAN.md "Scope"); users pass local files only.
- Proprietary formats ffmpeg cannot read (e.g. legacy Webex ARF/WRF). These must be converted with the vendor's tool first; the tech-writer documents this in troubleshooting.
- Timing and benchmarks (M4).
- Collecting real failing recordings. Real recordings are never committed (CLAUDE.md).

## Decisions (formerly open questions)
All proposed defaults below were accepted by the user on 2026-09-28.

| # | Question | Decision |
|---|---|---|
| Q1 | What CLI form runs extraction alone in M1, before ASR exists? PLAN.md only defines `transcribe meeting.mp4 --speakers --format …`. | `transcribe INPUT --extract-only [-o/--output PATH]`. In M1, running without `--extract-only` exits 2 with "transcription not implemented yet". |
| Q2 | Where does the WAV go by default, and are existing files overwritten? | `<input dir>/<input stem>.wav`. `-o` overrides. An existing file is overwritten. |
| Q3 | Should the user be able to pick a different audio track (e.g. `--audio-track N`)? PLAN.md only says "select track explicitly (`-map 0:a:0`)". | No. Always use the first audio track in M1, and log how many audio tracks were found when there is more than one. |
| Q4 | Exit codes? | 0 success; 2 usage error / input not found (argparse convention); 3 no audio stream; 4 file unreadable or extraction failed after retry; 5 ffmpeg/ffprobe missing. |
| Q5 | If `ffprobe` itself fails to parse the file, fail immediately, or also retry the probe with larger `-analyzeduration` / `-probesize`? | Retry the probe once with the larger values. If that also fails, give a clear error ("cannot read media file") and save the log. The conversion is skipped. |
| Q6 | Where is the ffmpeg log saved and under what name? Is it kept on success? What happens to partial output on failure? | Log path is `<output dir>/<input stem>.ffmpeg.log`. It is written only on failure and deleted after a successful run. Conversion writes to a temp file that is renamed on success, so no partial WAV is left. |
| Q7 | Should a missing ffmpeg/ffprobe binary get its own clear error (AC-M1-17)? PLAN.md is silent on this. | Yes, with exit code 5 and an install hint. |
| Q8 | Should the retry trigger on nonzero exit only, or also when the output is empty or much shorter than the probed duration? | Nonzero exit, or output with 0 audio samples. There is no duration-ratio heuristic in M1. |
| Q9 | PLAN.md requires 3–5 real failing files and their `ffprobe` output in `docs/troubleshooting-ffmpeg.md` before implementation. None exist. Do we block on this? | Don't block. The synthetic broken files stand in for them. The tech-writer creates `docs/troubleshooting-ffmpeg.md` with the `ffprobe` output of the synthetic broken fixtures, and real cases are appended later without committing the media. |
| Q10 | Should extraction also be exposed as a public Python API (e.g. `extract_audio(src, dst) -> Path`) for tests and M2? | Yes. Put it in `meeting_transcriber.audio` and have the CLI call it. Tests may target either one. |
| Q11 | What if the default output path is the input itself (`transcribe x.wav --extract-only` without `-o`)? | Refuse with exit 2 instead of overwriting the source. *(Added during implementation.)* |
| Q12 | What if the output directory is missing or cannot be written? | A missing directory is created. An unwritable one gives exit 4; full disk / quota gives the disk-full error (AC-M1-23). *(Added during implementation.)* |
| Q13 | Ctrl-C and unexpected errors? | Ctrl-C: exit 130, one-line message, temp files cleaned up. Unexpected errors: exit 1 with a one-line message; the full traceback only with `MEETING_TRANSCRIBER_DEBUG=1`. *(Added during implementation.)* |
| Q14 | Is a log saved when the file has no audio stream (AC-M1-06)? | No. This is a clean detection, not a failed ffmpeg/ffprobe run. The number of audio tracks goes to the log on failure and to `logging.info`, never to the terminal on success. *(Added during implementation.)* |
