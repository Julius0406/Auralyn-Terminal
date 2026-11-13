"""Real fresh-PTY action tests and simulated APT execution (never real updates).

Real subprocesses are limited to pwd, Bash, controlled sleep, and a synthetic
password-reading Python fixture. No administrator authentication is attempted.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import os
import pty
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import Mock, patch

from auralyn_terminal.protocol import SessionIPC
from auralyn_terminal.smart_session import execute, resolve_step, command_environment, executable_path
from auralyn_terminal.smart_catalog import Entry
from auralyn_terminal.terminal_state import is_readline_foreground
from test_shell import BashSession

ROOT = Path(__file__).resolve().parent.parent


class ExecutionBoundaryTests(unittest.TestCase):
    def test_untrusted_action_ids_cannot_execute(self):
        runner = Mock()
        for ident in ('files.cwd; touch /tmp/NEVER', '$(whoami)', 'unknown', 'app.help', ''):
            with self.assertRaises(ValueError):
                execute(ident, runner=runner)
        runner.assert_not_called()

    def test_literal_argv_no_shell_or_stdin_capture(self):
        runner = Mock(return_value=NS(returncode=0))
        self.assertEqual(execute('system.update', runner=runner, resolver=lambda name: '/usr/bin/' + name), 0)
        self.assertEqual([c.args[0] for c in runner.call_args_list],
                         [['/usr/bin/sudo', '/usr/bin/apt', 'update'],
                          ['/usr/bin/sudo', '/usr/bin/apt', 'upgrade']])
        for call in runner.call_args_list:
            self.assertNotIn('shell', call.kwargs)
            self.assertNotIn('stdin', call.kwargs)
            self.assertNotIn('input', call.kwargs)
            self.assertNotIn('stdout', call.kwargs)
            self.assertFalse(call.kwargs['check'])

    def test_upgrade_only_after_successful_refresh(self):
        runner = Mock(return_value=NS(returncode=100))
        self.assertEqual(execute('system.update', runner=runner, resolver=lambda x: '/usr/bin/' + x), 100)
        self.assertEqual(runner.call_count, 1)

    def test_signal_exit_is_reported_as_shell_exit_status(self):
        self.assertEqual(execute('files.cwd', runner=Mock(return_value=NS(returncode=-2)),
                                 resolver=lambda x: '/usr/bin/' + x), 130)

    def test_all_executables_checked_before_any_action(self):
        runner = Mock()
        def resolve(name):
            if name == 'apt':
                raise FileNotFoundError('apt')
            return '/usr/bin/' + name
        with self.assertRaises(FileNotFoundError):
            execute('system.update', runner=runner, resolver=resolve)
        runner.assert_not_called()

    def test_interrupt_prevents_next_step(self):
        count = 0
        def interrupted():
            nonlocal count
            count += 1
            return count > 1
        runner=Mock(return_value=NS(returncode=0))
        code=execute('system.update', runner=runner, resolver=lambda n: '/usr/bin/' + n,
                     interrupted=interrupted)
        self.assertEqual(code, 130)
        self.assertEqual(runner.call_count, 1)

    def test_environment_does_not_publish_shell_ipc_or_python_overrides(self):
        env=command_environment({'AURALYN_SESSION_DIR': '/private', 'AURALYN_EVENT_FIFO': '/fifo',
            'BASH_ENV': '/bad', 'PYTHONPATH': '/bad', 'HOME': '/home/test', 'TERM': 'xterm-256color'})
        self.assertEqual(env['HOME'], '/home/test')
        self.assertEqual(env['TERM'], 'xterm-256color')
        for key in ('AURALYN_SESSION_DIR', 'AURALYN_EVENT_FIFO', 'BASH_ENV', 'PYTHONPATH'):
            self.assertNotIn(key, env)

    def test_ignores_project_path_and_fake_pwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake=Path(tmp, 'pwd'); fake.write_text('#!/bin/sh\nexit 99\n');fake.chmod(0o755)
            with patch.dict(os.environ, {'PATH': tmp}):
                actual=executable_path('pwd')
            self.assertNotEqual(actual, str(fake))
            self.assertTrue(actual.startswith(('/usr/bin/', '/bin/')))

    def test_invalid_executable_names_refused(self):
        for name in ('', '../pwd', '/usr/bin/pwd', '-e'):
            with self.assertRaises(ValueError):
                executable_path(name)
        with self.assertRaises(ValueError):
            resolve_step(('sudo', '-S'))


class SmartSession(BashSession):
    def __init__(self, bashrc='', custom_entry: Entry | None = None, wait=True):
        self.home=tempfile.TemporaryDirectory(prefix='auralyn smart pty ')
        self.directory=Path(self.home.name)
        self.rcfile=self.directory/'.bashrc'
        self.rcfile.write_text("PS1='SMART_TEST> '\n" + bashrc)
        self.ipc=SessionIPC(); self.messages=[]; self.output=b''; self.ready=False
        self.pid,self.fd=pty.fork()
        if self.pid == 0:
            os.environ.update({'HOME': self.home.name, 'TERM': 'xterm-256color', 'LANG': 'C.UTF-8',
                'AURALYN_EVENT_FIFO': str(self.ipc.fifo), 'AURALYN_SESSION_DIR': str(self.ipc.directory)})
            os.environ.pop('BASH_ENV', None)
            os.chdir(self.home.name)
            if custom_entry is None:
                os.execv('/usr/bin/python3', ['python3', '-I', str(ROOT/'smart_launcher.py'), 'files.cwd'])
            code=(f'import sys; sys.path.insert(0, {str(ROOT)!r}); '
                  'from auralyn_terminal import smart_session as s; '
                  'from auralyn_terminal.smart_catalog import Entry; '
                  f'entry={custom_entry!r}; s.get_action=lambda ident: entry if ident == entry.id else None; '
                  'raise SystemExit(s.main([entry.id]))')
            os.execv('/usr/bin/python3', ['python3', '-I', '-c', code])
        if wait:
            self.initial_prompt=self.wait('P', timeout=4)
            self.pump(.03)

    def wait_output(self, marker: bytes, timeout=3):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.pump(.02)
            if marker in self.output:
                return
        raise AssertionError(f'Missing output {marker!r}: {self.output[-1000:]!r}')


class RealSmartPTYTests(unittest.TestCase):
    def test_real_action_finishes_then_normal_bash_and_completions(self):
        session=SmartSession()
        try:
            self.assertIn(b'$ pwd', session.output)
            self.assertIn(str(session.directory).encode(), session.output)
            self.assertIn(b'Exit-Code 0', session.output)
            self.assertEqual(int(session.initial_prompt[0]), session.pid)
            self.assertTrue(is_readline_foreground(session.fd, session.pid, session.ready))
            session.write('sudo a')
            self.assertEqual(session.snapshot()[3], 'sudo a')
        finally:
            session.close()

    def test_initial_action_does_not_run_user_pwd_alias(self):
        session=SmartSession("pwd() { printf 'USER_PWD_FUNCTION\\n'; }\n")
        try:
            self.assertNotIn(b'USER_PWD_FUNCTION', session.output)
            session.command('pwd')
            self.assertIn(b'USER_PWD_FUNCTION', session.output)
        finally:
            session.close()

    def test_ctrl_c_returns_to_normal_prompt(self):
        entry=Entry('test.sleep', 'Controlled test sleep', 'fixture', (), (('sleep', '30'),))
        session=SmartSession(custom_entry=entry, wait=False)
        try:
            session.wait_output(b'$ sleep 30')
            session.pump(.05)
            self.assertFalse(session.ready)
            session.write(b'\x03')
            session.wait('P', timeout=3)
            session.pump(.03)
            self.assertIn(b'Exit-Code 130', session.output)
            self.assertTrue(is_readline_foreground(session.fd, session.pid, session.ready))
        finally:
            session.close()

    def test_synthetic_password_prompt_gets_tty_not_search(self):
        code="import getpass; p=getpass.getpass('TEST_PASSWORD: '); print('PASS_OK' if p == 'synthetic-secret-415' else 'WRONG')"
        entry=Entry('test.input', 'Controlled password fixture', 'fixture', (), (('python3', '-c', code),))
        session=SmartSession(custom_entry=entry, wait=False)
        try:
            # The command is printed, so use the actual TTY prompt at the end.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                session.pump(.02)
                if session.output.endswith(b'TEST_PASSWORD: '):
                    break
            else:
                self.fail('Password fixture did not prompt')
            before=len(session.output)
            self.assertFalse(session.ready)
            self.assertFalse(is_readline_foreground(session.fd, session.pid, session.ready))
            self.assertFalse(termios.tcgetattr(session.fd)[3] & termios.ECHO)
            session.write('synthetic-secret-415\r')
            session.wait('P', timeout=3); session.pump(.03)
            self.assertIn(b'PASS_OK', session.output[before:])
            self.assertNotIn(b'synthetic-secret-415', session.output[before:])
        finally:
            session.close()

    def test_invalid_launcher_id_not_interpreted_as_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp,'NEVER')
            result=subprocess.run(['/usr/bin/python3','-I', str(ROOT/'smart_launcher.py'),
                                   'files.cwd;touch '+str(marker)], capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
