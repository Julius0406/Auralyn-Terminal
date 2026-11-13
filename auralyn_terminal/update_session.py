"""Fixed update workflow in a NEW user PTY, never an elevated interactive shell.

sudo -k is combined with each command; no reusable authentication timestamp is
intended. sudo -K also removes pre-existing user timestamps before/after the run
and on handled interruptions. The password is only supplied to those two sudo
processes by a private askpass broker. It is not part of the shell environment.
Automatic package confirmation is explicitly scoped to this fixed workflow:
APT full-upgrade receives -y; Flatpak update receives --assumeyes. No terminal
output parsing, synthetic keypresses, yes pipe or global APT configuration.
Special configuration/authentication prompts stay interactive. No sudoers edits,
NOPASSWD, force/unauthenticated options, lock removal or reboots.
"""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from .smart_session import executable_path, command_environment
from .update_auth import PasswordBroker, wipe, SOCKET_ENV, BROKER_PID_ENV
from .update_secrets import UpdateSecretStore, SecretError

ROOT = Path(__file__).resolve().parent.parent
DISPLAY_COMMANDS = ('sudo apt update', 'sudo apt full-upgrade', 'flatpak update')


def display_commands(assume_yes: bool = False) -> tuple[str, str, str]:
    """User-facing preview of the exact fixed workflow, not executable shell text."""
    if assume_yes:
        return ('sudo apt update', 'sudo apt full-upgrade -y',
                'flatpak update --assumeyes')
    return DISPLAY_COMMANDS


def confirmation_notice(assume_yes: bool) -> str:
    """Announce the selected mode without impersonating a package-manager prompt."""
    if assume_yes:
        return ('Automatisches Ja: EIN · nur dieser Update-Button.\n'
                'APT (-y) und Flatpak (--assumeyes) bestätigen Paketfragen selbst, '
                'unabhängig von Deutsch oder Englisch.\n'
                'Achtung: full-upgrade kann dabei auch Pakete entfernen.\n'
                'Konfigurationsfragen und separate Berechtigungsabfragen können '
                'weiterhin eine Eingabe verlangen. Kein automatischer Neustart.\n')
    return ('Automatisches Ja: AUS · Paketänderungen bitte selbst bestätigen.\n'
            'full-upgrade kann Pakete entfernen. Kein automatischer Neustart.\n')


def update_environment(environ=None):
    env = command_environment(environ)
    for key in list(env):
        if (key.startswith(('SUDO_', 'LD_', 'DYLD_')) or key in (
            'APT_CONFIG', 'DEBIAN_FRONTEND', 'DEBIAN_PRIORITY', 'SSH_ASKPASS',
            'BASH_ENV', 'ENV', 'PYTHONPATH', 'PYTHONHOME', 'GCONV_PATH',
            'GIO_EXTRA_MODULES', 'GIO_MODULE_DIR', 'GIT_ASKPASS',
            'LIBSECRET_DEBUG', 'G_MESSAGES_DEBUG')):
            env.pop(key, None)
    env['PATH'] = '/usr/sbin:/usr/bin:/sbin:/bin'
    return env


def shell_environment(environ=None):
    env = dict(os.environ if environ is None else environ)
    for key in list(env):
        if key in (SOCKET_ENV, BROKER_PID_ENV, 'SUDO_ASKPASS', 'BASH_ENV', 'ENV') or key.startswith('AURALYN_UPDATE_'):
            env.pop(key, None)
    return env


