"""Auralyn's explicit run / force-stop actions, executed only after Enter."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Sequence

from .programs import Program, ProgramIndex, display_text
from .processes import ProcessIndex, send_force_stop

RUN_HELP = '''Auralyn run – Programme starten
  run NAME [ARGUMENTE]             Startet ein Programm im Hintergrund.
  run "Name aus dem App-Menü"      Startet den installierten App-Eintrag.
  run --foreground NAME [ARGS]     Interaktiv in diesem Terminal starten.
  run --list                      Erkannte installierte Programme anzeigen.
  run --help                      Diese Hilfe anzeigen.
Nach "run " erscheinen Vorschläge. Tab wählt, H erklärt.
Enter übernimmt die Auswahl; erst das nächste Enter startet das Programm.
App-Menü-Einträge nehmen Dateien/URLs an; für CLI-Optionen den Befehlsnamen nehmen.
'''
KILL_HELP = '''Auralyn kill – laufende Programme sofort beenden
  kill NAME                       Erzwingt das Beenden nach genauem Namen.
  kill "Name [PID 1234]"           Wählt einen eindeutigen Vorschlag aus.
  kill --app NAME                 Explizit nach App-/Prozessname auswählen.
  kill --list                     Beendbare Programme dieses Benutzers anzeigen.
  kill --help                     Diese Hilfe anzeigen.
Achtung: Ungespeicherte Änderungen können verloren gehen!
Mehrere Prozesse derselben Anwendung und ihre Kindprozesse werden beendet.
Mehrdeutige Namen werden nicht geraten. Desktop-Kerndienste und Auralyn sind
von dieser Namensfunktion ausgenommen. Für diese Funktion ist kein sudo nötig.
Die normale Bash-Syntax bleibt erhalten: kill 1234, kill -9 1234, kill %1,
kill -l oder ausdrücklich builtin kill ... (Bash-Handbuch gilt weiterhin).
'''


def current_catalog() -> tuple[ProgramIndex, str, str]:
    return ProgramIndex(), os.environ.get('PATH', os.defpath), os.getcwd()


def launch_desktop(program: Program, arguments: Sequence[str]) -> None:
    """Use the desktop's launcher; do not implement or shell-eval Exec=."""
    if any(arg.startswith('-') for arg in arguments):
        raise ValueError('Bei App-Menü-Namen sind zusätzliche Argumente Dateien/URLs. Für Optionen bitte den ausführbaren Befehlsnamen verwenden.')
    try:
        import gi
        gi.require_version('Gio', '2.0')
        from gi.repository import Gio
        try:
            gi.require_version('GioUnix', '2.0')
            from gi.repository import GioUnix
            app_type = GioUnix.DesktopAppInfo
        except (ValueError, ImportError):
            app_type = Gio.DesktopAppInfo
        app = app_type.new_from_filename(program.path)
        if app is None:
            raise ValueError('Der App-Menü-Eintrag ist nicht mehr verfügbar oder ungültig.')
        uris = [arg if '://' in arg or arg.startswith(('mailto:', 'steam:', 'file:'))
                else Path(arg).expanduser().absolute().as_uri() for arg in arguments]
        if not app.launch_uris(uris, Gio.AppLaunchContext()):
            raise RuntimeError('Der Desktop hat den Start nicht angenommen.')
    except (ImportError, AttributeError) as exc:
        raise RuntimeError('Die GIO-Systembibliothek fehlt. Bitte python3-gi und gir1.2-glib-2.0 installieren.') from exc


def launch_executable(program: Program, arguments: Sequence[str], foreground: bool = False):
    """Exec argv literally, with the shell's current cwd/environment.

    --foreground replaces only this short-lived helper, not the user's Bash.
    Normal launches get their own session and a private, uniquely created log.
    """
    argv = [program.path, *arguments]
    if foreground:
        os.execv(program.path, argv)
        raise AssertionError('execv returned unexpectedly')
    state_home = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    if not state_home.is_absolute():
        state_home = Path.home() / '.local/state'
    logs = state_home / 'auralyn-terminal' / 'runs'
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    if logs.is_symlink() or logs.stat().st_uid != os.getuid():
        raise PermissionError('Der Ausgabeordner gehört nicht deinem Benutzer oder ist ein symbolischer Link.')
    fd, filename = tempfile.mkstemp(prefix='run-', suffix='.log', dir=logs)
    try:
        with os.fdopen(fd, 'ab', buffering=0) as log:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
    except BaseException:
        Path(filename).unlink(missing_ok=True)
        raise
    return child, filename


