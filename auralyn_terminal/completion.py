"""Prefix completion over the real PATH and installed Bash completions.

No shell=True, no eval of input, and no execution of suggested commands. Complex
shell substitutions are intentionally left to Bash's own Tab completion.
"""
from __future__ import annotations
from dataclasses import dataclass, replace as replace_context
import os
import queue
import re
import shlex
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .programs import ProgramIndex
from .processes import ProcessIndex

MAX_RESULTS = 10000
SAFE_WORD = re.compile(r"^[a-zA-Z0-9_./:@%+=,~-]+$")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PRIORITY = {name: i for i, name in enumerate((
    "sudo", "run", "kill", "ssh", "systemctl", "apt", "apt-get", "adduser", "awk", "git",
    "python3", "pip3", "cd", "ls", "cat", "nano", "htop", "docker", "bash",
    "install", "update", "upgrade", "status", "start", "stop", "restart",
))}
# Used only when a native completion provider returns nothing / is unavailable.
# Installed commands themselves ALWAYS come from PATH, not from this table.
FALLBACK = {
    "apt": "list search show install reinstall remove purge autoremove autopurge update upgrade full-upgrade edit-sources help source build-dep clean autoclean download changelog policy depends rdepends", 
    "apt-get": "update upgrade install remove purge autoremove dist-upgrade clean autoclean check download source build-dep",
    "git": "add bisect branch checkout cherry-pick clean clone commit config diff fetch grep init log merge mv pull push rebase reflog remote reset restore revert rm show stash status switch tag worktree",
    "systemctl": "status start stop restart reload enable disable mask unmask daemon-reload list-units list-unit-files is-active is-enabled cat edit show reboot poweroff suspend",
    "docker": "build compose container exec images info inspect kill logs network ps pull push restart rm rmi run start stats stop system version volume",
    "flatpak": "install uninstall update list search run info repair remotes remote-add remote-delete override permission-show",
    "snap": "install remove refresh list find info connections connect disconnect services start stop restart",
    "pip": "install download uninstall freeze list show check config search cache index wheel hash completion debug help",
    "pip3": "install download uninstall freeze list show check config search cache index wheel hash completion debug help",
    "npm": "install uninstall update run start test init ci audit cache config list outdated publish version",
    "cargo": "build check clean doc new init add remove run test bench update search publish install uninstall fmt clippy",
    "auralyn-terminal": "--help --version --working-directory --no-suggestions",
}

@dataclass(frozen=True)
class Token:
    start: int
    end: int
    raw: str
    value: str
    operator: bool = False

@dataclass(frozen=True)
class Context:
    line: str
    point: int  # Character offset, NOT Bash's byte offset.
    start: int
    end: int
    prefix: str
    words: tuple[str, ...]
    command: str
    command_position: bool
    sudo: bool
    files_only: bool
    command_start: int

@dataclass(frozen=True)
class Candidate:
    value: str
    kind: str = "Befehl"
    no_space: bool = False
    literal: bool = True
    help_text: str = ""
    help_context: Context | None = None

    @property
    def display(self) -> str:
        return "".join(c if ord(c) >= 32 and ord(c) != 127 else "�" for c in self.value)


def _unquote(raw: str) -> str:
    out = []
    quote = None
    i = 0
    while i < len(raw):
        c = raw[i]
        if quote == "'":
            if c == "'":
                quote = None
            else:
                out.append(c)
        elif quote == '"':
            if c == '"':
                quote = None
            elif c == "\\" and i + 1 < len(raw) and raw[i + 1] in '$`"\\\n':
                i += 1
                out.append(raw[i])
            else:
                out.append(c)
        elif c in "'\"":
            quote = c
        elif c == "\\" and i + 1 < len(raw):
            i += 1
            out.append(raw[i])
        elif c != "\\":
            out.append(c)
        i += 1
    return "".join(out)


