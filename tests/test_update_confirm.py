"""previous development version: native yes flags, no output scraping or synthetic J/Y input.

Real subprocess tests use tiny temporary sudo/APT/Flatpak fixture programs.
They NEVER run the host's package managers, sudo or real keyring. Existing
update tests cover the real Unix-socket broker with dummy secrets separately.
"""
from __future__ import annotations
import ast
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from auralyn_terminal import __version__
from auralyn_terminal.settings import Settings, DEFAULTS, validate
from auralyn_terminal.update_session import (
    UpdateRunner, UpdateResult, DISPLAY_COMMANDS, display_commands,
    confirmation_notice, shell_environment,
)
from auralyn_terminal.app_intent import match_app_question
from auralyn_terminal.app_knowledge import APP_HELP
from test_update_session import setup_runner
import test_update_ui as update_ui_tests

ROOT = Path(__file__).resolve().parent.parent


class ConfirmationSettingsTests(unittest.TestCase):
    def test_new_and_old_settings_enable_confirmation_not_password_storage(self):
        for old in ({}, {'transparency': 53, 'smart_ai_enabled': True,
                          'smart_ai_model': 'qwen3:4b', 'update_use_keyring': False}):
            settings = validate(old)
            self.assertIs(settings['update_auto_confirm'], True)
            self.assertIs(settings['update_use_keyring'], False)
            for key, value in old.items():
                self.assertEqual(settings[key], value)

    def test_saved_credentials_setting_preserved_independently(self):
        for keyring in (False, True):
            for automatic in (False, True):
                data = validate({'update_use_keyring': keyring,
                                 'update_auto_confirm': automatic})
                self.assertIs(data['update_use_keyring'], keyring)
                self.assertIs(data['update_auto_confirm'], automatic)

    def test_invalid_types_do_not_become_commands_or_truthy_values(self):
        for value in ('false', '--force-yes', 'yes | sudo sh', 0, 1, None, [], {}):
            with self.subTest(value=value):
                self.assertIs(validate({'update_auto_confirm': value})['update_auto_confirm'], True)
        runner, *_ = setup_runner(assume_yes='--force-yes')
        self.assertIs(runner.assume_yes, False)

    def test_toggle_roundtrip_and_existing_keyring_config_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            path.write_text(json.dumps({'transparency': 64, 'smart_ai_model': 'qwen3:4b',
                                        'update_use_keyring': True}))
            settings = Settings(path)
            for automatic in (False, True, False):
                settings.set('update_auto_confirm', automatic)
                restored = Settings(path)
                self.assertIs(restored['update_auto_confirm'], automatic)
                self.assertTrue(restored['update_use_keyring'])
                self.assertEqual(restored['transparency'], 64)
                self.assertEqual(restored['smart_ai_model'], 'qwen3:4b')
            self.assertNotIn('password', path.read_text())


