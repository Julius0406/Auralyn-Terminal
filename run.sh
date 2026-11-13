#!/bin/sh
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec /usr/bin/python3 -I "$HERE/launcher.py" "$@"