def lex(line: str) -> list[Token]:
    """Tokenize without expansions, retaining exact replacement spans."""
    tokens = []
    i = 0
    while i < len(line):
        if line[i].isspace():
            i += 1
            continue
        start = i
        if line[i] in ";&|<>()":
            i += 1
            if i < len(line) and line[i] == line[start] and line[start] in "&|<>":
                i += 1
            tokens.append(Token(start, i, line[start:i], line[start:i], True))
            continue
        quote = None
        while i < len(line):
            c = line[i]
            if quote == "'":
                if c == "'":
                    quote = None
            elif quote == '"':
                if c == '"':
                    quote = None
                elif c == "\\" and i + 1 < len(line):
                    i += 1
            elif c in "'\"":
                quote = c
            elif c == "\\" and i + 1 < len(line):
                i += 1
            elif c.isspace() or c in ";&|<>()":
                break
            i += 1
        raw = line[start:i]
        tokens.append(Token(start, i, raw, _unquote(raw)))
    return tokens


def parse_context(line: str, byte_point: int) -> Context | None:
    raw = line.encode("utf-8")
    if not 0 <= byte_point <= len(raw) or len(raw) > 65536:
        return None
    # A popup is not a Bash parser. Never interpret substitutions or heredocs.
    if any(part in line for part in ("\n", "\r", "`", "$(", "${", "<<", "<(" , ">(")):
        return None
    try:
        point = len(raw[:byte_point].decode("utf-8"))
    except UnicodeError:
        return None
    tokens = lex(line)
    current = next((t for t in tokens if not t.operator and t.start <= point <= t.end), None)
    if current is None:
        current = Token(point, point, "", "")
    prefix = _unquote(line[current.start:point])
    # Do not complete inside comments, variables, shell globs or multiline input.
    if prefix.startswith("#") or any(c in prefix for c in "$*?[]{}"):
        return None
    before = [t for t in tokens if t.end <= current.start and t is not current]
    segment = []
    for token in before:
        if token.operator and token.value in (";", "&&", "||", "|", "&", "(", ")"):
            segment = []
        else:
            segment.append(token)
    if any(t.raw.startswith("#") for t in segment):
        return None
    files_only = bool(segment and segment[-1].operator and segment[-1].value in ("<", ">", ">>"))
    segment = [t for t in segment if not t.operator]
    while segment and ASSIGNMENT.match(segment[0].value):
        segment.pop(0)
    segment.append(Token(current.start, current.end, current.raw, prefix))
    idx = 0
    sudo = False
    while idx < len(segment) - 1:
        name = segment[idx].value
        if name not in ("sudo", "command", "builtin", "env", "nohup", "nice"):
            break
        if name == "sudo":
            sudo = True
        idx += 1
        need_value = {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "-T", "-R", "-D"} if name == "sudo" else {"-n", "--adjustment"} if name == "nice" else {"-u", "--unset", "-C", "--chdir"} if name == "env" else set()
        while idx < len(segment) - 1:
            word = segment[idx].value
            if word == "--":
                idx += 1
                break
            if word in need_value:
                # Still entering the option's value? Native wrapper completion.
                if idx + 1 >= len(segment) - 1:
                    idx = 0
                    break
                idx += 2
                continue
            if word.startswith("-") or (name == "env" and ASSIGNMENT.match(word)):
                idx += 1
                continue
            break
        if idx == 0:
            break
        if idx == len(segment) - 1 and prefix.startswith("-"):
            idx = 0
            break
    effective = segment[idx:]
    words = tuple(t.value for t in effective)
    if not words:
        return None
    return Context(line, point, current.start, current.end, prefix, words,
                   words[0], len(words) == 1 and not files_only, sudo,
                   files_only, effective[0].start)


def quote_literal(value: str) -> str:
    if SAFE_WORD.fullmatch(value):
        return value
    return shlex.quote(value)


def replacement(context: Context, candidate: Candidate) -> tuple[str, int]:
    """Replace the WHOLE word and return a new line + UTF-8 BYTE cursor offset."""
    value = candidate.value
    # Completion scripts commonly escape spaces. Normalize just the escape
    # notation, then re-quote as a literal. Never allow a candidate to add code.
    if not candidate.literal:
        value = _unquote(value)
    # Preserve home expansion for ~/ paths. Do not quote the tilde itself.
    if value.startswith("~/"):
        insert = "~/" + quote_literal(value[2:]) if value[2:] else "~/"
    else:
        insert = quote_literal(value)
    tail = context.line[context.end:]
    add_space = not candidate.no_space and not value.endswith(("/", "="))
    if add_space and not tail.startswith((" ", "\t")):
        insert += " "
    result = context.line[:context.start] + insert + tail
    char_point = context.start + len(insert)
    return result, len(result[:char_point].encode("utf-8"))


