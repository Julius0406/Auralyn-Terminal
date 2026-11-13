"""User-owned process suggestions and exact, pidfd-pinned force-stop targets.

No pkill pattern, substring command-line search, shell execution, sudo, negative
PID, or process-group signal is used here. The existing Bash kill builtin stays
available for explicit PID/job/signal syntax, outside this name-based helper.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
from typing import Iterable

from .programs import Program, display_text, safe_name

CORE = frozenset(('systemd', 'init', 'gnome-shell', 'gnome-session', 'gnome-session-binary',
                  'gnome-settings-daemon', 'gdm', 'gdm3', 'gdm-session-worker', 'gdm-x-session',
                  'gdm-wayland-session', 'Xorg', 'Xwayland', 'mutter', 'kwin_wayland', 'kwin_x11',
                  'plasmashell', 'xfwm4', 'xfce4-session', 'sway', 'weston', 'cosmic-comp',
                  'dbus-daemon', 'dbus-broker', 'dbus-broker-launch', 'dbus-launch',
                  'pipewire', 'pipewire-pulse', 'wireplumber', 'pulseaudio', 'rtkit-daemon',
                  'NetworkManager', 'polkitd', 'sshd', 'login', 'sudo', 'su', 'snapd',
                  'gnome-keyring-daemon', 'gcr-prompter', 'gcr-ssh-agent',
                  'auralyn-terminal', 'auralyn-run', 'auralyn-kill',
                  'bash', 'sh', 'dash', 'zsh', 'fish', 'loginctl'))
HOST = re.compile(r'^(?:python(?:\d+(?:\.\d+)*)?|pypy\d*|java|javaw|node|nodejs|ruby(?:\d+(?:\.\d+)*)?|perl|mono|wine(?:64)?(?:-preloader)?|wineserver|flatpak|bwrap|snap|env|electron)$', re.I)


def executable_name(value: str) -> str:
    return os.path.basename(value.removesuffix(' (deleted)'))


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    uid: int
    start: int
    exe: str
    argv: tuple[str, ...]
    comm: str
    state: str = 'S'

    @property
    def name(self) -> str:
        return executable_name(self.exe) or (executable_name(self.argv[0]) if self.argv else self.comm)


def read_process(pid: int, proc_root: Path = Path('/proc')) -> Process | None:
    try:
        base = proc_root / str(pid)
        text = (base / 'stat').read_text()[:32768]
        left, right = text.index('('), text.rindex(')')
        comm = text[left + 1:right]
        fields = text[right + 2:].split()
        if int(text[:left]) != pid or len(fields) < 20 or fields[0] in ('Z', 'X', 'x'):
            return None
        status = (base / 'status').read_text()[:65536]
        uid_line = next(line for line in status.splitlines() if line.startswith('Uid:'))
        uids = tuple(int(v) for v in uid_line.split()[1:])
        # Exclude setuid/sudo transitions instead of relying solely on directory UID.
        if len(uids) != 4 or len(set(uids)) != 1:
            return None
        with (base / 'cmdline').open('rb') as stream:
            raw = stream.read(65536)
        argv = tuple(s.decode('utf-8', errors='replace') for s in raw.rstrip(b'\0').split(b'\0')) if raw else ()
        try:
            exe = os.readlink(base / 'exe')
        except OSError:
            exe = ''
        if not exe and not argv:
            return None
        return Process(pid, int(fields[1]), uids[0], int(fields[19]), exe, argv, comm, fields[0])
    except (OSError, ValueError, StopIteration, IndexError):
        return None


def scan_processes(uid: int | None = None, proc_root: Path = Path('/proc')) -> dict[int, Process]:
    uid = os.getuid() if uid is None else uid
    result = {}
    try:
        with os.scandir(proc_root) as entries:
            for entry in entries:
                if not entry.name.isdecimal():
                    continue
                try:
                    if entry.stat().st_uid != uid:
                        continue
                except OSError:
                    continue
                proc = read_process(int(entry.name), proc_root)
                if proc and proc.uid == uid:
                    result[proc.pid] = proc
    except OSError:
        pass
    return result


def ancestors(processes: dict[int, Process], seeds: Iterable[int]) -> set[int]:
    result = {0, 1}
    for pid in seeds:
        while pid > 1 and pid not in result:
            result.add(pid)
            current = processes.get(pid)
            if current is None:
                break
            pid = current.ppid
    return result


def protected(proc: Process, excluded: set[int]) -> bool:
    if proc.pid <= 1 or proc.pid in excluded:
        return True
    names = {proc.name, proc.comm}
    if proc.argv:
        names.add(executable_name(proc.argv[0]))
    if any(name in CORE or name.startswith(('gsd-', 'gdm-', 'xdg-desktop-portal')) for name in names):
        return True
    # Protect every Auralyn instance, not just the current tab's ancestors.
    for arg in proc.argv[1:]:
        normalized = arg.replace('\\', '/')
        if ('auralyn-terminal' in normalized or '/auralyn-work/' in normalized) and normalized.endswith(('/launcher.py', '/program_launcher.py')):
            return True
        if arg in ('auralyn_terminal', 'auralyn_terminal.program_cli'):
            return True
    return False


def runtime_label(proc: Process) -> str:
    name = proc.name
    argv = proc.argv
    if len(argv) > 2 and argv[1] == '-m' and name.lower().startswith(('python', 'pypy')):
        return argv[2]
    if '-jar' in argv and name.lower() in ('java', 'javaw'):
        pos = argv.index('-jar') + 1
        if pos < len(argv):
            return executable_name(argv[pos])
    if len(argv) > 1 and not argv[1].startswith('-') and name.lower().startswith(('python', 'pypy', 'node', 'ruby', 'perl', 'mono', 'wine')):
        return executable_name(argv[1].replace('\\', '/'))
    return name


def matching_desktop(proc: Process, apps: tuple[Program, ...]) -> Program | None:
    # Do not equate `java`, `flatpak`, `steam -applaunch`, shell wrappers, etc.
    # with a specific app. Unknown wrappers simply keep their actual process name.
    if HOST.fullmatch(proc.name):
        return None
    for app in apps:
        if app.kind != 'desktop' or not app.exec_words:
            continue
        executable, *arguments = app.exec_words
        base = executable_name(executable)
        if base in CORE or HOST.fullmatch(base):
            continue
        if any(not arg.startswith('%') for arg in arguments):
            continue
        names = {proc.name, executable_name(proc.argv[0]) if proc.argv else ''}
        if base in names:
            return app
        if os.path.isabs(executable) and proc.exe and os.path.realpath(executable) == proc.exe.removesuffix(' (deleted)'):
            return app
    return None


@dataclass(frozen=True)
class Target:
    name: str
    roots: tuple[Process, ...]
    aliases: tuple[str, ...]

    @property
    def help_text(self) -> str:
        amount = len(self.roots)
        return (f'Erzwingt das Beenden von „{display_text(self.name, 85)}“ '
                f'({amount} zugeordnete Prozesse, ggf. weitere Kindprozesse). '
                'Nur dein Benutzerkonto. Ungespeicherte Änderungen gehen verloren. '
                'Tab/H beendet nichts; erst Enter führt kill aus.')


class AmbiguousTarget(ValueError):
    pass


class ProcessIndex:
    def __init__(self, processes: dict[int, Process] | None = None, uid: int | None = None,
                 exclude_pids: Iterable[int] | None = None, apps: Iterable[Program] = ()):
        self.uid = os.getuid() if uid is None else uid
        self.processes = scan_processes(self.uid) if processes is None else processes
        self.excluded = ancestors(self.processes, (os.getpid(), os.getppid()) if exclude_pids is None else exclude_pids)
        self.apps = tuple(apps)
        self.allowed = {pid: p for pid, p in self.processes.items()
                        if p.uid == self.uid and not protected(p, self.excluded) and p.state not in ('Z', 'X', 'x')}

    def targets(self) -> tuple[Target, ...]:
        grouped: dict[tuple, list[Process]] = {}
        for proc in self.allowed.values():
            shared = bool(HOST.fullmatch(proc.name)) or not proc.exe
            key = ('pid', proc.pid) if shared else ('exe', proc.exe)
            grouped.setdefault(key, []).append(proc)
        raw = []
        for key, members in grouped.items():
            members.sort(key=lambda p: p.pid)
            proc = members[0]
            desktop = matching_desktop(proc, self.apps) if key[0] != 'pid' else None
            label = desktop.name if desktop else runtime_label(proc) if key[0] == 'pid' else proc.name
            label = display_text(label, 160)
            if not safe_name(label):
                continue
            aliases = [label, proc.name]
            if desktop:
                aliases.extend(desktop.aliases)
            if key[0] == 'pid':
                label += f' [PID {proc.pid}]'
            raw.append(Target(label, tuple(members), tuple(dict.fromkeys(aliases))))
        # Different executables may share a basename; the suggestions must still
        # be unique. Full PID disambiguation affects names, not signal semantics.
        counts: dict[str, int] = {}
        for t in raw:
            counts[t.name.casefold()] = counts.get(t.name.casefold(), 0) + 1
        result = [Target(t.name + f' [PID {t.roots[0].pid}]', t.roots, t.aliases)
                  if counts[t.name.casefold()] > 1 else t for t in raw]
        return tuple(sorted(result, key=lambda t: (t.name.casefold(), t.roots[0].pid)))

    def resolve(self, name: str) -> Target | None:
        targets = self.targets()
        exact = [t for t in targets if t.name == name]
        exact = exact or [t for t in targets if t.name.casefold() == name.casefold()]
        matches = exact or [t for t in targets if name.casefold() in {a.casefold() for a in t.aliases}]
        if len(matches) > 1:
            raise AmbiguousTarget('Nicht eindeutig. Bitte einen Vorschlag mit PID auswählen: ' + ', '.join(t.name for t in matches[:12]))
        return matches[0] if matches else None

    def members(self, target: Target) -> tuple[Process, ...]:
        selected = {p.pid for p in target.roots}
        children: dict[int, list[int]] = {}
        for p in self.allowed.values():
            children.setdefault(p.ppid, []).append(p.pid)
        queue = list(selected)
        while queue:
            for child in children.get(queue.pop(), ()):
                if child not in selected:
                    selected.add(child)
                    queue.append(child)
        # Signal children before root processes, reducing newly orphaned helpers.
        roots = {p.pid for p in target.roots}
        return tuple(sorted((self.allowed[pid] for pid in selected if pid in self.allowed),
                            key=lambda p: (p.pid in roots, -p.pid)))


def send_force_stop(processes: Iterable[Process], excluded: set[int]) -> tuple[int, int]:
    """Pin each process, validate identity again, then send SIGKILL.

    Refuse the operation when pidfds are unavailable; never downgrade to a
    potentially recycled numeric PID. Returns (signals sent, skipped/denied).
    """
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Sicheres Beenden per pidfd ist auf diesem System nicht verfügbar.')
    sent = skipped = 0
    for original in processes:
        if original.uid != os.getuid() or protected(original, excluded):
            skipped += 1
            continue
        fd = None
        try:
            fd = os.pidfd_open(original.pid, 0)
            current = read_process(original.pid)
            if (current is None or current.start != original.start or current.uid != original.uid or
                    current.exe != original.exe or protected(current, excluded)):
                skipped += 1
                continue
            signal.pidfd_send_signal(fd, signal.SIGKILL, None, 0)
            sent += 1
        except (OSError, ValueError):
            skipped += 1
        finally:
            if fd is not None:
                os.close(fd)
    return sent, skipped
