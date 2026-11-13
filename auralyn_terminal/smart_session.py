"""Execute a reviewed action in its OWN fresh PTY, then enter normal Auralyn Bash.

Only an action ID crosses the GUI/process boundary. No `shell=True`, eval,
model-written command, terminal pasting, sudo proxy, password interception or
automatic apt yes. Ordinary commands use inherited TTY input/output.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Callable

from .smart_catalog import Entry, get_action

ROOT = Path(__file__).resolve().parent.parent
TRUSTED_DIRS = ('/usr/bin', '/bin', '/usr/sbin', '/sbin')


def executable_path(name: str) -> str:
    # No current/project directory, aliases or arbitrary PATH entries.
    if not name or '/' in name or name.startswith('-'):
        raise ValueError('Ungültiger Programmname in der Aktion.')
    for directory in TRUSTED_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(f'„{name}“ ist in den System-Befehlsverzeichnissen nicht installiert.')


def resolve_step(argv: tuple[str, ...], resolver: Callable[[str], str] = executable_path) -> list[str]:
    if not argv:
        raise ValueError('Leere Aktion.')
    result = [resolver(argv[0]), *argv[1:]]
    if argv[0] == 'sudo':
        if len(argv) < 2 or argv[1].startswith('-'):
            raise ValueError('Nicht erlaubte sudo-Aktion.')
        result[1] = resolver(argv[1])
    return result


def command_environment(environ: dict | None = None) -> dict:
    result = dict(os.environ if environ is None else environ)
    for key in list(result):
        if key.startswith('AURALYN_') or key in ('BASH_ENV', 'ENV', 'PYTHONPATH', 'PYTHONHOME'):
            result.pop(key, None)
    result['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    return result


def execute(ident: str, *, runner=None, resolver=None,
            interrupted: Callable[[], bool] | None = None, environ: dict | None = None) -> int:
    action = get_action(ident)
    if action is None:
        raise ValueError('Unbekannte oder nicht ausführbare Smart-Search-Aktion.')
    run = runner or subprocess.run
    resolve = resolver or executable_path
    was_interrupted = interrupted or (lambda: False)
    # Validate all executables BEFORE any step is started.
    commands = [resolve_step(step, resolve) for step in action.steps]
    env = command_environment(environ)
    for argv in commands:
        if was_interrupted():
            return 130
        result = run(argv, env=env, check=False, restore_signals=True)
        code = result.returncode
        if was_interrupted():
            return 130
        if code:
            return code if code > 0 else 128 - code
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action_id')
    args = parser.parse_args(argv)
    action = get_action(args.action_id)
    if action is None:
        parser.error('Unbekannte oder nicht ausführbare Aktion.')
    print('\nAuralyn Smart Search · ' + action.title)
    print('$ ' + action.command, flush=True)
    if action.warning:
        print(action.warning, flush=True)
    cancelled = False
    def on_interrupt(_signal, _frame):
        nonlocal cancelled
        cancelled = True
    previous = signal.signal(signal.SIGINT, on_interrupt)
    try:
        code = execute(action.id, interrupted=lambda: cancelled)
    except (OSError, ValueError) as exc:
        print('\nNicht ausgeführt: ' + str(exc), file=sys.stderr, flush=True)
        code = 127
    except KeyboardInterrupt:
        code = 130
    finally:
        signal.signal(signal.SIGINT, previous)
    print(f'\n[Smart Search beendet · Exit-Code {code}]', flush=True)
    print('Dieser Tab ist jetzt wieder ein normales Bash-Terminal.\n', flush=True)
    env = dict(os.environ)
    env.pop('BASH_ENV', None)
    try:
        os.execve('/bin/bash', ['/bin/bash', '--rcfile', str(ROOT / 'shell/bashrc.bash'), '-i'], env)
    except OSError as exc:
        print('Bash konnte nicht gestartet werden: ' + str(exc), file=sys.stderr)
        return 127


if __name__ == '__main__':
    raise SystemExit(main())
