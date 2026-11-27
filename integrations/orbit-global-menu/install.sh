#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$HERE/auralyn-terminal.json"
if [[ ! -f "$SOURCE" ]]; then
    SOURCE="/usr/share/auralyn-terminal/integrations/orbit-global-menu/auralyn-terminal.json"
fi
if [[ ! -f "$SOURCE" ]]; then
    echo "Auralyn Orbit-Menüdatei wurde nicht gefunden." >&2
    exit 1
fi
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DEST_DIR="$CONFIG_HOME/global-menu/shortcuts/apps"
DEST="$DEST_DIR/auralyn-terminal.json"
mkdir -p "$DEST_DIR"
if [[ -f "$DEST" ]] && cmp -s "$SOURCE" "$DEST"; then
    echo "Orbit-Menü für Auralyn ist bereits aktuell."
else
    if [[ -e "$DEST" ]]; then
        BACKUP="$DEST.backup.$(date +%Y%m%d-%H%M%S)"
        cp -a "$DEST" "$BACKUP"
        echo "Vorhandenes eigenes Orbit-Menü gesichert: $BACKUP"
    fi
    install -m 0644 "$SOURCE" "$DEST"
    echo "Auralyn-Menü installiert: $DEST"
fi
UUID="global-menu@unmade.space"
if command -v gnome-extensions >/dev/null 2>&1 && gnome-extensions list --enabled 2>/dev/null | grep -Fxq "$UUID"; then
    gnome-extensions disable "$UUID"
    gnome-extensions enable "$UUID"
    echo "Orbit Global Menu wurde neu geladen."
elif command -v gnome-extensions >/dev/null 2>&1 && gnome-extensions list 2>/dev/null | grep -Fxq "$UUID"; then
    echo "Orbit Global Menu ist installiert, aber nicht aktiviert. Aktiviere es in Erweiterungen."
else
    echo "Orbit Global Menu ist nicht installiert. Das Menü ist vorbereitet und erscheint nach Installation der Erweiterung."
fi
