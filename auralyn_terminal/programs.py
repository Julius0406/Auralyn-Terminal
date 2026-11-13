"""Read-only installed application catalogue shared by completion and run/kill.

The Exec key is inspected only for conservative process matching. Desktop
entries are NEVER executed by this module; launching is delegated to GLib/GIO.
No shell, eval, --help invocation, or program discovery subprocess is used.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import shutil
import time
import unicodedata
from typing import Mapping

MAX_ENTRIES = 50000
MAX_DESKTOP_BYTES = 262144


def safe_name(value: str) -> bool:
    return bool(value and len(value) <= 240 and not value.startswith('-') and
                all(not unicodedata.category(c).startswith('C') for c in value))


def display_text(value: str, limit: int = 220) -> str:
    return ' '.join(''.join(c for c in value if not unicodedata.category(c).startswith('C')).split())[:limit]


def desktop_unescape(value: str) -> str:
    return re.sub(r'\\([sntr\\])', lambda m: {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}[m[1]], value)


def locale_keys(env: Mapping[str, str]) -> list[str]:
    locale = env.get('LC_ALL') or env.get('LC_MESSAGES') or env.get('LANG', '')
    # LANGUAGE is a GNU list, used for application menu translations on Ubuntu.
    values = env.get('LANGUAGE', '').split(':') if locale not in ('C', 'POSIX') else []
    values.append(locale)
    result: list[str] = []
    for value in values:
        if not value or value in ('C', 'POSIX'):
            continue
        value = re.sub(r'\.[^@]*', '', value)
        basic, _, modifier = value.partition('@')
        language = basic.split('_')[0]
        for variant in (value, basic, language + ('@' + modifier if modifier else ''), language):
            if variant not in result:
                result.append(variant)
    return result


def localized(section, key: str, env: Mapping[str, str]) -> str:
    for locale in locale_keys(env):
        value = section.get(f'{key}[{locale}]')
        if value:
            return desktop_unescape(value)
    return desktop_unescape(section.get(key, ''))


def desktop_dirs(env: Mapping[str, str]) -> list[Path]:
    home = Path(env.get('HOME', str(Path.home())))
    data_home = Path(env.get('XDG_DATA_HOME') or home / '.local/share')
    if not data_home.is_absolute():
        data_home = home / '.local/share'
    data_dirs = env.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share'
    bases = [data_home] + [Path(p) for p in data_dirs.split(':') if os.path.isabs(p)]
    bases += [home / '.local/share/flatpak/exports/share',
              Path('/var/lib/flatpak/exports/share'), Path('/var/lib/snapd/desktop')]
    return list(dict.fromkeys(base / 'applications' for base in bases))


def read_desktop(path: Path):
    """Bounded key-file reader. Malformed or oversized launchers are ignored."""
    try:
        with path.open('r', encoding='utf-8-sig') as stream:
            text = stream.read(MAX_DESKTOP_BYTES + 1)
        if len(text) > MAX_DESKTOP_BYTES:
            return None
        parser = configparser.ConfigParser(interpolation=None, strict=False, delimiters=('=',),
                                           comment_prefixes=('#',), inline_comment_prefixes=None)
        parser.optionxform = str
        parser.read_string(text)
        return parser['Desktop Entry'] if parser.has_section('Desktop Entry') else None
    except (OSError, UnicodeError, configparser.Error):
        return None


def executable_tokens(exec_value: str) -> tuple[str, ...]:
    """Not an Exec implementation! Only a conservative matching hint.

    All actual launching (field codes, DBus, Terminal, Path) is left to GIO.
    """
    try:
        words = shlex.split(desktop_unescape(exec_value))
    except ValueError:
        return ()
    if words and os.path.basename(words[0]) == 'env':
        words.pop(0)
        while words and ('=' in words[0] and not words[0].startswith('-')):
            words.pop(0)
        if words and words[0] == '--':
            words.pop(0)
        if not words or words[0].startswith('-'):
            return ()
    return tuple(words)


@dataclass(frozen=True)
class Program:
    name: str
    kind: str  # desktop / executable
    path: str
    desktop_id: str = ''
    description: str = ''
    exec_words: tuple[str, ...] = ()
    terminal: bool = False
    flatpak_id: str = ''

    @property
    def aliases(self) -> tuple[str, ...]:
        values = [self.name]
        if self.desktop_id:
            values += [self.desktop_id, self.desktop_id.removesuffix('.desktop')]
        return tuple(dict.fromkeys(values))

    @property
    def help_text(self) -> str:
        if self.kind == 'desktop':
            detail = (display_text(self.description, 140) + ' ') if self.description else ''
            return detail + 'Startet diesen Eintrag aus deinem App-Menü. Der Start wird erst mit Enter ausgeführt.'
        return 'Startet dieses installierte Programm im Hintergrund. Für interaktive Terminalprogramme: run --foreground NAME. Erst Enter führt den Start aus.'


class AmbiguousProgram(ValueError):
    pass


class ProgramIndex:
    def __init__(self, env: Mapping[str, str] | None = None, roots: list[Path] | None = None):
        self.env = env  # None means fresh environment on every refresh.
        self.roots = roots
        self._cache_key = None
        self._cache_time = 0.0
        self._cached: tuple[Program, ...] = ()

    def applications(self, path: str, cwd: str) -> tuple[Program, ...]:
        env = dict(os.environ if self.env is None else self.env)
        roots = self.roots if self.roots is not None else desktop_dirs(env)
        key = (path, cwd, tuple(map(str, roots)), tuple(locale_keys(env)), env.get('XDG_CURRENT_DESKTOP', ''))
        now = time.monotonic()
        if key == self._cache_key and now - self._cache_time < 1.5:
            return self._cached
        found: list[Program] = []
        executable_names: set[str] = set()
        for directory in dict.fromkeys(path.split(os.pathsep)):
            directory = os.path.abspath(os.path.join(cwd, directory or '.'))
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if len(executable_names) >= MAX_ENTRIES:
                            break
                        try:
                            if entry.name not in executable_names and safe_name(entry.name) and entry.is_file() and os.access(entry.path, os.X_OK):
                                executable_names.add(entry.name)
                                found.append(Program(entry.name, 'executable', entry.path))
                        except OSError:
                            continue
            except OSError:
                continue
        seen_ids: set[str] = set()
        desktops = env.get('XDG_CURRENT_DESKTOP', '').split(':')
        for root in roots:
            # os.walk does not follow directory symlinks; flatpak file symlinks work.
            scanned = 0
            for directory, dirs, filenames in os.walk(root, followlinks=False):
                dirs.sort()
                if len(Path(directory).relative_to(root).parts) > 8:
                    dirs[:] = []
                    continue
                for filename in sorted(filenames):
                    if not filename.endswith('.desktop'):
                        continue
                    scanned += 1
                    if scanned > 10000:
                        break
                    filename_path = Path(directory) / filename
                    desktop_id = '-'.join(filename_path.relative_to(root).parts)
                    if desktop_id in seen_ids:
                        continue
                    seen_ids.add(desktop_id)  # Hidden user files mask the system file.
                    section = read_desktop(filename_path)
                    if section is None or section.get('Type') != 'Application':
                        continue
                    if section.get('Hidden', '').lower() == 'true' or section.get('NoDisplay', '').lower() == 'true':
                        continue
                    only = section.get('OnlyShowIn', '').split(';')
                    not_in = section.get('NotShowIn', '').split(';')
                    if section.get('OnlyShowIn') and not any(d and d in only for d in desktops):
                        continue
                    if any(d and d in not_in for d in desktops):
                        continue
                    name = localized(section, 'Name', env)
                    if not safe_name(name):
                        continue
                    try_exec = desktop_unescape(section.get('TryExec', ''))
                    if try_exec and not find_executable(try_exec, path, cwd):
                        continue
                    words = executable_tokens(section.get('Exec', ''))
                    if not words and section.get('DBusActivatable', '').lower() != 'true':
                        continue
                    # Stale menu entries without DBus and without an executable
                    # cannot be launched. Snap wrappers/Flatpak work through PATH.
                    if words and section.get('DBusActivatable', '').lower() != 'true' and not find_executable(words[0], path, cwd):
                        continue
                    found.append(Program(name, 'desktop', str(filename_path), desktop_id,
                                         localized(section, 'Comment', env), words,
                                         section.get('Terminal', '').lower() == 'true', section.get('X-Flatpak', '')))
                if scanned > 10000:
                    break
        self._cache_key, self._cache_time, self._cached = key, now, tuple(found)
        return self._cached

    def choices(self, path: str, cwd: str) -> tuple[Program, ...]:
        """Expose unambiguous insertion strings, even with duplicate menu names."""
        apps = self.applications(path, cwd)
        counts: dict[str, int] = {}
        for p in apps:
            counts[p.name] = counts.get(p.name, 0) + 1
        result = []
        for p in apps:
            if p.kind == 'desktop' and counts[p.name] > 1:
                p = Program(p.desktop_id, p.kind, p.path, p.desktop_id,
                            p.description, p.exec_words, p.terminal, p.flatpak_id)
            result.append(p)
        return tuple(sorted(result, key=lambda p: (p.kind != 'desktop', p.name.casefold(), p.path)))

    def resolve(self, name: str, path: str, cwd: str) -> Program | None:
        # Literal executable names take precedence, matching normal shell intent.
        executable = find_executable(name, path, cwd)
        if executable:
            return Program(name, 'executable', executable)
        apps = [p for p in self.applications(path, cwd) if p.kind == 'desktop']
        exact = [p for p in apps if name in p.aliases]
        matches = exact or [p for p in apps if name.casefold() in {a.casefold() for a in p.aliases}]
        if len(matches) > 1:
            raise AmbiguousProgram('Mehrere Apps heißen so. Bitte den eindeutigen Namen verwenden: ' + ', '.join(p.desktop_id for p in matches))
        return matches[0] if matches else None


def find_executable(name: str, path: str, cwd: str) -> str | None:
    if not name or '\0' in name:
        return None
    if '/' in name:
        value = os.path.expanduser(name)
        value = value if os.path.isabs(value) else os.path.join(cwd, value)
        return os.path.abspath(value) if os.path.isfile(value) and os.access(value, os.X_OK) else None
    absolute_path = os.pathsep.join(os.path.abspath(os.path.join(cwd, d or '.')) for d in path.split(os.pathsep))
    return shutil.which(name, path=absolute_path)
