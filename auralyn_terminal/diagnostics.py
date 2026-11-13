"""Small private, metadata-only diagnostics for Smart Search failures.

No question, model output, web page, URL, credential, terminal output, local
variables, full filesystem paths or exception message is recorded. The caller
can show trusted AIError messages separately. Reports are never sent anywhere.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import re
import stat
import threading
import traceback
import uuid

from . import __version__

_LIMIT = 256 * 1024
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Diagnostic:
    code: str
    summary: str
    text: str
    saved: bool


def _identifier(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.<>:-]', '_', value)[:110]


def _stage(value: str) -> str:
    # Progress strings may include a proposed tool name; record only this finite
    # set of stages, never the incoming free text.
    if value.startswith('Aufgabe verstehen') or value.startswith('Lokale KI'):
        return 'Lokales Modell / Aufgabe verstehen'
    if value.startswith('1/2'):
        return '1/2 Web / Dokumentation abrufen'
    if value.startswith('2/2'):
        return '2/2 Lokal / Verfügbarkeit oder Installation prüfen'
    if value.startswith('Web + Lokal'):
        return 'Antwort aus Web- und lokalen Daten formulieren'
    if value.startswith('Offline'):
        return 'Offline-Hilfe'
    return 'Smart Search'


def diagnostic_path() -> Path:
    state = os.environ.get('XDG_STATE_HOME', '')
    base = Path(state) if state and Path(state).is_absolute() else Path.home() / '.local' / 'state'
    return base / 'auralyn-terminal' / 'smart-search.log'


def _append(text: str) -> bool:
    """At most 256 KiB; no symlink following, and no world-readable log."""
    try:
        path = diagnostic_path()
        with _LOCK:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Do not use a symlinked application state directory.
            if path.parent.is_symlink():
                return False
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
            fd = os.open(path, flags, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    return False
                os.fchmod(fd, 0o600)
                data = ('\n' + text + '\n').encode('utf-8')[:18000]
                if info.st_size + len(data) > _LIMIT:
                    os.ftruncate(fd, 0)
                view = memoryview(data)
                while view:
                    sent = os.write(fd, view)
                    if sent <= 0:
                        return False
                    view = view[sent:]
                return True
            finally:
                os.close(fd)
    except (OSError, ValueError, RuntimeError):
        return False


def record_failure(exc: Exception, *, stage: str = 'Smart Search', web: bool = False) -> Diagnostic:
    code = 'AT-' + uuid.uuid4().hex[:10].upper()
    kind = _identifier(type(exc).__name__)
    lines = [f'Auralyn Terminal {__version__}', f'Fehler-ID: {code}',
             'Zeit (UTC): ' + datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'Python: ' + platform.python_version(),
             'Webmodus: ' + ('an' if web else 'aus'), 'Schritt: ' + _stage(stage),
             'Fehlerart: ' + kind]
    summary = kind
    seen = set()
    current = exc
    for depth in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if depth:
            lines.append('Verursacht durch: ' + _identifier(type(current).__name__))
        # Do not format exception messages, source lines or captured locals.
        frames = traceback.extract_tb(current.__traceback__)[-12:]
        for frame in frames:
            filename = _identifier(Path(frame.filename).name)
            lines.append(f'  {filename}:{frame.lineno} in {_identifier(frame.name)}')
        if depth == 0 and frames:
            summary += ' in ' + _identifier(Path(frames[-1].filename).name) + ':' + str(frames[-1].lineno)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    lines.append('Enthält keine Suchfrage, KI-Texte, Schlüssel, Webseiten oder Terminalausgaben.')
    text = '\n'.join(lines)
    saved = _append(text)
    text += '\n' + ('Technischer Bericht lokal gespeichert; nicht hochgeladen.' if saved
                     else 'Lokales Protokoll nicht schreibbar; dieser Bericht kann trotzdem kopiert werden.')
    return Diagnostic(code, summary, text, saved)
