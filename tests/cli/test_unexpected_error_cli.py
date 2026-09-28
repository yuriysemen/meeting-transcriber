"""AC-M1-24: an unexpected exception raised by
`meeting_transcriber.audio.extract_audio` must not surface as a traceback on
stderr by default -- exit 1, one clear line naming the input file, plus a
hint mentioning `MEETING_TRANSCRIBER_DEBUG`, no WAV or temp file left. With
`MEETING_TRANSCRIBER_DEBUG=1` the full traceback is shown instead (Q13).

Per the spec's own "Test idea" for this row, this runs a tiny subprocess
script that patches `meeting_transcriber.audio.extract_audio` *before*
importing the CLI, then calls
`runpy.run_module("meeting_transcriber", run_name="__main__")`. This is the
only spec-given way to make the CLI observe a patched `extract_audio`
without reading src/ to find out how/where it is imported.

The CLI argv shape used here (`INPUT --extract-only -o OUTPUT`) matches the
one already exercised by every other CLI test via `tests.utils.cli_argv`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_PATCH_AND_RUN_SCRIPT = '''\
import runpy
import sys

import meeting_transcriber.audio as audio


def _boom(*_args, **_kwargs):
    raise RuntimeError("boom")


audio.extract_audio = _boom

sys.argv = ["meeting_transcriber", sys.argv[1], "--extract-only", "-o", sys.argv[2]]
runpy.run_module("meeting_transcriber", run_name="__main__")
'''


def _write_patch_script(tmp_path: Path) -> Path:
    script_path = tmp_path / "patch_extract_audio_and_run_cli.py"
    script_path.write_text(_PATCH_AND_RUN_SCRIPT, encoding="utf-8")
    return script_path


def _run_patched_cli(
    script_path: Path, src: Path, dst: Path, env: dict, timeout: float = 30
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script_path), str(src), str(dst)],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def test_unexpected_error_default_mode_no_traceback(tmp_path):
    """AC-M1-24 (default mode): exit 1; stderr has one line matching
    /^Error: unexpected error: RuntimeError: boom/ that also names the
    input file; a hint mentions MEETING_TRANSCRIBER_DEBUG; no "Traceback"
    anywhere in stderr; no WAV or temp file left at/around the output
    path."""
    script_path = _write_patch_script(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"placeholder - never actually read, extract_audio is mocked")
    dst = tmp_path / "out.wav"
    env = dict(os.environ)
    env.pop("MEETING_TRANSCRIBER_DEBUG", None)

    result = _run_patched_cli(script_path, src, dst, env)

    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert re.search(
        r"^Error: unexpected error: RuntimeError: boom", result.stderr, re.MULTILINE
    ), f"stderr={result.stderr!r}"
    assert str(src) in result.stderr, (
        f"expected the input path to be named in stderr: {result.stderr!r}"
    )
    assert "MEETING_TRANSCRIBER_DEBUG" in result.stderr, f"stderr={result.stderr!r}"
    assert "Traceback" not in result.stderr, f"stderr={result.stderr!r}"
    assert not dst.exists()
    leftover = [p for p in tmp_path.iterdir() if p not in (src, script_path)]
    assert leftover == [], f"unexpected leftover file(s) in output dir: {leftover!r}"


def test_unexpected_error_debug_mode_shows_traceback(tmp_path):
    """AC-M1-24 (MEETING_TRANSCRIBER_DEBUG=1, Q13): exit 1; stderr contains
    a Python traceback."""
    script_path = _write_patch_script(tmp_path)
    src = tmp_path / "in.mp4"
    src.write_bytes(b"placeholder - never actually read, extract_audio is mocked")
    dst = tmp_path / "out.wav"
    env = dict(os.environ)
    env["MEETING_TRANSCRIBER_DEBUG"] = "1"

    result = _run_patched_cli(script_path, src, dst, env)

    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "Traceback" in result.stderr, f"stderr={result.stderr!r}"
    assert not dst.exists()
