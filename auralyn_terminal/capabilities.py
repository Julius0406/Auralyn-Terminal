"""Read-only command discovery and local manual evidence for Smart Search.

Never run discovered programs, --help switches, completions or repository code.
Only executable *names* are indexed. Manuals in fixed documentation directories
are read as bounded text, without running roff macros, pagers or shell commands.
No home directories, terminal history, environment values or file contents are
sent to the model. ~/.local/bin names are included if they are on PATH.
"""
from __future__ import annotations
from dataclasses import dataclass
import gzip
import bz2
import lzma
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time
import unicodedata

from .local_ai import Cancelled

NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.+-]{0,79}$')
MAN_ROOTS = (Path('/usr/share/man'), Path('/usr/local/share/man'))
MAX_MAN_BYTES = 192 * 1024
MAX_EXCERPT = 4200
# Names, not task-to-answer rules. Documentation for these comes from bash(1).
BUILTINS = frozenset('alias bg bind break builtin cd command compgen complete continue '
    'declare dirs disown echo enable eval exec exit export false fc fg getopts hash help '
    'history jobs kill let local logout mapfile popd printf pushd pwd read readarray '
    'readonly return set shift shopt source test times trap true type typeset ulimit '
    'umask unalias unset wait'.split())


def plain(value: str, limit: int = MAX_EXCERPT) -> str:
    """Plain GTK/model text; retain newlines, remove controls/bidi/overstrikes."""
    value = re.sub(r'.\x08', '', value)
    value = ''.join(c for c in value if c in '\n\t' or not unicodedata.category(c).startswith('C'))
    return value[:limit]


def manual_text(value: str) -> str:
    """Conservative roff text extraction. Crucially, NEVER interpret .sy/.pso/.so."""
    lines = []
    for line in value.splitlines():
        if line.startswith(('.\\"', "'\\\"")):
            continue
        if line.startswith(('.', "'")):
            macro, _, rest = line[1:].partition(' ')
            if macro in {'so', 'sy', 'pso', 'open', 'opena', 'write', 'de', 'am', 'if', 'ie', 'el'}:
                continue
            if macro in {'SH', 'SS', 'Sh', 'Ss'}:
                line = '\n' + rest.strip('"') + '\n'
            elif macro in {'B', 'I', 'BI', 'BR', 'IB', 'IR', 'RB', 'RI', 'Nm', 'Nd', 'Fl', 'Ar', 'Pa', 'Li', 'Op'}:
                line = rest.replace('"', '')
            elif macro in {'TH', 'Dd', 'Dt', 'Os', 'PP', 'P', 'TP', 'IP', 'RS', 'RE', 'sp', 'br', 'nf', 'fi'}:
                line = ''
            else:
                # Other formatting commands are not useful evidence.
                continue
        line = re.sub(r'\\f(?:\[[^\]]*\]|\([^\s]{2}|.)', '', line)
        line = re.sub(r'\\s(?:[+-]?\d+|\[[^\]]*\])', '', line)
        for old, new in ((r'\-', '-'), (r'\(aq', "'"), (r'\(dq', '"'), (r'\(em', '—'),
                         (r'\(en', '-'), (r'\&', ''), (r'\e', '\\'), (r'\~', ' ')):
            line = line.replace(old, new)
        lines.append(line)
    return plain('\n'.join(lines), MAX_MAN_BYTES)


def excerpt(text: str, question: str, limit: int = MAX_EXCERPT) -> str:
    """Keep NAME/SYNOPSIS and a few relevant passages, not the whole manual."""
    if len(text) <= limit:
        return text
    head = text[:1700]
    words = {w.casefold() for w in re.findall(r'[\w+-]{3,40}', question)}
    passages = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if words.intersection(re.findall(r'[\w+-]{3,40}', line.casefold())):
            chunk = '\n'.join(lines[max(0, i-1):i+4])
            if chunk and chunk not in head and chunk not in passages:
                passages.append(chunk[:650])
                if sum(map(len, passages)) >= limit - len(head) - 100:
                    break
    return (head + '\n[…]\n' + '\n[…]\n'.join(passages))[:limit]