class NativeConfirmationTests(unittest.TestCase):
    def test_only_full_upgrade_and_flatpak_get_correct_native_flags(self):
        for saved in (False, True):
            with self.subTest(saved=saved):
                runner, *_ = setup_runner(saved=saved, assume_yes=True)
                result = runner.execute()
                self.assertEqual(result, UpdateResult(0, 3, True))
                sudo = ['/usr/bin/sudo', '-k'] + (['-A'] if saved else []) + ['--']
                actual = [c.args[0] for c in runner.popen.call_args_list]
                self.assertEqual(actual, [sudo + ['/usr/bin/apt', 'update'],
                                         sudo + ['/usr/bin/apt', 'full-upgrade', '-y'],
                                         ['/usr/bin/flatpak', 'update', '--assumeyes']])
                for line in display_commands(True):
                    self.assertIn(line, str(runner.emit.call_args_list))
                cleanup = [c.args[0] for c in runner.run.call_args_list if '-K' in c.args[0]]
                self.assertEqual(cleanup, [['/usr/bin/sudo', '-K']] * 3)

    def test_turning_off_restores_old_exact_commands(self):
        runner, *_ = setup_runner(assume_yes=False)
        runner.execute()
        self.assertEqual(display_commands(False), DISPLAY_COMMANDS)
        self.assertEqual([c.args[0] for c in runner.popen.call_args_list], [
            ['/usr/bin/sudo', '-k', '--', '/usr/bin/apt', 'update'],
            ['/usr/bin/sudo', '-k', '--', '/usr/bin/apt', 'full-upgrade'],
            ['/usr/bin/flatpak', 'update']])

    def test_no_global_unsafe_flags_stdin_injection_or_secret_leak(self):
        runner, _, broker, _, secret = setup_runner(saved=True, assume_yes=True)
        runner.execute()
        blocked = {'--force-yes', '--allow-unauthenticated', '--allow-downgrades',
                   '--allow-remove-essential', '--allow-change-held-packages',
                   '--ignore-hold', '--force-remove', '--noninteractive',
                   'yes', 'echo', 'bash', 'sh', 'reboot', 'autoremove'}
        for call in runner.popen.call_args_list:
            self.assertFalse(blocked & set(call.args[0]))
            self.assertNotIn('shell', call.kwargs)
            self.assertNotIn('stdin', call.kwargs)
            self.assertNotIn('input', call.kwargs)
            self.assertNotIn('APT_CONFIG', call.kwargs['env'])
            self.assertNotIn('DEBIAN_FRONTEND', call.kwargs['env'])
            self.assertNotIn('DUMMY-UPDATER-TEST', repr(call))
        self.assertEqual(secret, b'')
        broker.close.assert_called_once()
        self.assertNotIn('SUDO_ASKPASS', runner.popen.call_args_list[-1].kwargs['env'])

    def test_failure_at_any_stage_stops_and_revokes_without_retry(self):
        for codes, count in (((100,), 1), ((0, 100), 2), ((0, 0, 1), 3)):
            with self.subTest(codes=codes):
                runner, *_ = setup_runner(codes, assume_yes=True, saved=True)
                result = runner.execute()
                self.assertEqual(result.code, codes[-1])
                self.assertEqual(runner.popen.call_count, count)
                self.assertEqual(result.completed, count - 1)
                self.assertTrue(result.revoked)

    def test_missing_flatpak_not_auto_installed(self):
        runner, *_ = setup_runner((0, 0), assume_yes=True, missing=('flatpak',))
        result = runner.execute()
        self.assertEqual(result, UpdateResult(0, 2, True, True))
        self.assertEqual(runner.popen.call_count, 2)
        self.assertIn('übersprungen', str(runner.emit.call_args_list))

    def test_interrupt_full_upgrade_does_not_continue_or_skip_cleanup(self):
        runner, children, broker, _, _ = setup_runner((0, -2), assume_yes=True, saved=True)
        def stop():
            runner.interrupt(signal.SIGINT)
            return -2
        children[1].wait.side_effect = stop
        result = runner.execute()
        self.assertEqual(result, UpdateResult(130, 1, True))
        self.assertEqual(runner.popen.call_count, 2)
        broker.close.assert_called_once()
        children[1].send_signal.assert_called_with(signal.SIGINT)

    def test_failed_cleanup_not_reported_as_success_in_automatic_mode(self):
        runner, *_ = setup_runner(assume_yes=True)
        runner.run.side_effect = [NS(returncode=0), NS(returncode=0), NS(returncode=1)]
        result = runner.execute()
        self.assertFalse(result.revoked)
        self.assertEqual(result.code, 1)
        self.assertIn('NICHT gelöscht', str(runner.emit.call_args_list))

    def test_notice_does_not_claim_all_config_or_auth_prompts_disappear(self):
        text = confirmation_notice(True)
        for word in ('EIN', 'entfernen', 'Konfigurationsfragen', 'Berechtigungsabfragen',
                     '-y', '--assumeyes', 'Kein automatischer Neustart'):
            self.assertIn(word, text)
        self.assertIn('AUS', confirmation_notice(False))
        self.assertIn('selbst bestätigen', confirmation_notice(False))