def supports_askpass(sudo: str, env: dict, runner=subprocess.run) -> bool:
    try:
        result = runner([sudo, '--help'], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**env, 'LC_ALL': 'C'}, timeout=5, check=False)
        return result.returncode == 0 and b'--askpass' in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def revoke_sudo(sudo: str, env: dict, runner=subprocess.run) -> bool:
    try:
        result = runner([sudo, '-K'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, timeout=8, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class UpdateLock:
    """One updater per login UID, even if multiple Auralyn windows exist."""
    def __init__(self):
        self.fd = None

    def __enter__(self):
        # Persistent EMPTY lock is metadata, never contains a password.
        directory = Path('/tmp') / f'auralyn-update-{os.getuid()}'
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError('Unsicherer Update-Sperrordner. Kein Update gestartet.')
        self.fd = os.open(directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        info = os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError('Unsichere Update-Sperrdatei. Kein Update gestartet.')
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError('In einem anderen Auralyn-Fenster läuft bereits ein Update. Bitte warten.') from None
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


@dataclass(frozen=True)
class UpdateResult:
    code: int
    completed: int
    revoked: bool
    skipped_flatpak: bool = False


class UpdateRunner:
    def __init__(self, *, saved_password: bool, assume_yes: bool = False, resolver=executable_path,
                 store_factory=UpdateSecretStore, run=subprocess.run,
                 popen=subprocess.Popen, broker_factory=PasswordBroker,
                 emit=None, environ=None):
        self.saved_password = saved_password
        # Only explicit True enables the native confirmation flags; arbitrary
        # strings from callers never become argv or a global environment policy.
        self.assume_yes = assume_yes is True
        self.resolve = resolver
        self.store_factory = store_factory
        self.run = run
        self.popen = popen
        self.broker_factory = broker_factory
        self.emit = emit or (lambda text: print(text, flush=True))
        self.env = update_environment(environ)
        self.cancel_signal = 0
        self.child = None

    def interrupt(self, signum):
        self.cancel_signal = self.cancel_signal or signum
        # Ctrl+C/HUP often also goes to the foreground group, but a signal sent
        # directly to this wrapper must not leave sudo's package manager behind.
        if self.child is not None and self.child.poll() is None:
            try:
                self.child.send_signal(signum)
            except OSError:
                pass

    def _command(self, argv, broker=None):
        env = self.env
        if broker is not None:
            broker.prepare()
            env = broker.environment(env, str(ROOT / 'update_askpass.py'))
        try:
            self.child = self.popen(argv, env=env, cwd=str(Path.home()),
                restore_signals=True, close_fds=True)
            if broker is not None:
                broker.arm(self.child.pid)
            if self.cancel_signal:
                self.interrupt(self.cancel_signal)
            code = self.child.wait()
            return 128 - code if code < 0 else code
        finally:
            if broker is not None:
                broker.disarm()
            self.child = None

    def execute(self) -> UpdateResult:
        completed = 0
        skipped = False
        commands = display_commands(self.assume_yes)
        code = 1
        broker = None
        secret = bytearray()
        sudo = self.resolve('sudo')
        try:
            # Remove any earlier timestamps as well, including other terminals.
            if not revoke_sudo(sudo, self.env, self.run):
                raise RuntimeError('sudo-Anmeldung konnte nicht zurückgesetzt werden. Sicherheitshalber kein Update gestartet.')
            apt = self.resolve('apt')
            try:
                flatpak = self.resolve('flatpak')
            except FileNotFoundError:
                flatpak = None
                skipped = True
            if self.saved_password and not self.cancel_signal:
                if not supports_askpass(sudo, self.env, self.run):
                    raise RuntimeError('Dein sudo unterstützt --askpass nicht. In den Einstellungen „Passwort für Update-Button verwenden“ ausschalten; dann ist die normale Passwortabfrage möglich. Keine sudo-Konfiguration wurde verändert.')
                secret = self.store_factory().lookup()
                if self.cancel_signal:
                    code = 128 + self.cancel_signal
                else:
                    broker = self.broker_factory(secret)
            wipe(secret)
            if not self.cancel_signal:
                for index, verb in enumerate(('update', 'full-upgrade'), start=1):
                    if self.cancel_signal:
                        break
                    self.emit(f'\n[{index}/3] $ {commands[index - 1]}')
                    argv = [sudo, '-k']
                    if broker is not None:
                        argv.append('-A')
                    argv += ['--', apt, verb]
                    if self.assume_yes and verb == 'full-upgrade':
                        argv.append('-y')
                    code = self._command(argv, broker)
                    if code or self.cancel_signal:
                        if broker is not None and code:
                            self.emit('Schritt nicht erfolgreich. Bei einem Passwortfehler bitte den gespeicherten Eintrag prüfen. Es wird nicht automatisch erneut versucht.')
                        break
                    completed += 1
                else:
                    # Release credentials/broker BEFORE unprivileged Flatpak.
                    if broker is not None:
                        broker.close()
                        broker = None
                    if not revoke_sudo(sudo, self.env, self.run):
                        raise RuntimeError('sudo-Anmeldung konnte nicht gelöscht werden. Bitte im Terminal sudo -K ausführen.')
                    if flatpak is None:
                        self.emit('\n[3/3] flatpak update übersprungen: Flatpak ist nicht installiert. Es wurde nicht nachinstalliert.')
                        code = 0
                    elif not self.cancel_signal:
                        self.emit(f'\n[3/3] $ {commands[2]}  (als normaler Benutzer)')
                        argv = [flatpak, 'update']
                        if self.assume_yes:
                            argv.append('--assumeyes')
                        code = self._command(argv)
                        if not code and not self.cancel_signal:
                            completed += 1
            if self.cancel_signal:
                code = 128 + self.cancel_signal
        except (OSError, RuntimeError, ValueError) as exc:
            self.emit('\nUpdate gestoppt: ' + str(exc))
            code = 1
        finally:
            wipe(secret)
            try:
                if broker is not None:
                    broker.close()
            finally:
                revoked = revoke_sudo(sudo, self.env, self.run)
                if revoked:
                    self.emit('\n[sudo-Anmeldung gelöscht · normale Passwortabfrage wieder aktiv]')
                else:
                    self.emit('\n[WARNUNG: sudo-Anmeldung NICHT gelöscht. Bitte sofort sudo -K ausführen.]')
        return UpdateResult(code if revoked else 1, completed, revoked, skipped)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Auralyn: fester Systemupdate-Ablauf, keine freien Befehle.')
    parser.add_argument('--saved-password', action='store_true')
    parser.add_argument('--assume-yes', action='store_true',
                        help='Paketfragen nur in diesem Update-Ablauf automatisch bestätigen.')
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        print('Auralyn bitte als normalen Benutzer starten, nicht als root.', file=sys.stderr)
        return 1
    if not os.isatty(0):
        print('Der Update-Button benötigt einen eigenen Terminal-Tab.', file=sys.stderr)
        return 1
    print('\nAuralyn · Systemupdate\n' + '\n'.join('$ ' + x for x in display_commands(args.assume_yes)), flush=True)
    print('\n' + confirmation_notice(args.assume_yes), flush=True)
    runner = UpdateRunner(saved_password=args.saved_password, assume_yes=args.assume_yes)
    previous = {s: signal.signal(s, lambda signum, _frame: runner.interrupt(signum))
                for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        with UpdateLock():
            result = runner.execute()
    except (OSError, RuntimeError) as exc:
        print('Update nicht gestartet: ' + str(exc), flush=True)
        result = UpdateResult(1, 0, False)
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
    if result.code == 0:
        suffix = ' · Flatpak nicht installiert' if result.skipped_flatpak else ''
        print(f'\n[Update beendet · {result.completed} Schritte erfolgreich{suffix}]', flush=True)
    else:
        print(f'\n[Update gestoppt · Exit-Code {result.code} · {result.completed} Schritte erfolgreich]', flush=True)
    if runner.cancel_signal in (signal.SIGHUP, signal.SIGTERM):
        return result.code
    print('Dieser Tab ist jetzt wieder eine normale Benutzer-Bash.\n', flush=True)
    try:
        os.execve('/bin/bash', ['/bin/bash', '--rcfile', str(ROOT / 'shell/bashrc.bash'), '-i'], shell_environment())
    except OSError:
        print('Bash konnte nicht gestartet werden.', file=sys.stderr)
        return 127


if __name__ == '__main__':
    raise SystemExit(main())
