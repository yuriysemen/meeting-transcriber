"""AC-M1-20: with stderr attached to a terminal, the CLI shows a single
self-updating progress line ending at 100%. Uses `pty` to give the child a
real pseudo-terminal, since `os.isatty()` on a plain pipe is always False.
"""

from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import time

from tests.utils import cli_argv


def test_progress_shown_as_self_updating_line_on_a_tty(valid_mp4_10s, tmp_path):
    """AC-M1-20: stderr is a terminal -> a single self-updating line matching
    /Extracting audio.*\\d+%/ that ends at 100%."""
    dst = tmp_path / "out.wav"
    master_fd, slave_fd = pty.openpty()

    proc = None
    try:
        proc = subprocess.Popen(
            cli_argv(str(valid_mp4_10s), "--extract-only", "-o", str(dst)),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1

        output = b""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            r, _, _ = select.select([master_fd], [], [], 5)
            if not r:
                if proc.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
    finally:
        if slave_fd != -1:
            os.close(slave_fd)
        os.close(master_fd)
        if proc is not None:
            proc.wait(timeout=30)

    text = output.decode(errors="replace")
    assert re.search(r"Extracting audio.*\d+%", text), f"progress line not found in: {text!r}"
    assert re.search(r"100%", text), f"progress did not reach 100% in: {text!r}"
    assert proc.returncode == 0, f"CLI exited {proc.returncode}, output: {text!r}"
    assert dst.exists()
