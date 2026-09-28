# Project Plan

## Goal
A small, finished, portfolio-quality tool that turns meeting recordings (e.g. Teams MP4)
into speaker-labeled transcripts. Private by default: runs fully offline.

## Decisions
- **Language:** Python (faster-whisper, pyannote, PyAV ecosystem).
- **Model location:** configurable provider, `local` by default.
  - `local` — faster-whisper on CPU/GPU
  - `remote-selfhosted` — OpenAI-compatible transcription endpoint on a separate VM
    (e.g. faster-whisper-server/Speaches, whisper.cpp server)
  - `cloud` — hosted API (OpenAI, Groq, Deepgram, AssemblyAI) via API key
- **Diarization:** pyannote (gated model, free Hugging Face token) or disabled.
  Speakers assigned by overlapping word timestamps with speaker segments.

## Scope
### In scope (MVP)
- CLI: `transcribe meeting.mp4 --speakers --format srt,md,json`
- Pipeline: probe → extract audio → transcribe → diarize → merge → export
- Outputs: TXT, SRT/VTT, Markdown, JSON
- Inputs: any local video or audio recording file ffmpeg can read — MP4, M4A, MKV, WebM, MOV,
  MP3, WAV — from any meeting app or recorder (Teams, Zoom, Google Meet, Webex, OBS, QuickTime,
  browser recorders, voice memos). No integration with the apps themselves.
- Progress indicator for long files (terminal only)
- Recording length: supported up to **8 hours**, tested up to 2 hours (see "Recording length & limits")
- Optional Gradio web UI (for demo GIF)
- Docker image (CPU + GPU), tests on tiny self-recorded clips, GitHub Actions CI

<!-- Possible future idea, NOT planned: `--url` input via yt-dlp (YouTube, Vimeo, …).
     Left out on purpose: YouTube ToS restricts downloading, it conflicts with the
     "private on-prem" pitch, and yt-dlp breaks often. If ever added: optional extra
     (`pip install meeting-transcriber[url]`), not in the Docker image, generic "URL input"
     naming, rights disclaimer, demo only on own / CC-licensed content, no network calls in CI. -->

