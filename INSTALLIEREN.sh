#!/bin/bash
# Build locally if necessary, then let APT resolve official Ubuntu dependencies.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE="$HERE/dist/auralyn-terminal_1.0.0_all.deb"
if [[ ! -f "$PACKAGE" ]]; then
    /usr/bin/python3 "$HERE/packaging/build_deb.py"
fi
printf '\nAuralyn Terminal v1.0.0 Stable installieren\n'
printf 'Dein vorhandenes Terminal und deine .bashrc werden nicht ersetzt.\n\n'
if (( EUID == 0 )); then
    apt install "$PACKAGE"
else
    sudo apt install "$PACKAGE"
fi
printf '\nInstallation abgeschlossen. Starte Auralyn Terminal über das App-Menü.\n'
printf 'Oder als normaler Benutzer: auralyn-terminal\n'