class PathIndex:
    def __init__(self):
        self._cache: dict[tuple, tuple[float, dict[str, str]]] = {}

    def commands(self, path: str, cwd: str, sudo: bool = False) -> dict[str, str]:
        directories = list(dict.fromkeys(path.split(os.pathsep)))
        if sudo:
            directories.extend(d for d in ("/usr/local/sbin", "/usr/sbin", "/sbin") if d not in directories)
        dirs = [os.path.abspath(os.path.join(cwd, d or ".")) for d in directories]
        fingerprint = []
        for directory in dirs:
            try:
                st = os.stat(directory)
                fingerprint.append((directory, st.st_mtime_ns, st.st_ino))
            except OSError:
                fingerprint.append((directory, None))
        key = (tuple(fingerprint), sudo)
        found = self._cache.get(key)
        now = time.monotonic()
        if found and now - found[0] < 3.0:
            return found[1]
        result = {}
        for directory in dirs:
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if len(result) >= 50000:
                            break
                        try:
                            executable = bool(entry.stat().st_mode & 0o111) if sudo else os.access(entry.path, os.X_OK)
                            if entry.is_file() and executable:
                                result.setdefault(entry.name, "Programm")
                        except OSError:
                            continue
            except OSError:
                continue
        self._cache = {key: (now, result)}
        return result


def files(prefix: str, cwd: str, directories_only: bool = False, executable_only: bool = False) -> list[Candidate]:
    directory, leaf = os.path.split(prefix)
    # Keep ~/ as a UI prefix but enumerate the real home directory.
    disk_dir = os.path.expanduser(directory or ".")
    if not os.path.isabs(disk_dir):
        disk_dir = os.path.join(cwd, disk_dir)
    result = []
    try:
        with os.scandir(disk_dir) as entries:
            for entry in entries:
                if not entry.name.startswith(leaf) or (entry.name.startswith(".") and not leaf.startswith(".")):
                    continue
                try:
                    is_dir = entry.is_dir()
                    if directories_only and not is_dir:
                        continue
                    if executable_only and not is_dir and not (entry.is_file() and os.access(entry.path, os.X_OK)):
                        continue
                    value = (directory + "/" if directory else "") + entry.name + ("/" if is_dir else "")
                    result.append(Candidate(value, "Ordner" if is_dir else "Datei", is_dir))
                except OSError:
                    continue
                if len(result) >= MAX_RESULTS:
                    break
    except OSError:
        pass
    return sorted(result, key=lambda x: (x.kind != "Ordner", x.value.casefold()))


CUSTOM_HELP = {
    "run": "Startet ein installiertes Programm oder einen App-Menü-Eintrag. Nach run werden passende Programme vorgeschlagen. Für interaktive Terminalprogramme: run --foreground NAME.",
    "kill": "Beendet das ausgewählte eigene Programm sofort. Ungespeicherte Änderungen können verloren gehen! Mit einer PID oder Signaloption gilt weiterhin die normale Bash-kill-Syntax.",
}


def custom_action(ctx: Context, shell_names: list[str]) -> str | None:
    """Only intercept our installed shell function, never sudo/builtin/command."""
    name = ctx.command
    action = name.removeprefix('auralyn-')
    if action not in CUSTOM_HELP or ctx.sudo or '/' in name:
        return None
    if name.startswith('auralyn-'):
        if name not in shell_names:
            return None
    elif '__auralyn_' + action + '_enabled' not in shell_names:
        return None
    before = []
    for token in lex(ctx.line[:ctx.command_start]):
        if token.operator and token.value in (';', '&&', '||', '|', '&', '(', ')'):
            before = []
        else:
            before.append(token)
    if any(not ASSIGNMENT.match(t.value) for t in before):
        return None
    return action


