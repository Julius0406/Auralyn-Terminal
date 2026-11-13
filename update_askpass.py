#!/usr/bin/python3 -I
"""Private sudo askpass entry point; does not read the keyring itself."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from auralyn_terminal.update_auth import askpass_main
raise SystemExit(askpass_main())