def run(args: list[str]) -> int:
    if not args or args[0] in ('--help', '-h'):
        print(RUN_HELP, end='')
        return 0
    index, path, cwd = current_catalog()
    if args == ['--list']:
        for program in index.choices(path, cwd):
            print(program.name)
        return 0
    foreground = args[0] in ('--foreground', '-f')
    if foreground:
        args = args[1:]
    if args and args[0] == '--':
        args = args[1:]
    if not args or args[0].startswith('-'):
        raise ValueError('Bitte einen Programmnamen angeben. Hilfe: run --help')
    program = index.resolve(args[0], path, cwd)
    if program is None:
        raise ValueError('Programm nicht gefunden: ' + display_text(args[0]) + '. Nach "run " einen Vorschlag auswählen; Namen mit Leerzeichen in Anführungszeichen setzen.')
    if program.kind == 'desktop':
        if foreground:
            raise ValueError('--foreground braucht den ausführbaren Befehlsnamen, nicht den Namen aus dem App-Menü.')
        launch_desktop(program, args[1:])
        print('Start angefordert: ' + display_text(program.name))
    else:
        child, logfile = launch_executable(program, args[1:], foreground)
        print(f'Gestartet: {display_text(program.name)} (PID {child.pid})')
        print('Ausgabe: ' + display_text(logfile, 400))
    return 0


def kill(args: list[str]) -> int:
    if not args or args[0] in ('--help', '-h'):
        print(KILL_HELP, end='')
        return 0
    index, path, cwd = current_catalog()
    processes = ProcessIndex(apps=index.applications(path, cwd))
    if args == ['--list']:
        for target in processes.targets():
            print(target.name)
        return 0
    if args[0] in ('--app', '--'):
        args = args[1:]
    if len(args) != 1 or not args[0]:
        raise ValueError('Bitte genau einen Programmnamen angeben. Namen mit Leerzeichen in Anführungszeichen setzen. Hilfe: kill --help')
    target = processes.resolve(args[0])
    if target is None:
        raise ValueError('Kein beendbares eigenes Programm mit genau diesem Namen gefunden: ' + display_text(args[0]) + '. Nach "kill " einen aktuellen Vorschlag wählen.')
    sent, skipped = send_force_stop(processes.members(target), processes.excluded)
    print(f'Sofort-Beenden angefordert: {display_text(target.name)} – KILL an {sent} Prozess(e).')
    if skipped:
        print(f'{skipped} Prozess(e) bereits beendet, verändert oder nicht zugänglich.')
    return 0 if sent else 1


def completion_names(action: str, prefix: str) -> list[str]:
    index, path, cwd = current_catalog()
    if action == 'run':
        names = [p.name for p in index.choices(path, cwd)]
    elif action == 'kill':
        names = [t.name for t in ProcessIndex(apps=index.applications(path, cwd)).targets()]
    else:
        return []
    return [n for n in names if n.casefold().startswith(prefix.casefold())]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ('run', 'kill', 'complete'):
        print('Interner Auralyn-Starter. Im Terminal run --help oder kill --help eingeben.', file=sys.stderr)
        return 2
    action = args.pop(0)
    try:
        if action == 'complete':
            if len(args) != 2:
                return 2
            sys.stdout.buffer.write(b''.join(n.encode('utf-8') + b'\0' for n in completion_names(*args)))
            return 0
        informational = not args or args[0] in ('--help', '-h', '--list')
        if os.geteuid() == 0 and not informational:
            raise PermissionError('Auralyn run/kill bitte als normaler Benutzer und ohne sudo ausführen.')
        return run(args) if action == 'run' else kill(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Auralyn {action}: {display_text(str(exc), 700)}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nAbgebrochen.', file=sys.stderr)
        return 130
    except Exception as exc:
        # GLib.Error (e.g. missing DBus service) is not an OSError. Keep the
        # terminal usable and report it instead of raising an Apport traceback.
        print(f'Auralyn {action}: {display_text(str(exc), 700)}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
