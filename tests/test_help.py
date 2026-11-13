"""Offline help logic and worker tests (independent of GTK and real sudo)."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from auralyn_terminal.completion import Candidate, parse_context
from auralyn_terminal.command_help import (describe, HelpEngine, HelpWorker,
                                           HelpText, clean_text, parse_whatis, MAX_TEXT)
from auralyn_terminal.help_catalog import COMMAND_HELP, SUBCOMMAND_HELP


def context(text):
    return parse_context(text, len(text.encode()))


class DescriptionTests(unittest.TestCase):
    def setUp(self):
        self.manual = Mock(return_value=None)
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def help(self, line, value, kind='Programm'):
        return describe(context(line), Candidate(value, kind), self.cwd, self.manual)

    def test_faceman_help_has_ctrl_c_for_all_three_names(self):
        for name in ('face', 'gondelface', 'luiswiththegondelface'):
            item = self.help(name[:2], name, 'Shell')
            self.assertIn('Faceman is here', item.text)
            self.assertIn('Strg+C', item.text)
            self.manual.assert_not_called()

    def test_sudo_in_german_without_manual_process(self):
        result = self.help('sud', 'sudo')
        self.assertIn('Administrator', result.text)
        self.manual.assert_not_called()

    def test_command_after_sudo(self):
        self.assertIn('Ubuntu-Pakete', self.help('sudo a', 'apt').text)

    def test_apt_install_context(self):
        result = self.help('sudo apt i', 'install', 'Bash')
        self.assertEqual(result.title, 'apt install')
        self.assertIn('Abhängigkeiten', result.text)

    def test_sudo_target_user(self):
        self.assertEqual(self.help('sudo -u root apt u', 'update').title, 'apt update')

    def test_update_not_upgrade(self):
        self.assertIn('noch keine', self.help('apt u', 'update').text)
        self.assertNotEqual(self.help('apt u', 'update').text, self.help('apt u', 'upgrade').text)

    def test_git_commit(self):
        self.assertIn('vorgemerkte', self.help('git c', 'commit').text)

    def test_nested_docker_compose(self):
        result = self.help('docker compose u', 'up', 'Bash')
        self.assertEqual(result.title, 'docker compose up')
        self.assertIn('Compose', result.text)

    def test_exact_subcommand_options(self):
        self.assertIn('verloren', self.help('git reset --h', '--hard', 'Bash').text)
        self.assertIn('keine', self.help('some-cli reset --h', '--hard', 'Bash').text)

    def test_sudo_option(self):
        self.assertIn('Benutzer', self.help('sudo --u', '--user', 'Bash').text)

    def test_unknown_option_is_not_guessed(self):
        result = self.help('mytool --r', '--restart', 'Bash')
        self.assertEqual(result.source, 'Keine Beschreibung vorhanden')
        self.manual.assert_not_called()

    def test_manual_for_third_party_name(self):
        self.manual.return_value = 'manage the island assets'
        result = self.help('island-', 'island-cli')
        self.assertEqual(result.text, 'manage the island assets')
        self.assertIn('Originalsprache', result.source)
        self.manual.assert_called_once_with('island-cli')

    def test_manual_for_separate_subcommand_page(self):
        self.manual.return_value = 'display project statistics'
        result = self.help('island-cli st', 'stats', 'Bash')
        self.assertIn('statistics', result.text)
        self.manual.assert_called_once_with('island-cli-stats')

    def test_unknown_command_honest(self):
        result = self.help('zthird', 'zthirdparty')
        self.assertIn('Keine lokale', result.text)

    def test_file_argument_not_another_command(self):
        result = self.help('cat su', 'sudo', 'Datei')
        self.assertNotIn('Administrator', result.text)
        self.manual.assert_not_called()

    def test_argument_not_top_level_command(self):
        result = self.help('cat su', 'sudo', 'Bash')
        self.assertNotIn('Administrator', result.text)
        self.manual.assert_called_once_with('cat-sudo')

    def test_package_argument(self):
        result = self.help('apt install na', 'nano', 'Bash')
        self.assertEqual(result.source, 'Paketargument')
        self.assertNotIn('Texteditor', result.text)

    def test_own_script_does_not_inherit_system_name(self):
        result = self.help('./su', './sudo', 'Datei')
        self.assertNotIn('Administrator', result.text)
        self.assertIn('Skripte', result.text)
        self.manual.assert_not_called()

    def test_directory(self):
        self.assertIn('Ordner', self.help('cd Do', 'Downloads/', 'Ordner').text)

    def test_native_file_detected(self):
        Path(self.cwd, 'docs').mkdir()
        self.assertEqual(self.help('cd do', 'docs/', 'Bash').source, 'Dateipfad')
        Path(self.cwd, 'notes').touch()
        self.assertEqual(self.help('cat no', 'notes', 'Bash').source, 'Dateipfad')

    def test_unknown_shell_entry_not_guessed_from_manual(self):
        result = self.help('myal', 'myalias', 'Shell')
        self.assertIn('Definition', result.text)
        self.manual.assert_not_called()

    def test_no_markup_or_controls(self):
        self.manual.return_value = 'Do\x1b something\u202e evil\nnext <b>text</b>'
        result = self.help('f', 'foobar')
        self.assertNotIn('\x1b', result.text)
        self.assertNotIn('\u202e', result.text)
        self.assertNotIn('\n', result.text)
        # Kept as plain text, NOT passed to GTK set_markup.
        self.assertIn('<b>text</b>', result.text)

    def test_catalog_is_short(self):
        self.assertGreater(len(COMMAND_HELP), 100)
        self.assertGreater(len(SUBCOMMAND_HELP), 100)
        for value in (*COMMAND_HELP.values(), *SUBCOMMAND_HELP.values()):
            self.assertLessEqual(len(value), MAX_TEXT)
            self.assertEqual(value, clean_text(value))


class ManualParsingTests(unittest.TestCase):
    def test_standard_description(self):
        self.assertEqual(parse_whatis(b'foo (1) - useful command\n', 'foo'), 'useful command')

    def test_alias_names(self):
        self.assertEqual(parse_whatis(b'bar, foo (8) - manage something\n', 'foo'), 'manage something')

    def test_reject_wrong_name(self):
        self.assertIsNone(parse_whatis(b'foobar (1) - wrong command\n', 'foo'))

    def test_reject_library_section(self):
        self.assertIsNone(parse_whatis(b'foo (3) - library function\n', 'foo'))

    def test_missing_manual_not_misread(self):
        self.assertIsNone(parse_whatis(b'foo: nothing appropriate.\n', 'foo'))

    def test_output_bounded(self):
        self.assertIsNone(parse_whatis(b'foo (1) - ' + b'x' * 40000, 'foo'))
        self.assertLessEqual(len(clean_text('x' * 10000)), MAX_TEXT)


class ManualProcessTests(unittest.TestCase):
    """Substitute a controlled Python child for whatis, never the target CLI.

    This tests real process bounds and argument safety, not a man-db installation.
    """
    def setUp(self):
        self.engine = HelpEngine()
        self.real_popen = subprocess.Popen

    def tearDown(self):
        self.engine.cancel()

    def runner(self, code):
        def spawn(argv, **kwargs):
            self.assertEqual(argv[:4], ['/usr/bin/whatis', '--long', '--sections=1,8', '--'])
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['env']['PATH'], '/usr/bin:/bin')
            self.assertNotIn('LD_PRELOAD', kwargs['env'])
            return self.real_popen([sys.executable, '-I', '-S', '-c', code], **kwargs)
        return spawn

    def test_fixed_helper_and_cached_result(self):
        with patch('auralyn_terminal.command_help.os.access', return_value=True), \
             patch('auralyn_terminal.command_help.subprocess.Popen', side_effect=self.runner("print('ztool (1) - useful thing')")) as popen:
            self.assertEqual(self.engine.lookup_manual('ztool'), 'useful thing')
            self.assertEqual(self.engine.lookup_manual('ztool'), 'useful thing')
            self.assertEqual(popen.call_count, 1)

    def test_no_executable_what_is_graceful(self):
        with patch('auralyn_terminal.command_help.os.access', return_value=False):
            self.assertIsNone(self.engine.lookup_manual('ztool'))

    def test_invalid_topics_no_process(self):
        with patch('auralyn_terminal.command_help.subprocess.Popen') as popen:
            for name in ('--help', 'x;touch nope', '$(whoami)', '../script', 'foo\nbar', '\x1b[31m'):
                self.assertIsNone(self.engine.lookup_manual(name))
            popen.assert_not_called()

    def test_timeout_kills_child(self):
        with patch('auralyn_terminal.command_help.os.access', return_value=True), \
             patch('auralyn_terminal.command_help.subprocess.Popen', side_effect=self.runner('import time; time.sleep(10)')):
            before = time.monotonic()
            self.assertIsNone(self.engine.lookup_manual('ztool'))
            self.assertLess(time.monotonic() - before, 1.5)
            self.assertIsNone(self.engine._process)

    def test_large_output_kills_child(self):
        with patch('auralyn_terminal.command_help.os.access', return_value=True), \
             patch('auralyn_terminal.command_help.subprocess.Popen', side_effect=self.runner("import sys; sys.stdout.write('ztool (1) - ' + 'a' * 1000000)")):
            self.assertIsNone(self.engine.lookup_manual('ztool'))
            self.assertIsNone(self.engine._process)

    def test_nonzero_exit_not_used(self):
        with patch('auralyn_terminal.command_help.os.access', return_value=True), \
             patch('auralyn_terminal.command_help.subprocess.Popen', side_effect=self.runner("print('ztool (1) - incorrect'); raise SystemExit(1)")):
            self.assertIsNone(self.engine.lookup_manual('ztool'))

    def test_cancellation_before_start(self):
        self.engine.cancel()
        with patch('auralyn_terminal.command_help.subprocess.Popen') as popen:
            self.assertIsNone(self.engine.lookup_manual('ztool'))
            popen.assert_not_called()

    def test_selected_program_is_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp, 'executed')
            tool = Path(tmp, 'zzcustom')
            tool.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
            tool.chmod(0o755)
            with patch.dict(os.environ, {'PATH': tmp}), \
                 patch('auralyn_terminal.command_help.os.access', return_value=True), \
                 patch('auralyn_terminal.command_help.subprocess.Popen', side_effect=self.runner("print('zzcustom (1) - local tool')")):
                result = self.engine.explain(context('zzcu'), Candidate('zzcustom'), tmp)
            self.assertEqual(result.text, 'local tool')
            self.assertFalse(marker.exists())


class WorkerTests(unittest.TestCase):
    def test_worker_result_has_selection_generation(self):
        done = threading.Event()
        results = []
        worker = HelpWorker(lambda n, text: (results.append((n, text)), done.set()))
        try:
            worker.submit(123, context('sud'), Candidate('sudo'), '/')
            self.assertTrue(done.wait(2))
            self.assertEqual(results[0][0], 123)
            self.assertIn('Administrator', results[0][1].text)
        finally:
            worker.close()
            worker._thread.join(2)
        self.assertFalse(worker._thread.is_alive())

    def test_closing_worker_drops_late_result(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        worker = HelpWorker(lambda *args: results.append(args))
        def slow(*args):
            entered.set()
            release.wait(2)
            return HelpText('sudo', 'text')
        worker.engine.explain = slow
        worker.submit(1, context('sud'), Candidate('sudo'), '/')
        self.assertTrue(entered.wait(2))
        worker.close()
        release.set()
        worker._thread.join(2)
        self.assertFalse(results)
        self.assertFalse(worker._thread.is_alive())

    def test_exception_becomes_honest_help(self):
        done = threading.Event()
        results = []
        worker = HelpWorker(lambda n, text: (results.append(text), done.set()))
        worker.engine.explain = Mock(side_effect=OSError('test'))
        try:
            worker.submit(1, context('sud'), Candidate('sudo'), '/')
            self.assertTrue(done.wait(2))
            self.assertIn('nicht geladen', results[0].text)
        finally:
            worker.close()
            worker._thread.join(2)


if __name__ == '__main__':
    unittest.main()