@dataclass(frozen=True)
class Evidence:
    command: str
    available: bool
    kind: str
    manual: str = ''
    text: str = ''

    def payload(self) -> dict:
        # No executable path, directory listing or absolute user paths.
        return {'command': self.command, 'available': self.available, 'kind': self.kind,
                'manual': self.manual, 'excerpt': self.text,
                'limits': 'Availability and documentation only; no program or argument was test-executed.'}

    def description(self) -> str:
        available = 'Bash-Builtin' if self.kind == 'builtin' else ('im Suchpfad gefunden' if self.available else 'nicht im Suchpfad gefunden')
        doc = f'Handbuch {self.manual} gelesen' if self.manual else 'kein lokales Handbuch gefunden'
        return f'{self.command}: {available}; {doc}.'


class CapabilityReader:
    def __init__(self, roots=None):
        self.roots = tuple(Path(p) for p in (MAN_ROOTS if roots is None else roots))
        self._index = (0.0, '', ())

    @staticmethod
    def check(cancelled):
        if cancelled.is_set():
            raise Cancelled('Anfrage abgebrochen.')

    def names(self, cancelled: threading.Event) -> tuple[str, ...]:
        path = os.environ.get('PATH', '')
        now = time.monotonic()
        if self._index[0] > now and self._index[1] == path:
            return self._index[2]
        names = set(BUILTINS)
        deadline = now + 1.5
        for folder in dict.fromkeys(path.split(os.pathsep)):
            self.check(cancelled)
            # Do not traverse implicit/relative project directories for inventory.
            if not os.path.isabs(folder):
                continue
            try:
                with os.scandir(folder) as files:
                    for count, item in enumerate(files):
                        self.check(cancelled)
                        if count >= 16000 or len(names) >= 16000 or time.monotonic() > deadline:
                            break
                        if NAME.fullmatch(item.name) and item.is_file() and os.access(item.path, os.X_OK):
                            names.add(item.name)
            except OSError:
                continue
            if time.monotonic() > deadline:
                break
        result = tuple(sorted(names))
        self._index = (now + 45, path, result)
        return result

    def hints(self, question: str, cancelled: threading.Event) -> dict:
        names = self.names(cancelled)
        words = set(re.findall(r'[a-z0-9_.+-]{2,80}', question.casefold()))
        mentioned = [n for n in names if n.casefold() in words]
        # A compact sample helps with unfamiliar CLIs; this is not an allowlist.
        # Never label the rest of PATH missing merely because it is not in here.
        sample = list(dict.fromkeys(mentioned + list(names)))[:350]
        return {'mentioned_installed_names': mentioned[:40], 'installed_name_sample': sample,
                'total_indexed': len(names), 'sample_is_incomplete': True}

    def _read_manual(self, topic: str, question: str, cancelled: threading.Event):
        if not NAME.fullmatch(topic):
            return '', ''
        for root in self.roots:
            for section in ('1', '8'):
                for suffix in ('', '.gz', '.xz', '.bz2'):
                    self.check(cancelled)
                    candidate = root / ('man' + section) / (topic + '.' + section + suffix)
                    try:
                        resolved = candidate.resolve()
                        if not resolved.is_relative_to(root.resolve()):
                            continue
                        info = resolved.stat()
                        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * MAX_MAN_BYTES:
                            continue
                        opener = {'.gz': gzip.open, '.xz': lzma.open, '.bz2': bz2.open}.get(suffix, open)
                        with opener(resolved, 'rb') as stream:
                            raw = stream.read(MAX_MAN_BYTES + 1)
                        self.check(cancelled)
                        # A long manual is capped, not silently loaded in full.
                        text = manual_text(raw[:MAX_MAN_BYTES].decode('utf-8', errors='replace')).strip()
                        if len(text) >= 20:
                            return f'{topic}({section})', excerpt(text, question)
                    except (OSError, EOFError, ValueError, RuntimeError, lzma.LZMAError):
                        continue
        return '', ''

    def inspect(self, command: str, topic: str, question: str, cancelled: threading.Event) -> Evidence:
        self.check(cancelled)
        if not NAME.fullmatch(command) or not NAME.fullmatch(topic):
            raise ValueError('Ungültiger Befehls-/Handbuchname.')
        if topic != command and not topic.startswith(command + '-'):
            raise ValueError('Handbuch gehört nicht zum vorgeschlagenen Befehl.')
        builtin = command in BUILTINS
        # which() only checks for executable files. It does NOT run the tool.
        available = builtin or shutil.which(command) is not None
        manual, text = self._read_manual(topic, question, cancelled)
        if not text and topic != command:
            manual, text = self._read_manual(command, question + ' ' + topic, cancelled)
        if not text and builtin:
            manual, text = self._read_manual('bash', command + ' ' + question, cancelled)
        return Evidence(command, available, 'builtin' if builtin else 'program', manual, text)