class ConfirmationUiTests(unittest.TestCase):
    def dialog(self, **kwargs):
        return update_ui_tests.LifecycleTests().create(**kwargs)

    def test_dialog_default_enabled_and_can_disable_independently(self):
        dialog, owner, store = self.dialog(exists=True, enabled=True)
        self.assertTrue(dialog.auto_confirm.get_active())
        self.assertTrue(dialog.enabled.get_active())
        owner.change_setting.reset_mock()
        dialog.auto_confirm.set_active(False)
        owner.change_setting.assert_called_once_with('update_auto_confirm', False)
        self.assertTrue(dialog.enabled.get_active())
        store.lookup.assert_not_called()
        store.delete.assert_not_called()
        store.save.assert_not_called()

    def test_keyring_failure_does_not_block_independent_confirmation_toggle(self):
        dialog, owner, store = self.dialog()
        store.exists.side_effect = RuntimeError('no service')
        dialog._task('status')
        owner.change_setting.reset_mock()
        dialog.auto_confirm.set_active(False)
        dialog.auto_confirm.set_active(True)
        self.assertEqual([c.args for c in owner.change_setting.call_args_list],
                         [('update_auto_confirm', False), ('update_auto_confirm', True)])
        self.assertFalse(dialog.enabled.get_active())

    def test_closed_dialog_never_changes_setting(self):
        dialog, owner, _ = self.dialog()
        dialog._destroyed()
        owner.change_setting.reset_mock()
        dialog.auto_confirm.set_active(False)
        owner.change_setting.assert_not_called()

    def spawn(self, *, update=False, smart=None, automatic=True, saved=False, closed=False):
        tree = ast.parse((ROOT / 'auralyn_terminal/app.py').read_text())
        cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'TerminalPage')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == '_spawn')
        ns = {'os': os, 'ROOT': ROOT, '__version__': __version__,
              'Vte': NS(PtyFlags=NS(DEFAULT=0)), 'GLib': NS(SpawnFlags=NS(DEFAULT=0))}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-_spawn>', 'exec'), ns)
        page = NS(closed=closed, smart_action=smart, update_session=update,
                  window=NS(settings={**DEFAULTS, 'update_auto_confirm': automatic,
                                      'update_use_keyring': saved}),
                  ipc=NS(fifo='/test/fifo', directory='/test/ipc'),
                  cwd='/tmp', terminal=Mock(), _spawn_done=Mock())
        ns['_spawn'](page)
        return page

    def test_updated_setting_reaches_updater_as_flag_only(self):
        for automatic in (False, True):
            for saved in (False, True):
                with self.subTest(automatic=automatic, saved=saved):
                    page = self.spawn(update=True, automatic=automatic, saved=saved)
                    argv = page.terminal.spawn_async.call_args.args[2]
                    expected = ['/usr/bin/python3', '-I', str(ROOT / 'update_launcher.py')]
                    if saved: expected.append('--saved-password')
                    if automatic: expected.append('--assume-yes')
                    self.assertEqual(argv, expected)
                    env = page.terminal.spawn_async.call_args.args[3]
                    self.assertFalse(any(x.startswith(('APT_CONFIG=', 'DEBIAN_FRONTEND=')) for x in env))
                    page.terminal.feed_child.assert_not_called()

    def test_normal_and_smart_tabs_never_receive_confirmation_flag(self):
        for smart in (None, 'system.update'):
            page = self.spawn(smart=smart, automatic=True, saved=True)
            argv = page.terminal.spawn_async.call_args.args[2]
            self.assertNotIn('--assume-yes', argv)
            self.assertNotIn('--saved-password', argv)
            page.terminal.feed_child.assert_not_called()

    def test_closed_page_does_not_start_update(self):
        page = self.spawn(update=True, closed=True)
        page.terminal.spawn_async.assert_not_called()

    def test_no_auth_or_confirmation_environment_leaks_to_returned_bash(self):
        env = shell_environment({'AURALYN_UPDATE_AUTO_CONFIRM': 'yes',
                                 'SUDO_ASKPASS': 'private-helper', 'TERM': 'xterm'})
        self.assertEqual(env, {'TERM': 'xterm'})


class ProductConfirmationHelpTests(unittest.TestCase):
    def test_help_knows_toggle_without_offering_shell_execution(self):
        for question in ('Wie bestätigt der Update Button automatisch Ja?',
                         'Auralyn Update Button automatisch bestatigen',
                         'Update Button Yes No', 'Wie schalte ich automatisches Ja aus?',
                         'Paketfragen automatisch bestätigen'):
            with self.subTest(question=question):
                match = match_app_question(question)
                self.assertEqual(match.entry_id, 'app.update_confirmation')
                help_entry = APP_HELP[match.entry_id]
                self.assertEqual(help_entry.ui, 'settings')
                self.assertIn('Optionen & Passwort', help_entry.text)
                self.assertIn('--assumeyes', help_entry.text)

    def test_password_help_stays_separate(self):
        self.assertEqual(match_app_question('Wie speichere ich das Passwort für den Update Button?').entry_id,
                         'app.update_password')

    def test_generic_systemupdate_search_does_not_gain_auto_yes(self):
        from auralyn_terminal.smart_search import SearchEngine
        answer = SearchEngine().answer('Wie update ich mein System?', False, 'qwen3:4b')
        self.assertEqual(answer.command, 'sudo apt update && sudo apt upgrade')


