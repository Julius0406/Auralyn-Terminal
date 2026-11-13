#!/usr/bin/python3
"""Private installed Smart Search PTY entry point (action IDs, not shell code)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auralyn_terminal.smart_session import main
raise SystemExit(main())
