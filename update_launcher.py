#!/usr/bin/python3
"""Private entry point for a dedicated update tab; no command string accepted."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auralyn_terminal.update_session import main
raise SystemExit(main())
