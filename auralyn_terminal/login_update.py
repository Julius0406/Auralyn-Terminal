"""Per-user XDG desktop autostart for the existing fixed update workflow."""
from __future__ import annotations
import configparser
import os
from pathlib import Path
import tempfile

NAME = "de.julius.AuralynTerminal.LoginUpdate.desktop"
EXEC = "/usr/bin/auralyn-terminal --login-update"
ENTRY = """[Desktop Entry]
Type=Application
Name=Auralyn Terminal - Login Update
Name[de]=Auralyn Terminal - Systemupdate beim Login
Comment=Open Auralyn and run APT and Flatpak updates
Exec=/usr/bin/auralyn-terminal --login-update
TryExec=/usr/bin/auralyn-terminal
Icon=auralyn-terminal
Terminal=false
StartupNotify=true
X-GNOME-Autostart-enabled=true
X-Auralyn-Managed=true
"""


def entry_path(config_home=None):
    if config_home is None:
        configured = os.environ.get("XDG_CONFIG_HOME", "")
        config_home = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".config"
    return Path(config_home) / "autostart" / NAME


def _read(path):
    if path.is_symlink():
        raise OSError("Autostart-Datei ist ein symbolischer Link.")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except FileNotFoundError:
        return None
    except (configparser.Error, UnicodeError) as exc:
        raise OSError("Autostart-Datei ist ungültig.") from exc
    if not parser.has_section("Desktop Entry"):
        raise OSError("Autostart-Datei ist ungültig.")
    entry = parser["Desktop Entry"]
    if entry.get("X-Auralyn-Managed") != "true" or entry.get("Exec") != EXEC:
        raise OSError("Autostart-Datei gehört nicht zu Auralyn.")
    return entry


def enabled(config_home=None):
    try:
        entry = _read(entry_path(config_home))
        return (entry is not None and entry.get("Hidden", "false").lower() != "true"
                and entry.get("X-GNOME-Autostart-enabled", "true").lower() == "true")
    except OSError:
        return False


def set_enabled(active, config_home=None):
    """Only manage the dedicated entry. No privileged writes or commands."""
    path = entry_path(config_home)
    current = _read(path)
    if not active:
        if current is not None:
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".auralyn-autostart-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(ENTRY)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
