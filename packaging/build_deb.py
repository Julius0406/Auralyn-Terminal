#!/usr/bin/python3
"""Build a distro-native, architecture-independent package without downloading.

Run with an ordinary user: python3 packaging/build_deb.py
No installation, root privileges, network access, or maintainer scripts needed.
"""
from __future__ import annotations
import argparse
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
FILE_VERSION = '1.0.0'
DEB_VERSION = '1:1.0.0'


def copy_file(source: Path, target: Path, mode=0o644):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(mode)


def build(output: Path):
    tool = shutil.which('dpkg-deb')
    if tool is None:
        raise SystemExit('dpkg-deb fehlt. Benötigt wird das Paket dpkg.')
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f'auralyn-terminal_{FILE_VERSION}_all.deb'
    with tempfile.TemporaryDirectory(prefix='auralyn-package-') as temp:
        root = Path(temp) / 'package'
        app = root / 'usr/share/auralyn-terminal'
        for dirname in ('auralyn_terminal', 'shell'):
            for source in sorted((ROOT / dirname).rglob('*')):
                if source.is_file() and '__pycache__' not in source.parts and source.suffix != '.pyc':
                    copy_file(source, app / source.relative_to(ROOT))
        copy_file(ROOT / 'launcher.py', app / 'launcher.py')
        copy_file(ROOT / 'program_launcher.py', app / 'program_launcher.py')
        copy_file(ROOT / 'smart_launcher.py', app / 'smart_launcher.py')
        copy_file(ROOT / 'update_launcher.py', app / 'update_launcher.py')
        copy_file(ROOT / 'update_askpass.py', app / 'update_askpass.py', mode=0o755)
        copy_file(ROOT / 'assets/auralyn-terminal.svg', root / 'usr/share/icons/hicolor/scalable/apps/auralyn-terminal.svg')
        copy_file(ROOT / 'packaging/de.julius.AuralynTerminal.desktop', root / 'usr/share/applications/de.julius.AuralynTerminal.desktop')
        for filename in ('README.md', 'LICENSE', 'TESTBERICHT.md', 'CHANGELOG.md'):
            source = ROOT / filename
            if source.exists():
                copy_file(source, root / 'usr/share/doc/auralyn-terminal' / filename)
        for source in sorted((ROOT / 'docs').glob('*.md')):
            copy_file(source, root / 'usr/share/doc/auralyn-terminal/docs' / source.name)
        launcher = root / 'usr/bin/auralyn-terminal'
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text('#!/bin/sh\nexec /usr/bin/python3 -I /usr/share/auralyn-terminal/launcher.py "$@"\n')
        launcher.chmod(0o755)
        meta = root / 'DEBIAN'
        meta.mkdir()
        size = math.ceil(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) / 1024)
        (meta / 'control').write_text(f'''Package: auralyn-terminal
Version: {DEB_VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: Auralyn Terminal (local project)
Installed-Size: {size}
Depends: ca-certificates, python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-glib-2.0, gir1.2-gtk-3.0, gir1.2-vte-2.91, gir1.2-secret-1, sudo | sudo-rs, bash (>= 4.4), bash-completion
Recommends: man-db, gnome-keyring
Description: Native Bash terminal with scoped Smart Search and local AI support
 Auralyn Terminal uses GTK and VTE for real interactive terminal sessions.
 It provides a compact two- or three-row suggestion popup, PATH discovery,
 installed Bash completions, tabs, and adjustable background transparency.
 Adds run and name-based force-stop commands, with offline command help.
 Smart Search offers reviewed command actions in fresh PTYs, offline help,
 versioned Auralyn product help, and optional local-only Ollama research.
 Opt-in web research reads public documentation before local PATH checks.
 Missing programs get sourced, copy-only installation proposals.
 New model-generated commands are copy-only, never freely executable.
 Dedicated update button for APT and Flatpak with optional Secret Service
 password storage and sudo timestamp cleanup. Optional native yes flags
 confirm package questions only in this workflow. No NOPASSWD rules are added.
 No automatic model downloads. A web API key is optional; inference stays local.
 Known product questions work without a model or an internet connection.
 Three Auralyn-only Faceman commands print repeatedly until Ctrl+C.
 Core desktop processes and normal Bash kill syntax are protected.
 See the test report for tested features and remaining limitations.
''')
        checksums = []
        for path in sorted((root / 'usr').rglob('*')):
            if path.is_file():
                checksums.append(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(root)))
        (meta / 'md5sums').write_text('\n'.join(checksums) + '\n')
        for directory in root.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
        subprocess.run([tool, '--root-owner-group', '-Zxz', '--build', str(root), str(archive)], check=True)
    print(archive)
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    build(parser.parse_args().output.resolve())
