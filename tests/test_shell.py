"""Integration tests against REAL Bash in a real controlling pseudoterminal.

No GTK/VTE required. Synthetic secret strings only; no system sudoers changes.
"""
import os
import pty
import select
import shlex
import signal
import tempfile
import termios
import time
import unittest
from pathlib import Path

from auralyn_terminal.protocol import SessionIPC
from auralyn_terminal.terminal_state import is_readline_foreground

ROOT = Path(__file__).resolve().parent.parent
QUERY = b'\x1b[989;1~'
APPLY = b'\x1b[989;2~'


class BashSession:
    def __init__(self, bashrc=""):
        self.home = tempfile.TemporaryDirectory(prefix='auralyn-shell-test-')
        self.directory = Path(self.home.name)
        self.rcfile = self.directory / '.bashrc'
        self.rcfile.write_text("PS1='AURALYN_TEST> '\n" + bashrc)
        self.ipc = SessionIPC()
        self.messages = []
        self.output = b''
        self.ready = False
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.update({'HOME': self.home.name, 'TERM': 'xterm-256color', 'LANG': 'C.UTF-8',
                'AURALYN_EVENT_FIFO': str(self.ipc.fifo), 'AURALYN_SESSION_DIR': str(self.ipc.directory)})
            os.environ.pop('BASH_ENV', None)
            os.chdir(self.home.name)
            os.execv('/bin/bash', ['bash', '--noprofile', '--rcfile', str(ROOT/'shell'/'bashrc.bash'), '-i'])
        self.wait('P')
        self.pump(.025)

    def pump(self, duration=.03):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            ready, _, _ = select.select([self.fd, self.ipc.fd], [], [], max(0, end-time.monotonic()))
            if self.fd in ready:
                try:
                    self.output += os.read(self.fd, 65536)
                except OSError:
                    pass
            if self.ipc.fd in ready:
                for message in self.ipc.receive():
                    if message[0] == 'P':
                        self.ready = True
                    elif message[0] == 'B':
                        self.ready = False
                    self.messages.append(message)

    def wait(self, kind, timeout=2.5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for i, event in enumerate(self.messages):
                if event[0] == kind:
                    return self.messages.pop(i)[1]
            self.pump(.02)
        raise AssertionError(f'No {kind!r} event; output={self.output[-1000:]!r}; messages={self.messages!r}')

    def write(self, text):
        os.write(self.fd, text.encode() if isinstance(text, str) else text)

    def snapshot(self):
        self.write(QUERY)
        return self.wait('S')

    def command(self, text):
        self.write(text + '\r')
        self.wait('B')
        result = self.wait('P')
        self.pump(.02)
        return result

    def close(self):
        try:
            foreground = os.tcgetpgrp(self.fd)
            if foreground > 0 and foreground != self.pid:
                os.killpg(foreground, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(self.pid, 0)
        os.close(self.fd)
        self.ipc.close()
        self.home.cleanup()


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.session = BashSession()

    def tearDown(self):
        self.session.close()

    def test_readline_foreground_detected_even_with_echo_off(self):
        s = self.session
        self.assertFalse(termios.tcgetattr(s.fd)[3] & termios.ECHO)
        self.assertTrue(is_readline_foreground(s.fd, s.pid, s.ready))
        self.assertFalse(is_readline_foreground(s.fd, s.pid, False))

    def test_live_line_snapshot(self):
        s = self.session
        s.write('sudo a')
        result = s.snapshot()
        self.assertEqual(result[0], '6')
        self.assertEqual(result[3], 'sudo a')
        self.assertTrue(is_readline_foreground(s.fd, s.pid, s.ready))

    def test_bash_ctrl_a_moves_to_start_of_input_line(self):
        """Readline's original Ctrl+A is preserved, without executing input."""
        s = self.session
        s.write('sudo')
        point, _, _, line, *_ = s.snapshot()
        self.assertEqual((point, line), ('4', 'sudo'))
        s.write(b'\x01')  # Ctrl+A, delivered by VTE when GUI handler returns False.
        point, _, _, line, *_ = s.snapshot()
        self.assertEqual((point, line), ('0', 'sudo'))
        s.write('echo ')
        point, _, _, line, *_ = s.snapshot()
        self.assertEqual((point, line), ('5', 'echo sudo'))

    def test_utf8_snapshot_and_replacement(self):
        s = self.session
        s.write('echo grü')
        snap = s.snapshot()
        self.assertEqual(int(snap[0]), len('echo grü'.encode()))
        s.ipc.write_replacement('echo grü', int(snap[0]), 'echo grün ', len('echo grün '.encode()))
        s.write(APPLY)
        self.assertEqual(s.wait('S')[3], 'echo grün ')

    def test_apply_does_not_execute(self):
        s = self.session
        marker = s.directory / 'MARKER'
        s.write('tou')
        s.snapshot()
        new = f'touch {shlex.quote(str(marker))}'
        s.ipc.write_replacement('tou', 3, new, len(new.encode()))
        s.write(APPLY)
        result = s.wait('S')
        self.assertEqual(result[3], new)
        self.assertFalse(marker.exists())
        s.write('\r')
        s.wait('B')
        s.wait('P')
        self.assertTrue(marker.exists())

    def test_stale_replacement_refused(self):
        s = self.session
        s.write('sud')
        s.snapshot()
        s.ipc.write_replacement('su', 2, 'sudo ', 5)
        s.write(APPLY)
        self.assertEqual(s.wait('S')[3], 'sud')

    def test_status_survives_snapshot(self):
        s = self.session
        s.command('false')
        s.write('printf "STATUS:%s\\n" "$?"')
        s.snapshot()
        s.write('\r')
        s.wait('B'); s.wait('P'); s.pump(.02)
        self.assertIn(b'STATUS:1', s.output)

    def test_status_survives_apply(self):
        s = self.session
        s.command('false')
        s.write('p')
        s.snapshot()
        line = 'printf "APPLY_STATUS:%s\\n" "$?"'
        s.ipc.write_replacement('p', 1, line, len(line))
        s.write(APPLY)
        s.wait('S')
        s.write('\r')
        s.wait('B'); s.wait('P'); s.pump(.02)
        self.assertIn(b'APPLY_STATUS:1', s.output)

    def test_program_owns_foreground(self):
        s = self.session
        s.write('sleep 0.3\r')
        s.wait('B')
        s.pump(.03)
        self.assertFalse(is_readline_foreground(s.fd, s.pid, s.ready))
        self.assertNotEqual(os.tcgetpgrp(s.fd), s.pid)
        s.wait('P')
        s.pump(.03)
        self.assertTrue(is_readline_foreground(s.fd, s.pid, s.ready))

    def test_hidden_read_is_not_a_completion_prompt(self):
        s = self.session
        s.write("read -rs -p 'Synthetic password: ' __secret; printf '\\nDONE\\n'\r")
        s.wait('B'); s.pump(.03)
        # read is a Bash builtin: the foreground PID alone would be insufficient.
        self.assertEqual(os.tcgetpgrp(s.fd), s.pid)
        self.assertFalse(is_readline_foreground(s.fd, s.pid, s.ready))
        s.write('synthetic-secret-123\r')
        s.wait('P'); s.pump(.03)
        self.assertFalse(any(event[0] == 'S' for event in s.messages))
        self.assertNotIn(b'synthetic-secret-123', s.output)
        self.assertNotIn('synthetic-secret-123', repr(s.messages))

    def test_alias_function_path_and_cwd_publish(self):
        s = self.session
        names = s.command("alias julius_alias='echo hi'; julius_function() { :; }")[3]
        self.assertIn('julius_alias', names)
        self.assertIn('julius_function', names)
        path = s.command('PATH=/usr/bin:/bin')[2]
        self.assertEqual(path, '/usr/bin:/bin')
        self.assertEqual(s.command('cd /tmp')[1], '/tmp')

    def test_faceman_commands_discovered_as_auralyn_shell_functions(self):
        s = self.session
        names = s.command('true')[3].splitlines()
        for name in ('face', 'gondelface', 'luiswiththegondelface'):
            self.assertIn(name, names)
            s.command(f'type -t {name}')
            self.assertIn(b'function', s.output)

    def test_faceman_commands_repeat_and_stop_with_ctrl_c(self):
        s = self.session
        for name in ('face', 'gondelface', 'luiswiththegondelface'):
            before = len(s.output)
            s.write(name + '\r')
            s.wait('B')
            s.pump(0.65)
            printed = s.output[before:].count(b'Faceman is here')
            self.assertGreaterEqual(printed, 3, name)
            self.assertLess(printed, 12, 'Output must be throttled to avoid terminal freezes')
            s.write('\x03')
            s.wait('P', timeout=3)
            s.pump(0.1)
            print_count = s.output.count(b'Faceman is here')
            s.command(f'printf "AFTER_{name}\\n"')
            self.assertEqual(s.output.count(b'Faceman is here'), print_count,
                             'Ctrl+C must stop printing before the next command')
            self.assertIn(('AFTER_' + name).encode(), s.output)

    def test_no_rc_file_changes(self):
        s = self.session
        before = s.rcfile.read_bytes()
        s.command('true')
        self.assertEqual(s.rcfile.read_bytes(), before)

    def test_clear_command_restores_live_snapshots_and_path_completions(self):
        # clear emits VT escape sequences, including optional scrollback erase.
        s = self.session
        for _ in range(3):
            s.command('clear')
            self.assertTrue(is_readline_foreground(s.fd, s.pid, s.ready))
            s.write('sud')
            line = s.snapshot()[3]
            self.assertEqual(line, 'sud')
            s.write('\x15')  # Ctrl+U: clear the TEST input, not the screen.
            self.assertEqual(s.snapshot()[3], '')

    def test_ctrl_l_redraw_does_not_end_readline_completion(self):
        s = self.session
        s.write('sud')
        self.assertEqual(s.snapshot()[3], 'sud')
        s.write(b'\x0c')  # Readline clear-screen (Ctrl+L), NOT command execution
        s.pump(.03)
        self.assertTrue(is_readline_foreground(s.fd, s.pid, s.ready))
        self.assertEqual(s.snapshot()[3], 'sud')

    def test_ctrl_c_reactivates_prompt(self):
        s = self.session
        s.write('never-run-this-command')
        s.snapshot()
        s.write('\x03')
        s.wait('P'); s.pump(.02)
        s.write('sud')
        self.assertEqual(s.snapshot()[3], 'sud')


class PromptCompatibilityTests(unittest.TestCase):
    def test_array_prompt_command_preserved(self):
        session = BashSession("PROMPT_COMMAND=('printf ARRAY_HOOK' 'true')\n")
        try:
            self.assertIn(b'ARRAY_HOOK', session.output)
            session.write('sud')
            self.assertEqual(session.snapshot()[3], 'sud')
        finally:
            session.close()

    def test_vi_mode_snapshot(self):
        session = BashSession('set -o vi\n')
        try:
            session.write('sudo a')
            self.assertEqual(session.snapshot()[3], 'sudo a')
        finally:
            session.close()


if __name__ == '__main__':
    unittest.main()
