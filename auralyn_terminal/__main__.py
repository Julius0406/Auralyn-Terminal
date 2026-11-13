"""Entrypoint with actionable dependency diagnostics, also usable from source."""
import sys
from . import __version__

if "--version" in sys.argv[1:]:
    print(f"Auralyn Terminal {__version__}")
    raise SystemExit(0)

try:
    from .app import main
except (ImportError, ValueError) as exc:
    print("Auralyn Terminal: Eine System-Abhängigkeit fehlt.", file=sys.stderr)
    print(f"Details: {exc}", file=sys.stderr)
    print("Installiere sie im normalen Ubuntu-Terminal:", file=sys.stderr)
    print("sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 bash-completion", file=sys.stderr)
    raise SystemExit(1)

raise SystemExit(main())