### Out of scope
Summaries, LLM Q&A, accounts, databases, real-time transcription in the MVP
(planned separately as Milestone 5), Teams meeting bots (Graph API / .NET media bots),
downloading media from URLs or online video platforms, proprietary formats ffmpeg cannot
read (e.g. legacy Webex ARF/WRF — convert with the vendor's tool first).

## Audio extraction (FFmpeg robustness)
Target format: mono, 16 kHz, 16-bit PCM WAV (`-vn -ac 1 -ar 16000 -c:a pcm_s16le`).

1. `ffprobe` first: reject files with no audio stream; select track explicitly (`-map 0:a:0`).
2. Normal conversion.
3. On failure, retry with `-fflags +discardcorrupt+genpts -err_detect ignore_err`
   and larger `-analyzeduration` / `-probesize`.
4. On failure again, clear error message + saved ffmpeg stderr log.
5. Always consume/redirect stderr (unread pipes hang on long files).
6. Pin ffmpeg version via Docker. Consider PyAV / imageio-ffmpeg as alternatives.
7. Write with `-rf64 auto` so WAV output over 4 GB (~37 h) does not break.
8. Out of disk space → clear error (no tolerant retry), no partial WAV left behind.

Before implementing: collect 3–5 failing files and record their `ffprobe` output
in `docs/troubleshooting-ffmpeg.md`.

## Recording length & limits
Target: up to 8 h per recording; tested up to 2 h (slow test), benchmarked at 1 h and 4 h (M4).

| Stage | Limit | Handling |
|---|---|---|
| Extraction (M1) | WAV ≈ 115 MB/hour; classic WAV caps at 4 GB ≈ 37 h | `-rf64 auto`; clear out-of-disk error |
| Local ASR (M2) | faster-whisper works in 30 s windows, memory ~constant | No length limit; only time grows |
| Remote / cloud ASR (M2) | Upload size limits (e.g. OpenAI 25 MB ≈ 13 min of WAV); server timeouts | Compress (Opus/MP3) and/or chunk; stitch timestamps across chunk boundaries. Check each provider's current limits when writing the M2 spec |
| Diarization (M3) | pyannote RAM/time grow with length | Measure in M4; document in README "Limits" |

## Test strategy
Test media is generated programmatically — no real recordings in the repo.
Required tools: ffmpeg (already a dependency), pytest; optionally espeak-ng or Piper for speech.

### Synthetic media (ffmpeg `lavfi` sources)
| Case | Source |
|---|---|
| Valid MP4 (H.264 + AAC, Teams-like) | `testsrc` video + `sine` audio |
| No audio stream | `testsrc` only |
| Multiple audio tracks | two `sine` inputs mapped with `-map` |
| Silent audio | `anullsrc` |
| Fragmented MP4 | `-movflags frag_keyframe+empty_moov` |
| Input format matrix: M4A (AAC), MKV, WebM (Opus), MOV, MP3, WAV 44.1 kHz stereo | `testsrc` + `sine`, one fixture per format |

### Broken files (reproduce extraction failures)
- Truncated MP4 (cut in half → "moov atom not found")
- Random bytes overwritten mid-file (corrupted packets)
- Zero-byte file; text file renamed to `.mp4`

Each case maps to a step of the probe → convert → retry → clear-error pipeline.

### Speech for ASR / diarization
- Offline TTS only: espeak-ng (CI-friendly) or Piper (natural voices);
  macOS `say` for local use only. No online TTS (flaky tests).
- Diarization fixture: two sentences in two different voices, concatenated and
  muxed with a test-pattern video → known ground truth (2 speakers, known change point, known words).

### Organization
- Session-scoped pytest fixtures (`tmp_path_factory`) generate media on the fly; generated files are not committed.
- Commit only 1–2 tiny speech clips (few seconds) in `tests/fixtures/` so CI does not depend on TTS.
- **Fast tests (every push):** extraction and error handling on synthetic files; unit tests with a mocked ASR provider.
- **Slow tests (`@pytest.mark.slow`):** real Whisper `tiny` model; assert expected keywords appear, not exact text.
- No network calls in tests.

## Planned repo structure
```
src/<pkg>/        cli, config, audio/, asr/providers/, diarization/, export/
tests/            + tests/fixtures/ (tiny self-recorded clips)
docker/           Dockerfile.cpu, Dockerfile.gpu
docs/             architecture diagram, troubleshooting-ffmpeg.md,
                  specs/, reports/, assets/, promo/
examples/         sample outputs
config.example.yaml
.github/workflows/ci.yml
```

## Milestones
1. Robust audio extraction (video + audio inputs, progress) + tests with previously failing files
   — spec: `docs/specs/M1-audio-extraction.md`
2. Provider interface + local faster-whisper provider; chunking/compression for remote and cloud
   providers with correct timestamps across chunk boundaries
3. Diarization + export formats
4. Docker, CI, README, benchmarks, demo GIF → publish + LinkedIn post
   - Benchmarks: 1 h and 4 h recordings — processing time and peak RAM per model size, CPU vs GPU
     → README "Benchmarks" and "Limits" tables
   - Presentation deliverables (see "Presentation"): `docs/promo/*`, social preview image, demo GIF
5. (v2) Live mode, hybrid — see "Live mode (v2)" below

## Live mode (v2)
Whisper is not natively streaming (≤30 s windows). Live transcription re-transcribes a
rolling buffer every 1–2 s and commits words once consecutive passes agree
(LocalAgreement). Expected latency: ~2–4 s; the tail of the text may change until committed.

### Approach: hybrid
- **Live:** draft text from microphone + system audio via faster-whisper streaming, no speaker labels.
- **After the meeting:** save the recording and run the existing batch pipeline
  (with diarization) to produce the final, accurate transcript.

### Components
- Audio capture: virtual loopback device (BlackHole on macOS, WASAPI loopback on Windows)
  + microphone. Works with any meeting app; no Teams integration.
- Streaming engine options: whisper_streaming (ÚFAL), WhisperLive (Collabora),
  whisper.cpp `stream`, Speaches (OpenAI-compatible, fits `remote-selfhosted`).
- Cloud streaming via the `cloud` provider: Deepgram, AssemblyAI, OpenAI Realtime.
- Live diarization (optional, later): diart — lower accuracy than batch pyannote.

### Constraints
- GPU strongly recommended; on CPU only `tiny`/`base`/`small` models are real-time.
- Reuse MVP components (config, providers, export); live mode must not change batch behavior.
- Tests: feed a pre-generated speech file as a simulated live stream; no real audio devices in CI.

## Rules
- Never commit real meeting recordings or transcripts.
- Demo only with own recordings or Creative Commons / public-domain content.
- README must state: process only content you own or have rights to, with participants' consent.

## Presentation
One source of truth, several outputs. README is the full reference; every other channel is a
shorter derivative using the same facts and the same benchmark numbers. Owner: `tech-writer` agent.
The user pastes the texts into GitHub settings / LinkedIn / Upwork and records the demo GIF.

```
README.md              full documentation
docs/assets/           demo.gif, screenshots, social-preview.png (1280×640)
docs/promo/
  github-about.md      About description (one line) + topics
  linkedin.md          Featured item text, Projects entry, story post
  upwork.md            portfolio item: title, Problem / Solution / Result, skills
```

| Channel | Audience | Content |
|---|---|---|
| **GitHub About** | 5-second skim | One-line description, topics (`whisper`, `speech-to-text`, `diarization`, `ffmpeg`, `python`, `docker`, `privacy`, …), social preview image (also the LinkedIn/Slack link thumbnail) |
| **README** | Developers, technical clients | Sections listed in README.md outline |
| **LinkedIn** | Recruiters, network | Featured link to repo, Projects entry, one story post (problem → FFmpeg failures → fix → numbers → GIF) |
| **Upwork** | Clients, often non-technical | Outcome-focused title, Problem / Solution / Result in business terms (private on-prem transcription), 3–5 screenshots or GIF, skills, repo link |
| **CV** | Hiring managers | One line with measurable numbers (speed on CPU/GPU, input formats, backends) |

Rules:
- Timing: README sections are filled per milestone, only for features that exist. `docs/promo/*`,
  social preview and demo GIF are written in M4, after benchmarks.
- Every number or claim comes from benchmarks or tests, never estimates; same numbers in all channels.
- Demo media: own recordings or Creative Commons / public-domain content only.
