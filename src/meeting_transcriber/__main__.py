"""Allow running as ``python -m meeting_transcriber``."""

import sys

from meeting_transcriber.cli import main

if __name__ == "__main__":
    sys.exit(main())
