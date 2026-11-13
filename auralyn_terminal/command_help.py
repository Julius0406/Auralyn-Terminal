"""Offline help for selected suggestions, without executing those suggestions.

Known commands have a short German explanation. Other *command names* can be
looked up by the distro's /usr/bin/whatis. The selected tool is never invoked,
not even with --help; unknown arguments are not silently treated as commands.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import re
import selectors
import signal
import subprocess
import threading
import time
import unicodedata
from typing import Callable

from .completion import Candidate, Context
from .help_catalog import COMMAND_HELP, SUBCOMMAND_HELP, OPTION_HELP

MAX_TEXT = 260
MAX_OUTPUT = 32768
MAN_TOPIC = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.+:-]{0,119}$')


def clean_text(text: str, limit: int = MAX_TEXT) -> str:
    """Only plain text is used in GTK labels; strip control/bidi formatting."""
    text = ''.join(' ' if c.isspace() else c for c in text
                   if c.isspace() or not unicodedata.category(c).startswith('C'))
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:max(0, limit - 1)].rstrip() + '…'


@dataclass(frozen=True)
class HelpText:
    title: str
    text: str
    source: str = 'Auralyn-Kurzhilfe'


def parse_whatis(output: bytes, topic: str) -> str | None:
    """Accept descriptions only for an exact name in command sections 1 or 8."""
    if len(output) > MAX_OUTPUT or not MAN_TOPIC.fullmatch(topic):
        return None
    for line in output.decode('utf-8', errors='replace').splitlines():
        match = re.match(r'^(.+?)\s+\(([18][^)]*)\)\s+[-–—]\s+(.+)$', line)
        if not match:
            continue
        names = [word.strip() for word in match.group(1).split(',')]
        if topic not in names:
            continue
        description = clean_text(match.group(3))
        if description:
            return description
    return None


def describe(context: Context, candidate: Candidate, cwd: str,
             manual: Callable[[str], str | None]) -> HelpText:
    """Explain the actual selected word in its context. Never infer unknown APIs."""
    context = candidate.help_context or context
    value = candidate.value
    title = clean_text(candidate.display, 100)
    cmd = os.path.basename(context.command)

    if candidate.help_text:
        return HelpText(title, clean_text(candidate.help_text), 'Auralyn · lokal')

    if candidate.kind == 'Ordner':
        return HelpText(title, 'Ordner. Du kannst den Pfad weiter ergänzen oder ihn als Ziel verwenden.')
    if context.command_position:
        # ./sudo may be a completely different local script; do not describe it
        # using the bundled explanation of the system's sudo executable.
        if '/' in value or value.startswith('~'):
            return HelpText(title, 'Ausführbare Datei an diesem Pfad. Für eigene Skripte ist keine automatische Funktionsbeschreibung hinterlegt.', 'Dateipfad')
        if value in COMMAND_HELP:
            return HelpText(title, COMMAND_HELP[value])
        if candidate.kind == 'Shell':
            return HelpText(title, 'Befehl, Alias oder Funktion deiner Bash. Die eigene Definition legt fest, was ausgeführt wird; keine Kurzbeschreibung hinterlegt.', 'Shell-Eintrag')
        text = manual(value) if MAN_TOPIC.fullmatch(value) else None
        if text:
            return HelpText(title, clean_text(text), 'Lokales Handbuch · Originalsprache')
        return HelpText(title, 'Installierter Befehl. Keine lokale Kurzbeschreibung gefunden; Auralyn erfindet keine Erklärung.', 'Keine Beschreibung vorhanden')

    if candidate.kind == 'Datei':
        return HelpText(title, 'Datei. Wird als Dateipfad eingesetzt; der davorstehende Befehl bestimmt, was damit passiert.', 'Dateipfad')
    chain = (*context.words[1:-1], value)
    key = (cmd, *chain)
    command_title = clean_text(' '.join(key), 100)
    if key in SUBCOMMAND_HELP:
        return HelpText(command_title, SUBCOMMAND_HELP[key])
    if value.startswith('-'):
        text = OPTION_HELP.get((cmd, value.split('=', 1)[0]))
        if text:
            return HelpText(command_title, text)
        return HelpText(command_title, f'Option für {clean_text(cmd, 60)}. Für diese Option ist keine eigene Kurzbeschreibung hinterlegt.', 'Keine Beschreibung vorhanden')

    # Native Bash completion also returns files with the neutral "Bash" kind.
    # Do not inspect the file contents or execute a file to learn its purpose.
    disk = os.path.expanduser(value)
    if not os.path.isabs(disk):
        disk = os.path.join(cwd, disk)
    try:
        if os.path.isdir(disk):
            return HelpText(title, 'Ordner. Du kannst den Pfad weiter ergänzen oder ihn als Ziel verwenden.', 'Dateipfad')
        if os.path.lexists(disk):
            return HelpText(title, 'Dateipfad für den davorstehenden Befehl. Die Datei wird für diese Erklärung nicht geöffnet.', 'Dateipfad')
    except (OSError, ValueError):
        pass

    # Some CLIs install separate manuals such as git-status. Limit this to the
    # first subcommand: "cat sudo" must NOT display the description of sudo.
    if len(chain) == 1 and MAN_TOPIC.fullmatch(cmd) and MAN_TOPIC.fullmatch(value):
        topic = cmd + '-' + value
        text = manual(topic) if MAN_TOPIC.fullmatch(topic) else None
        if text:
            return HelpText(command_title, clean_text(text), 'Lokales Handbuch · Originalsprache')
    if len(chain) >= 2 and cmd in ('apt', 'apt-get', 'pip', 'pip3') and chain[0] in ('install', 'reinstall', 'remove', 'uninstall', 'purge', 'show'):
        return HelpText(title, f'Paketname oder Paketdatei für „{cmd} {clean_text(chain[0], 25)}“. Eine Beschreibung dieses Pakets ist hier nicht hinterlegt.', 'Paketargument')
    return HelpText(command_title, f'Vervollständigung für {clean_text(cmd, 60)}. Für diesen Unterbefehl oder Wert ist lokal keine Kurzbeschreibung vorhanden.', 'Keine Beschreibung vorhanden')


class HelpEngine:
    """One cancellable, time- and output-bounded whatis reader per help worker."""
    def __init__(self):
        self.cancelled = threading.Event()
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, str | None]] = {}

    def cancel(self):
        self.cancelled.set()
        with self._lock:
            self._kill(self._process)

    @staticmethod
    def _kill(process):
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def lookup_manual(self, topic: str) -> str | None:
        if self.cancelled.is_set() or not MAN_TOPIC.fullmatch(topic):
            return None
        now = time.monotonic()
        cached = self._cache.get(topic)
        if cached and now < cached[0]:
            return cached[1]
        # A fixed distro path avoids a fake `whatis` in a project's PATH. It is
        # optional: a missing database/helper merely yields the honest fallback.
        tool = '/usr/bin/whatis'
        if not os.access(tool, os.X_OK):
            return None
        output = bytearray()
        process = None
        valid = True
        try:
            with self._lock:
                if self.cancelled.is_set():
                    return None
                process = subprocess.Popen(
                    [tool, '--long', '--sections=1,8', '--', topic],
                    cwd='/', env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8',
                                  'HOME': str(Path.home())},
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, start_new_session=True,
                )
                self._process = process
            deadline = time.monotonic() + 0.65
            with selectors.DefaultSelector() as poller:
                poller.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if self.cancelled.is_set() or time.monotonic() >= deadline:
                        valid = False
                        break
                    ready = poller.select(min(0.05, max(0, deadline - time.monotonic())))
                    if not ready:
                        continue
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > MAX_OUTPUT:
                        valid = False
                        break
            if valid:
                try:
                    valid = process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0
                except subprocess.TimeoutExpired:
                    valid = False
        except (OSError, ValueError):
            valid = False
        finally:
            with self._lock:
                self._kill(process)
                self._process = None
            if process is not None:
                process.wait()
                if process.stdout:
                    process.stdout.close()
        if self.cancelled.is_set():
            return None
        text = parse_whatis(bytes(output), topic) if valid else None
        if len(self._cache) >= 256:
            self._cache.clear()
        self._cache[topic] = (time.monotonic() + (120 if text else 15), text)
        return text

    def explain(self, context, candidate, cwd):
        return describe(context, candidate, cwd, self.lookup_manual)


class HelpWorker:
    """Latest-only queue, separate from Bash completion so H never blocks GTK."""
    def __init__(self, deliver: Callable[[int, HelpText], None]):
        self.engine = HelpEngine()
        self.deliver = deliver
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name='auralyn-help', daemon=True)
        self._thread.start()

    def submit(self, serial: int, context: Context, candidate: Candidate, cwd: str):
        if self._closed:
            return
        self.engine.cancel()
        self._replace_pending((serial, context, candidate, cwd))

    def _replace_pending(self, value):
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait(value)

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None or self._closed:
                return
            serial, context, candidate, cwd = item
            self.engine.cancelled.clear()
            try:
                result = self.engine.explain(context, candidate, cwd)
            except Exception:
                result = HelpText(clean_text(candidate.display, 100), 'Kurzbeschreibung konnte nicht geladen werden.', 'Keine Beschreibung vorhanden')
            if not self._closed and not self.engine.cancelled.is_set():
                self.deliver(serial, result)

    def cancel(self):
        self.engine.cancel()
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass

    def close(self):
        self._closed = True
        self.engine.cancel()
        self._replace_pending(None)
