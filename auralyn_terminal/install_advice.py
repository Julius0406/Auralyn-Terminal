"""Read-only APT proposal verification. Never installs or runs discovered tools.

An existing APT candidate is not a proof of binary ownership or a guarantee the
installation is compatible. Web evidence + local package metadata are shown;
all newly proposed installation commands are copy-only, with normal apt review.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

from .capabilities import NAME, plain
from .local_ai import AIError, Cancelled

PACKAGE = re.compile(r'^[a-z0-9][a-z0-9+.-]{0,99}$')
ALLOWED = {'/usr/bin/apt-cache', '/usr/bin/dpkg-query'}


def read_metadata(argv, cancelled):
    if not argv or argv[0] not in ALLOWED:
        raise ValueError('Nur feste lokale Paket-Metadatenprogramme sind erlaubt.')
    if cancelled.is_set():
        raise Cancelled('Anfrage abgebrochen.')
    if not os.path.isfile(argv[0]):
        return ''
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, cwd='/', start_new_session=True,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/nonexistent'})
    parts, count, deadline = [], 0, time.monotonic() + 4
    poll = selectors.DefaultSelector()
    try:
        os.set_blocking(proc.stdout.fileno(), False)
        poll.register(proc.stdout, selectors.EVENT_READ)
        while count < 128000 and time.monotonic() < deadline:
            if cancelled.is_set():
                raise Cancelled('Anfrage abgebrochen.')
            events = poll.select(.05)
            if events:
                chunk = os.read(proc.stdout.fileno(), min(8192, 128000-count))
                if not chunk:
                    break
                parts.append(chunk)
                count += len(chunk)
            elif proc.poll() is not None:
                # Drain the finite stdout pipe on the next readability event.
                continue
        return plain(b''.join(parts).decode('utf-8', errors='replace'), 128000)
    finally:
        poll.close()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()
        proc.stdout.close()


@dataclass(frozen=True)
class PackageInfo:
    name: str
    candidate: str = ''
    installed: str = ''
    description: str = ''

    def payload(self):
        return dict(name=self.name, candidate=self.candidate, installed=self.installed,
                    description=self.description,
                    limitation='Local APT metadata, not an installation or a compatibility proof.')


@dataclass(frozen=True)
class InstallAdvice:
    command: str = ''
    note: str = ''
    packages: tuple[PackageInfo, ...] = ()
    source_ids: tuple[str, ...] = ()


class PackageReader:
    def __init__(self, run=None):
        self.run = run or read_metadata

    def package(self, name, cancelled):
        if not PACKAGE.fullmatch(name):
            raise ValueError('Ungültiger Paketname.')
        value = self.run(['/usr/bin/apt-cache', 'policy', '--', name], cancelled)
        candidate = re.search(r'^\s*Candidate:\s*(\S+)', value, re.M)
        installed = re.search(r'^\s*Installed:\s*(\S+)', value, re.M)
        c = candidate.group(1) if candidate else ''
        i = installed.group(1) if installed else ''
        if c in ('(none)', 'none'):
            c = ''
        if i in ('(none)', 'none'):
            i = ''
        desc = ''
        if c:
            detail = self.run(['/usr/bin/apt-cache', 'show', '--no-all-versions', '--', name], cancelled)
            m = re.search(r'^Description(?:-en)?:\s*(.+)', detail, re.M)
            desc = m.group(1)[:240] if m else ''
        return PackageInfo(name, c[:100], i[:100], desc)

    def nvidia_state(self, cancelled):
        # Version only; do not read serials, process names, GPU UUIDs or files in
        # the user's home. No nvidia-smi/modprobe invocation during a search.
        version = ''
        for file in ('/sys/module/nvidia/version', '/proc/driver/nvidia/version'):
            try:
                with open(file, encoding='utf-8', errors='replace') as stream:
                    text = stream.read(2048)
                match = re.search(r'\b(\d{3}\.\d+(?:\.\d+)?)\b', text)
                if match:
                    version = match.group(1)
                    break
            except OSError:
                pass
        raw = self.run(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n',
                        'nvidia-driver-*', 'nvidia-utils*', 'libnvidia-compute*', 'nvidia-smi'], cancelled)
        entries = []
        for line in raw.splitlines():
            cols = line.split('\t')
            if len(cols) == 3 and cols[2].startswith('ii'):
                name = cols[0].split(':')[0]
                if PACKAGE.fullmatch(name):
                    entries.append((name, cols[1][:100]))
        server = any('-server' in name and name.startswith(('nvidia-driver-', 'libnvidia-compute-')) for name, _ in entries)
        variants = {('server' if '-server' in name else 'desktop') for name, _ in entries
                    if name.startswith(('nvidia-driver-', 'libnvidia-compute-'))}
        return {'loaded_version': version, 'server': server, 'ambiguous': len(variants) > 1,
                'packages': entries[:30]}

    def advise(self, command, candidates, sources, cancelled, *, distro=None):
        if not NAME.fullmatch(command) or not isinstance(candidates, list) or len(candidates) > 3:
            raise AIError('Ungültiger Installationsvorschlag.')
        for candidate in candidates:
            if not isinstance(candidate, str) or not PACKAGE.fullmatch(candidate):
                raise AIError('Ungültiger Paketname in der Installationsrecherche.')
        # The model cannot mint source IDs/URLs or pull a package from nothing.
        supported = [name for name in dict.fromkeys(candidates)
                     if any(re.search(r'(?<![a-z0-9+.-])' + re.escape(name) + r'(?![a-z0-9+.-])',
                                      s.title + '\n' + s.text, re.I) for s in sources)]
        if distro and distro.get('id') not in ('ubuntu', 'debian'):
            return InstallAdvice(note='APT-Installation passt nicht sicher zu dieser Distribution. Quellenanleitung prüfen.')
        if command == 'nvidia-smi':
            return self._nvidia(supported, sources, cancelled)
        if not supported:
            return InstallAdvice(note='Kein konkretes APT-Paket in den Webbelegen bestätigt. Installationsquelle unten prüfen; kein Downloadbefehl geraten.')
        checked = tuple(self.package(name, cancelled) for name in supported)
        # Packages are alternatives, not a set to blindly install together.
        available = [p for p in checked if p.candidate]
        if not available:
            return InstallAdvice(note='In den aktuellen lokalen APT-Paketlisten kein passender Kandidat. '
                                 'Die Listen können veraltet sein. Kein Repository oder Installationsskript wird automatisch hinzugefügt.', packages=checked)
        chosen = available[0]
        refs = tuple(s.id for s in sources if chosen.name in s.text or chosen.name in s.title)
        return InstallAdvice('sudo apt install ' + chosen.name,
                             f'Web-Anleitung nennt {chosen.name}; lokaler APT-Kandidat: {chosen.candidate}. '
                             'Installationsvorschlag, kein Funktionstest. Nur kopieren, APT-Änderungsliste prüfen. '
                             'Nach der Installation erneut suchen.', checked, refs)

    def _nvidia(self, supported, sources, cancelled):
        state = self.nvidia_state(cancelled)
        version = state['loaded_version']
        if not version or state['ambiguous']:
            return InstallAdvice(note='nvidia-smi fehlt. Laufende NVIDIA-Treiberversion/Variante nicht eindeutig ermittelt. '
                                 'Keinen beliebigen nvidia-utils- oder Treiberzweig installieren. Erst den vorhandenen Treiber klären.')
        branch = version.split('.')[0]
        # Ubuntu packages may be branch-suffixed or use NVIDIA's newer unversioned
        # names. Never assume the newest package is compatible with this driver.
        matching_name = 'nvidia-utils-' + branch + ('-server' if state['server'] else '')
        names = list(dict.fromkeys([matching_name] + supported + ['nvidia-utils', 'nvidia-smi']))[:6]
        infos = []
        for name in names:
            if not (name == matching_name or name in ('nvidia-utils', 'nvidia-smi')):
                continue
            info = self.package(name, cancelled)
            infos.append(info)
            upstream = info.candidate.split(':')[-1].split('-')[0]
            if upstream != version:
                continue
            # Require some actual installation-package web evidence; a bare
            # occurrence of nvidia-smi in a command manual isn't enough.
            documented = any(re.search(r'\bnvidia-utils(?:-[0-9]+)?\b|\bapt(?:-get)?\s+install\s+nvidia-smi\b',
                                        s.text, re.I) for s in sources)
            if documented:
                return InstallAdvice('sudo apt install ' + name,
                                     f'Laufender NVIDIA-Treiber: {version}; passender lokaler APT-Kandidat: {info.candidate}. '
                                     'Kein Treiberzweigwechsel. Nur kopieren und APT-Änderungsliste prüfen; danach erneut suchen.',
                                     tuple(infos), tuple(s.id for s in sources if 'nvidia' in s.text.lower()))
        return InstallAdvice(note=f'nvidia-smi fehlt; laufender NVIDIA-Treiber: {version}. '
                             'Kein exakt passendes Utilities-Paket in den lokalen APT-Listen bestätigt. '
                             'Ein neueres/anderes Paket kann einen Treiberwechsel auslösen; deshalb kein blinder Installationsbefehl.',
                             packages=tuple(infos))


def documented_manager_advice(proposed, sources):
    """Copy-only vendor instructions for a few normal user package managers.

    NOT an allowlist to execute commands. The entire proposed command must be
    literally present in a fetched excerpt. No repo changes, scripts or URLs.
    """
    import shlex
    import shutil
    from .command_ai import command_tools
    if not isinstance(proposed, str) or not proposed.strip():
        return InstallAdvice()
    try:
        tools = command_tools(proposed)
        words = shlex.split(proposed)
    except (AIError, ValueError):
        return InstallAdvice(note='Zusätzliche Installationsvorlage nicht übernommen: kein einfacher Paketmanager-Aufruf.')
    argv = words[1:] if words[0] == 'sudo' else words
    manager = argv[0]
    exact = {
        'snap': ('install',), 'flatpak': ('install', 'flathub'), 'pipx': ('install',),
        'cargo': ('install',), 'uv': ('tool', 'install')}
    prefix = exact.get(manager)
    if not prefix or tuple(argv[1:1+len(prefix)]) != prefix:
        return InstallAdvice(note='Kein unterstützter einfacher Installationsweg. Originalquelle prüfen.')
    operands = argv[1+len(prefix):]
    classic = manager == 'snap' and '--classic' in operands
    operands = [p for p in operands if not (classic and p=='--classic')]
    if len(operands)!=1 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+=-]{0,120}',operands[0]):
        return InstallAdvice(note='Komplexer Paket-/Repository-Aufruf nicht übernommen. Quelle und Installationsart klären.')
    if words[0]=='sudo' and manager not in ('snap','flatpak'):
        return InstallAdvice(note='Keine globale sudo-Installation in einer Benutzer-Paketumgebung vorgeschlagen.')
    normalised = ' '.join(proposed.split())
    refs = tuple(s.id for s in sources if normalised in ' '.join(s.text.split()))
    if not refs:
        return InstallAdvice(note='Die zusätzliche Installationszeile ist nicht wörtlich in den abgerufenen Quellen belegt.')
    if any(shutil.which(tool) is None for tool in tools):
        return InstallAdvice(note=f'Installationsweg in der Quelle gefunden, aber der Paketmanager {manager} fehlt. '
                             'Erst dessen offizielle Einrichtung prüfen; keine automatische Installationskette.')
    return InstallAdvice(normalised, 'Installationszeile aus der Webquelle; Paketmanager im Suchpfad gefunden. '
                         'Paketname/Publisher und Kompatibilität NICHT in diesem Store geprüft. Nur kopieren und prüfen. '
                         + ('Snap --classic gewährt weitreichenden Systemzugriff. ' if classic else '')
                         + 'Danach erneut suchen.', source_ids=refs)