class Engine:
    def __init__(self, helper: Path):
        self.helper = helper
        self.index = PathIndex()
        self.program_index = ProgramIndex()
        self.cancelled = threading.Event()
        self._process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()
        with self._process_lock:
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def native(self, ctx: Context, cwd: str, path: str) -> list[Candidate]:
        if self.cancelled.is_set():
            return []
        # COMP_LINE retains original quotes; COMP_WORDS contains decoded words.
        line = ctx.line[ctx.command_start:ctx.point]
        env = dict(os.environ)
        env["PATH"] = path
        env["PWD"] = cwd
        env.pop("BASH_ENV", None)
        env.pop("ENV", None)
        try:
            with self._process_lock:
                if self.cancelled.is_set():
                    return []
                process = subprocess.Popen(
                    ["/bin/bash", "--noprofile", "--norc", str(self.helper), line,
                     str(len(line.encode("utf-8"))), str(len(ctx.words) - 1), *ctx.words],
                    cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._process = process
            try:
                output, _ = process.communicate(timeout=0.85)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                output, _ = process.communicate()
                return []
        except (OSError, ValueError):
            return []
        finally:
            with self._process_lock:
                self._process = None
        if self.cancelled.is_set() or len(output) > 4 * 1024 * 1024:
            return []
        values = output.split(b"\0")
        if len(values) < 2:
            return []
        no_space = values[0] == b"1"
        result = []
        for raw in values[1:MAX_RESULTS + 1]:
            if not raw:
                continue
            try:
                value = raw.decode("utf-8")
            except UnicodeError:
                continue
            if len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                continue
            # COMPREPLY generally contains literal words, but some providers
            # add shell escapes or an explicit trailing completion-space.
            disk_value = os.path.expanduser(value)
            if not os.path.isabs(disk_value):
                disk_value = os.path.join(cwd, disk_value)
            exists = os.path.lexists(disk_value)
            item_no_space = no_space
            if not exists:
                if value.endswith(" "):
                    value = value.rstrip(" ")
                    item_no_space = False
                # Preserve literal apostrophes (O'Brien) in unquoted replies.
                if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                    value = _unquote(value)
                elif "\\" in value:
                    value = re.sub(r"\\(.)", r"\1", value)
            if not value.startswith(ctx.prefix):
                continue
            result.append(Candidate(value, "Bash", item_no_space or value.endswith(("/", "=")), True))
        return result

    def complete(self, ctx: Context, cwd: str, path: str, shell_names: list[str], use_native: bool = True) -> list[Candidate]:
        if ctx.command_position:
            if "/" in ctx.prefix or ctx.prefix.startswith("~"):
                return files(ctx.prefix, cwd, executable_only=True)
            if not ctx.prefix:
                return []
            commands = dict(self.index.commands(path, cwd, ctx.sudo))
            if not ctx.sudo:
                for name in shell_names:
                    if name and not name.startswith("__auralyn_"):
                        commands.setdefault(name, "Shell")
            items = []
            for name, kind in commands.items():
                if not name.startswith(ctx.prefix):
                    continue
                item_context = replace_context(ctx, command=name)
                action = custom_action(item_context, shell_names)
                items.append(Candidate(name, "Auralyn" if action else kind,
                                       help_text=CUSTOM_HELP[action] if action else ""))
            return self._sort(items, ctx.prefix)
        if ctx.files_only:
            return files(ctx.prefix, cwd)
        action = custom_action(ctx, shell_names)
        if action:
            result = self._custom_complete(action, ctx, cwd, path, use_native)
            if result is not None:
                return result
        if use_native:
            result = self.native(ctx, cwd, path)
            if result:
                return self._sort(result, ctx.prefix)
        cmd = os.path.basename(ctx.command)
        if len(ctx.words) == 2 and cmd in FALLBACK and not ctx.prefix.startswith(("/", ".", "~")):
            result = [Candidate(word, "Unterbefehl") for word in FALLBACK[cmd].split() if word.startswith(ctx.prefix)]
            if result:
                return self._sort(result, ctx.prefix)
        return files(ctx.prefix, cwd, directories_only=cmd in ("cd", "pushd", "rmdir"))

    def _custom_complete(self, action: str, ctx: Context, cwd: str, path: str,
                         use_native: bool) -> list[Candidate] | None:
        if self.cancelled.is_set():
            return []
        words = ctx.words
        prefix = ctx.prefix
        if len(words) == 2 and prefix.startswith('-'):
            options = ('--foreground', '--list', '--help') if action == 'run' else ('--app', '--list', '--help')
            descriptions = {
                '--foreground': 'Startet ein ausführbares Programm interaktiv in diesem Terminal, statt im Hintergrund. Geeignet für nano, htop und andere Terminalprogramme.',
                '--app': 'Wählt ausdrücklich nach einem App- oder Prozessnamen aus, auch bei Namen, die wie eine Zahl aussehen. Erzwingt das Beenden; ungespeicherte Daten können verloren gehen.',
                '--list': 'Zeigt die lokal erkannten Programmnamen an. Startet und beendet nichts.',
                '--help': 'Zeigt die Bedienung dieses Auralyn-Befehls an. Startet und beendet nichts.',
            }
            options_result = [Candidate(v, 'Option', help_text=descriptions[v]) for v in options if v.startswith(prefix)]
            if options_result or action == 'run':
                return options_result
            return None  # kill -9/-s/-l retain native Bash completion.
        start = 1
        foreground = False
        allowed = ('--foreground', '-f', '--') if action == 'run' else (('--app', '--') if ctx.command == 'auralyn-kill' else ('--app',))
        while start < len(words) - 1 and words[start] in allowed:
            foreground = foreground or words[start] in ('--foreground', '-f')
            start += 1
        if start < len(words) - 1 and words[start] in ('--list', '--help'):
            return []
        if action == 'kill' and start == 1 and ((prefix.isdecimal() and len(words) == 2) or
                                               words[1].startswith(('-', '%'))):
            return None
        if len(words) - 1 == start:
            if action == 'run':
                if '/' in prefix or prefix.startswith('~'):
                    return files(prefix, cwd, executable_only=True)
                apps = self.program_index.choices(path, cwd)
                matches = [p for p in apps if (not foreground or p.kind == 'executable') and
                           p.name.casefold().startswith(prefix.casefold())]
                # App-menu entries first, then PATH tools; both stay searchable.
                return [Candidate(p.name, 'App starten' if p.kind == 'desktop' else 'Programm starten',
                                  help_text=("Startet dieses Programm interaktiv in diesem Terminal. Die Tastatur und Programmausgabe bleiben hier; Strg+C funktioniert wie gewohnt." if foreground else p.help_text)) for p in matches[:MAX_RESULTS]]
            apps = self.program_index.applications(path, cwd)
            targets = ProcessIndex(apps=apps).targets()
            return [Candidate(t.name, 'Sofort beenden', help_text=t.help_text)
                    for t in targets if t.name.casefold().startswith(prefix.casefold())][:MAX_RESULTS]
        if action == 'kill':
            return []
        # For run git ..., delegate to git's real completion definitions.
        name = words[start]
        program = self.program_index.resolve(name, path, cwd)
        if program and program.kind == 'executable':
            tokens = lex(ctx.line[ctx.command_start:ctx.point])
            if len(tokens) > start:
                command_start = ctx.command_start + tokens[start].start
                nested = replace_context(ctx, command=name, words=words[start:], command_start=command_start)
                if use_native:
                    candidates = self.native(nested, cwd, path)
                    if candidates:
                        return self._sort([replace_context(c, help_context=nested) for c in candidates], prefix)
                cmd = os.path.basename(name)
                if len(nested.words) == 2 and cmd in FALLBACK:
                    candidates = [Candidate(v, 'Unterbefehl', help_context=nested) for v in FALLBACK[cmd].split() if v.startswith(prefix)]
                    if candidates:
                        return self._sort(candidates, prefix)
        return files(prefix, cwd)

    @staticmethod
    def _sort(items: list[Candidate], prefix: str) -> list[Candidate]:
        unique = {item.value: item for item in items}
        return sorted(unique.values(), key=lambda c: (c.value != prefix, PRIORITY.get(c.value, 1000), c.value.casefold()))[:MAX_RESULTS]


class CompletionWorker:
    """One latest-only queue per tab; slow providers cannot block GTK/Readline."""
    def __init__(self, helper: Path, deliver: Callable):
        self.engine = Engine(helper)
        self.deliver = deliver
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="auralyn-completion", daemon=True)
        self._thread.start()

    def submit(self, serial: int, context: Context, cwd: str, path: str, names: list[str], native: bool):
        self.engine.cancel()
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait((serial, context, cwd, path, names, native))

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            if self._closed:
                return
            self.engine.cancelled.clear()
            serial, context, cwd, path, names, native = item
            try:
                candidates = self.engine.complete(context, cwd, path, names, native)
            except Exception:
                candidates = []
            if not self._closed:
                self.deliver(serial, context, candidates)

    def close(self):
        self._closed = True
        self.engine.cancel()
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