FIXTURE = r'''#!/usr/bin/python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as f:
    f.write(json.dumps([name, args]) + '\n')
if name == 'sudo':
    if args == ['-K']: sys.exit(0)
    if args == ['--help']: print('--askpass'); sys.exit(0)
    if args[:2] != ['-k', '--']: sys.exit(90)
    os.execv(args[2], args[2:])
if name == 'apt' and args == ['update']:
    print('fixture: package lists'); sys.exit(0)
flag = '-y' if name == 'apt' else '--assumeyes'
prompt = 'Möchten Sie fortfahren? [J/n]' if os.environ.get('FIXTURE_LANG') == 'de' else 'Do you want to continue? [Y/n]'
print('fixture: ' + prompt, flush=True)
if flag not in args:
    # Deliberately no host package action and no waiting for tester input.
    print('fixture: would require manual confirmation', flush=True); sys.exit(29)
if name == 'apt' and os.environ.get('FIXTURE_REFUSE') == '1':
    print('fixture: special change rejected despite native -y'); sys.exit(100)
if name == 'apt' and os.environ.get('FIXTURE_CONFIG') == '1':
    print('fixture: replace modified configuration? [Y/n]', flush=True)
    # Auralyn must not pipe or synthesize an answer to this unknown question.
    text = sys.stdin.readline()
    sys.exit(91 if text else 42)
print('fixture: native yes selected', flush=True)
'''


class NativeSubprocessTests(unittest.TestCase):
    def exercise(self, *, automatic=True, lang='de', refuse=False, config=False):
        with tempfile.TemporaryDirectory(prefix='auralyn-confirm-test-') as temp:
            base = Path(temp)
            for name in ('sudo', 'apt', 'flatpak'):
                path = base / name
                path.write_text(FIXTURE)
                path.chmod(0o755)
            env = {**os.environ, 'FIXTURE_LOG': str(base / 'calls.jsonl'),
                   'FIXTURE_LANG': lang, 'FIXTURE_REFUSE': str(int(refuse)),
                   'FIXTURE_CONFIG': str(int(config))}
            def popen(argv, **kwargs):
                return subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
            runner = UpdateRunner(saved_password=False, assume_yes=automatic,
                                  resolver=lambda name: str(base / name), environ=env,
                                  popen=popen, emit=Mock())
            result = runner.execute()
            calls = [json.loads(line) for line in (base / 'calls.jsonl').read_text().splitlines()]
            return result, calls

    def test_german_native_confirmation_completes_without_entered_j(self):
        result, calls = self.exercise(lang='de')
        self.assertEqual(result, UpdateResult(0, 3, True))
        self.assertIn(['apt', ['full-upgrade', '-y']], calls)
        self.assertIn(['flatpak', ['update', '--assumeyes']], calls)
        self.assertEqual(calls[-1], ['sudo', ['-K']])

    def test_english_native_confirmation_completes_without_entered_y(self):
        result, calls = self.exercise(lang='en')
        self.assertEqual(result, UpdateResult(0, 3, True))
        self.assertEqual(sum(row == ['sudo', ['-K']] for row in calls), 3)

    def test_manual_mode_does_not_force_through_fixture_prompt(self):
        result, calls = self.exercise(automatic=False)
        self.assertEqual(result, UpdateResult(29, 1, True))
        self.assertNotIn('flatpak', [row[0] for row in calls])
        self.assertIn(['apt', ['full-upgrade']], calls)

    def test_native_rejection_does_not_trigger_force_flags_or_retry(self):
        result, calls = self.exercise(refuse=True)
        self.assertEqual(result, UpdateResult(100, 1, True))
        self.assertEqual(sum(row[0] == 'apt' for row in calls), 2)
        self.assertNotIn('flatpak', [row[0] for row in calls])
        self.assertEqual(calls[-1], ['sudo', ['-K']])

    def test_unknown_config_prompt_gets_no_synthetic_input(self):
        result, calls = self.exercise(config=True)
        self.assertEqual(result, UpdateResult(42, 1, True))
        self.assertNotIn('flatpak', [row[0] for row in calls])
        self.assertEqual(calls[-1], ['sudo', ['-K']])
