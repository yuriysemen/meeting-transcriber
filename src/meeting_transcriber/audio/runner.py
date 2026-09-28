"""Runs one ffprobe/ffmpeg command without ever blocking on a full pipe."""

from __future__ import annotations

import shlex
import subprocess
import threading
from typing import Callable, TextIO

Runner = Callable[[list[str], TextIO, Callable[[str], None] | None], int]
"""(args, log, on_stdout_line) -> exit code.

Writes the full command line and all of the command's stderr to ``log``.
Calls ``on_stdout_line`` for each stdout line (without the newline) if given.
Raises ``FileNotFoundError`` if the executable does not exist.
"""


def default_runner(
    args: list[str],
    log: TextIO,
    on_stdout_line: Callable[[str], None] | None = None,
) -> int:
    """Real subprocess runner. stderr is drained on a separate thread (no deadlock)."""
    log.write(f"$ {shlex.join(args)}\n")
    proc = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None and proc.stderr is not None

    def drain_stderr() -> None:
        for line in proc.stderr:
            log.write(line)

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    try:
        for line in proc.stdout:
            if on_stdout_line is not None:
                on_stdout_line(line.rstrip("\r\n"))
        return proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        stderr_thread.join()
        proc.stdout.close()
        proc.stderr.close()
        log.write(f"[exit code {proc.returncode}]\n")
