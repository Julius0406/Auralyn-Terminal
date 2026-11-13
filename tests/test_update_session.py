"""No real package updates. Fixed commands/cleanup tested with controlled children.

The broker tests use real Unix sockets and isolated helper processes with a dummy
secret, never the tester's password. See LIVE-SUDO-TEST for the optional harmless
real sudo authentication check, performed separately by the packager.
"""
from __future__ import annotations
import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from auralyn_terminal.settings import Settings, DEFAULTS, validate
from auralyn_terminal.update_secrets import validate_password, attributes, SecretError, UpdateSecretStore, SCHEMA_NAME
from auralyn_terminal.update_auth import PasswordBroker, SOCKET_ENV, BROKER_PID_ENV, wipe
from auralyn_terminal.update_session import (UpdateRunner, UpdateResult, UpdateLock, update_environment,
    shell_environment, supports_askpass, revoke_sudo, DISPLAY_COMMANDS)
from auralyn_terminal.app_intent import match_app_question


def setup_runner(codes=(0, 0, 0), *, saved=False, missing=(), **kwargs):
    def resolve(name):
        if name in missing:
            raise FileNotFoundError(name)
        return '/usr/bin/' + name
    processes = [Mock(pid=9200 + i, returncode=code) for i, code in enumerate(codes)]
    for child, code in zip(processes, codes):
        child.wait.return_value = code
        child.poll.return_value = None
    popen = Mock(side_effect=processes)
    run = Mock(return_value=NS(returncode=0, stdout=b'--askpass'))
    broker = Mock()
    broker.environment.side_effect = lambda env, helper: {**env, 'SUDO_ASKPASS': helper, SOCKET_ENV: '/private/no-secret'}
    secret = bytearray(b'DUMMY-UPDATER-TEST')
    store = Mock()
    store.lookup.return_value = secret
    args = dict(saved_password=saved, resolver=resolve, run=run, popen=popen,
                store_factory=Mock(return_value=store), broker_factory=Mock(return_value=broker),
                emit=Mock(), environ={'HOME': '/tmp', 'PATH': '/evil', 'TERM': 'xterm'})
    args.update(kwargs)
    obj = UpdateRunner(**args)
    return obj, processes, broker, store, secret


class SettingsAndSecretTests(unittest.TestCase):
    def test_no_automatic_credential_optin(self):
        self.assertIs(DEFAULTS['update_use_keyring'], False)
        for value in ('yes', 'true', 1, None, [], {}):
            self.assertFalse(validate({'update_use_keyring': value})['update_use_keyring'])
        self.assertTrue(validate({'update_use_keyring': True})['update_use_keyring'])

    def test_config_never_keeps_password_fields(self):
        data = validate({'password': 'NEVER_SAVE_THIS', 'sudo_password': 'NEVER_SAVE_THIS',
                         'update_password': 'NEVER_SAVE_THIS', 'update_use_keyring': True})
        self.assertNotIn('NEVER_SAVE_THIS', json.dumps(data))
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(Path(temp) / 'settings.json')
            settings.set('update_use_keyring', True)
            self.assertTrue(Settings(settings.path)['update_use_keyring'])
            with self.assertRaises(KeyError):
                settings.set('sudo_password', 'NEVER_SAVE_THIS')
            self.assertNotIn('NEVER_SAVE_THIS', settings.path.read_text())

    def test_password_validation_preserves_spaces_and_unicode(self):
        for value in ('abc', '  spaces  ', 'Grüße!🔒', 'x' * 1024):
            self.assertEqual(validate_password(value), value)

    def test_bad_password_shape_never_in_error(self):
        for value in ('', '\nsecret', 'secret\r', 'secret\0', 'ä' * 513, None, 9):
            with self.subTest(type=type(value)):
                with self.assertRaises(SecretError) as cm:
                    validate_password(value)
                self.assertNotIn('secret', str(cm.exception))

    def test_metadata_contains_only_local_scope(self):
        self.assertEqual(set(attributes()), {'uid', 'host', 'purpose'})
        self.assertEqual(attributes()['purpose'], 'update-button')
        self.assertEqual(attributes()['uid'], str(os.getuid()))

    def fake_store(self, service):
        obj = UpdateSecretStore()
        api = NS(SearchFlags=NS(NONE=0, ALL=1, UNLOCK=2, LOAD_SECRETS=4),
                 Value=NS(new=Mock()), COLLECTION_DEFAULT='default')
        @contextmanager
        def session(**kw):
            yield api, service, 'schema', 'cancel'
        obj._session = session
        return obj, api

    def test_exists_uses_metadata_only(self):
        service = Mock();service.search_sync.return_value = [Mock()]
        store, _ = self.fake_store(service)
        self.assertTrue(store.exists())
        service.search_sync.assert_called_once_with('schema', attributes(), 0, 'cancel')
        service.lookup_sync.assert_not_called()

    def test_save_uses_explicit_service_and_secretvalue(self):
        service = Mock();service.store_sync.return_value = True
        store, api = self.fake_store(service)
        store.save('DUMMY secret')
        api.Value.new.assert_called_once_with('DUMMY secret', -1, 'text/plain')
        args = service.store_sync.call_args.args
        self.assertNotIn('DUMMY secret', str(args))
        self.assertEqual(args[3], 'Auralyn Terminal · Passwort für den Update-Button')

    def test_store_error_does_not_claim_saved(self):
        service = Mock();service.store_sync.return_value = False
        store, _ = self.fake_store(service)
        with self.assertRaises(SecretError):store.save('DUMMY')

    def test_lookup_unlocks_only_matching_item(self):
        service = Mock();item = Mock();item.get_secret.return_value.get_text.return_value = 'DUMMY'
        service.search_sync.return_value = [item]
        store, _ = self.fake_store(service)
        secret = store.lookup()
        self.assertEqual(secret, bytearray(b'DUMMY'))
        service.search_sync.assert_called_once_with('schema', attributes(), 6, 'cancel')
        wipe(secret);self.assertEqual(secret, b'')

    def test_missing_or_locked_password_does_not_make_plaintext_fallback(self):
        for items in ([], [Mock(get_secret=Mock(return_value=None))]):
            service = Mock();service.search_sync.return_value = items
            store, _ = self.fake_store(service)
            with self.assertRaises(SecretError):store.lookup()

    def test_delete_unlocks_our_items_and_verifies_removal(self):
        service = Mock();item = Mock();item.get_locked.return_value = False;item.delete_sync.return_value = True
        service.search_sync.side_effect = [[item], []]
        store, _ = self.fake_store(service)
        store.delete()
        item.delete_sync.assert_called_once_with('cancel')
        self.assertEqual(service.search_sync.call_args_list[0].args[2], 3)
        self.assertEqual(service.search_sync.call_args_list[1].args[2], 0)

    def test_locked_delete_reports_failure(self):
        service = Mock();item = Mock();item.get_locked.return_value = True
        service.search_sync.return_value = [item]
        store, _ = self.fake_store(service)
        with self.assertRaises(SecretError):store.delete()
        item.delete_sync.assert_not_called()

    def test_backend_exception_text_is_not_disclosed(self):
        api = NS(Service=NS(get_sync=Mock(side_effect=ValueError('DUMMY SECRET in backend error'))),
                 ServiceFlags=NS(OPEN_SESSION=1))
        store = UpdateSecretStore();store._api = Mock(return_value=(api, NS(Cancellable=Mock), 'schema'))
        with self.assertRaises(SecretError) as cm:store.exists()
        self.assertNotIn('DUMMY SECRET', str(cm.exception))


class WorkflowTests(unittest.TestCase):
    def test_normal_mode_never_reads_keyring(self):
        runner, _, _, _, _ = setup_runner()
        result = runner.execute()
        self.assertEqual(result, UpdateResult(0, 3, True, False))
        runner.store_factory.assert_not_called()
        runner.broker_factory.assert_not_called()
        actual = [call.args[0] for call in runner.popen.call_args_list]
        self.assertEqual(actual, [['/usr/bin/sudo','-k','--','/usr/bin/apt','update'],
                                 ['/usr/bin/sudo','-k','--','/usr/bin/apt','full-upgrade'],
                                 ['/usr/bin/flatpak','update']])
        self.assertEqual([c.args[0] for c in runner.run.call_args_list], [['/usr/bin/sudo','-K']] * 3)

    def test_saved_mode_askpass_only_two_apt_steps(self):
        runner, _, broker, store, secret = setup_runner(saved=True)
        result = runner.execute()
        self.assertEqual(result.code, 0)
        self.assertEqual(store.lookup.call_count, 1)
        self.assertEqual(broker.arm.call_count, 2)
        self.assertEqual(broker.prepare.call_count, 2)
        self.assertEqual(broker.close.call_count, 1)
        self.assertEqual(secret, b'')
        for call in runner.popen.call_args_list[:2]:
            self.assertEqual(call.args[0][:4], ['/usr/bin/sudo', '-k', '-A', '--'])
            self.assertIn('SUDO_ASKPASS', call.kwargs['env'])
            self.assertNotIn('DUMMY-UPDATER-TEST', str(call))
        self.assertNotIn('SUDO_ASKPASS', runner.popen.call_args_list[2].kwargs['env'])
        self.assertNotIn(SOCKET_ENV, runner.popen.call_args_list[2].kwargs['env'])

    def test_manual_mode_no_automatic_yes_or_privileged_shell_or_reboot(self):
        runner, *_ = setup_runner(saved=True);runner.execute()
        actual = [call.args[0] for call in runner.popen.call_args_list]
        flat = sum(actual, [])
        for word in ('-y','--assumeyes','--assume-yes','--allow-unauthenticated','-s','-i','sh','bash','reboot','autoremove'):
            self.assertNotIn(word, flat)
        self.assertTrue(all('shell' not in call.kwargs for call in runner.popen.call_args_list))

    def test_stop_after_first_apt_failure(self):
        runner, *_ = setup_runner((100,));result=runner.execute()
        self.assertEqual(result.code,100);self.assertEqual(result.completed,0)
        self.assertTrue(result.revoked);self.assertEqual(runner.popen.call_count,1)

    def test_stop_after_full_upgrade_failure(self):
        runner, *_ = setup_runner((0,100));result=runner.execute()
        self.assertEqual(result.code,100);self.assertEqual(result.completed,1)
        self.assertEqual(runner.popen.call_count,2);self.assertTrue(result.revoked)

    def test_flatpak_failure_is_not_success(self):
        runner, *_ = setup_runner((0,0,1));result=runner.execute()
        self.assertEqual(result.code,1);self.assertEqual(result.completed,2);self.assertTrue(result.revoked)

    def test_missing_flatpak_explicit_skip_not_install(self):
        runner, *_ = setup_runner((0,0),missing=('flatpak',));result=runner.execute()
        self.assertTrue(result.skipped_flatpak);self.assertEqual(result.completed,2)
        self.assertEqual(result.code,0);self.assertEqual(runner.popen.call_count,2)
        self.assertIn('nicht installiert',str(runner.emit.call_args_list))

    def test_missing_apt_no_execution_and_cleanup(self):
        runner, *_ = setup_runner(missing=('apt',));result=runner.execute()
        self.assertNotEqual(result.code,0);self.assertTrue(result.revoked);runner.popen.assert_not_called()

    def test_missing_saved_secret_no_fallback_or_updates(self):
        runner, _, _, store, _ = setup_runner(saved=True)
        store.lookup.side_effect=SecretError('Kein Eintrag')
        result=runner.execute()
        self.assertNotEqual(result.code,0);runner.popen.assert_not_called();self.assertTrue(result.revoked)

    def test_unsupported_askpass_no_config_modification(self):
        runner, *_ = setup_runner(saved=True)
        runner.run.return_value = NS(returncode=0,stdout=b'--help')
        result=runner.execute()
        self.assertNotEqual(result.code,0);runner.store_factory.assert_not_called();runner.popen.assert_not_called()
        self.assertIn('--askpass',str(runner.emit.call_args_list))

    def test_wrong_password_failure_no_silent_retry(self):
        runner, _, broker, _, _ = setup_runner((1,),saved=True)
        result=runner.execute()
        self.assertEqual(runner.popen.call_count,1);self.assertTrue(result.revoked)
        broker.close.assert_called_once()

    def test_failed_cleanup_is_never_success(self):
        runner, *_ = setup_runner()
        runner.run.side_effect=[NS(returncode=0), NS(returncode=0), NS(returncode=1)]
        result=runner.execute()
        self.assertEqual(result.code,1);self.assertFalse(result.revoked)
        self.assertIn('NICHT gelöscht',str(runner.emit.call_args_list))

    def test_initial_invalidation_failure_stops_before_any_auth(self):
        runner, *_ = setup_runner(saved=True)
        runner.run.return_value=NS(returncode=1)
        result=runner.execute()
        self.assertFalse(result.revoked);runner.popen.assert_not_called();runner.store_factory.assert_not_called()

    def test_interrupted_before_start_never_reads_password(self):
        runner, *_ = setup_runner(saved=True);runner.interrupt(signal.SIGINT)
        result=runner.execute()
        self.assertEqual(result.code,130);self.assertTrue(result.revoked)
        runner.popen.assert_not_called();runner.store_factory.assert_not_called()

    def test_sigint_while_child_runs_cleanup_and_no_next_step(self):
        runner, children, broker, _, _ = setup_runner((-2,),saved=True)
        def wait():
            runner.interrupt(signal.SIGINT)
            return -2
        children[0].wait.side_effect=wait
        result=runner.execute()
        self.assertEqual(result.code,130);self.assertEqual(runner.popen.call_count,1)
        children[0].send_signal.assert_called_with(signal.SIGINT)
        self.assertTrue(result.revoked);broker.close.assert_called_once()

    def test_popen_error_does_not_keep_broker(self):
        runner, _, broker, _, _ = setup_runner(saved=True)
        runner.popen.side_effect=OSError('cannot spawn')
        result=runner.execute()
        self.assertEqual(result.code,1);self.assertTrue(result.revoked)
        broker.close.assert_called_once();broker.disarm.assert_called_once()

    def test_environment_removes_injection_and_stale_credentials(self):
        raw={k:'BAD' for k in ('BASH_ENV','ENV','LD_PRELOAD','PYTHONPATH','APT_CONFIG',
             'DEBIAN_FRONTEND','SUDO_ASKPASS','SUDO_PROMPT','AURALYN_UPDATE_PASSWORD',SOCKET_ENV)}
        raw.update({'TERM':'xterm','DBUS_SESSION_BUS_ADDRESS':'unix:path=test','HOME':'/home/test'})
        env=update_environment(raw)
        self.assertNotIn('BAD',env.values())
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'],'unix:path=test')
        self.assertEqual(env['PATH'],'/usr/sbin:/usr/bin:/sbin:/bin')

    def test_return_shell_drops_update_auth_but_keeps_normal_ipc(self):
        env=shell_environment({SOCKET_ENV:'x',BROKER_PID_ENV:'123','SUDO_ASKPASS':'helper',
            'AURALYN_UPDATE_OTHER':'x','AURALYN_EVENT_FIFO':'keep','TERM':'xterm'})
        self.assertEqual(env,{'AURALYN_EVENT_FIFO':'keep','TERM':'xterm'})

    def test_revoke_timeout_returns_false_not_throw(self):
        self.assertFalse(revoke_sudo('/usr/bin/sudo',{},Mock(side_effect=subprocess.TimeoutExpired('sudo',8))))
        self.assertFalse(supports_askpass('/usr/bin/sudo',{},Mock(side_effect=OSError())))


class BrokerTests(unittest.TestCase):
    def test_private_socket_and_cleanup(self):
        dummy=bytearray(b'DUMMY')
        broker=PasswordBroker(dummy);path=Path(broker.path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700)
        self.assertTrue(stat.S_ISSOCK(path.stat().st_mode))
        broker.close()
        self.assertFalse(path.exists());self.assertFalse(path.parent.exists())
        self.assertEqual(broker._password,b'')

    def test_direct_invocation_has_no_keyring_and_no_output(self):
        result=subprocess.run(['/usr/bin/python3','-I',str(ROOT/'update_askpass.py')],
            env={'PATH':'/usr/bin:/bin'},capture_output=True,timeout=8)
        self.assertEqual(result.returncode,1);self.assertEqual(result.stdout,b'')

    def test_wrong_parent_cannot_get_password(self):
        with PasswordBroker(bytearray(b'DUMMY-NEVER-DISCLOSE')) as broker:
            broker.arm(987654321)
            result=subprocess.run(['/usr/bin/python3','-I',str(ROOT/'update_askpass.py')],
                env=broker.environment(dict(os.environ),str(ROOT/'update_askpass.py')),
                capture_output=True,timeout=8)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn(b'DUMMY-NEVER-DISCLOSE',result.stdout+result.stderr)
            self.assertFalse(broker.supplied)

    def test_authorized_child_once_per_arm_and_no_secret_environment(self):
        with PasswordBroker(bytearray(b'DUMMY-NOT-A-REAL-PASSWORD')) as broker:
            env=broker.environment(dict(os.environ),str(ROOT/'update_askpass.py'))
            self.assertNotIn('DUMMY-NOT-A-REAL-PASSWORD',str(env))
            # Simulates a sudo parent: helper is a child of THIS process.
            broker.arm(os.getpid())
            first=subprocess.run(['/usr/bin/python3','-I',str(ROOT/'update_askpass.py')],env=env,capture_output=True,timeout=8)
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertEqual(first.stdout,b'DUMMY-NOT-A-REAL-PASSWORD\n')
            self.assertTrue(broker.supplied)
            second=subprocess.run(['/usr/bin/python3','-I',str(ROOT/'update_askpass.py')],env=env,capture_output=True,timeout=8)
            self.assertNotEqual(second.returncode,0);self.assertEqual(second.stdout,b'')
            broker.prepare();broker.arm(os.getpid())
            third=subprocess.run(['/usr/bin/python3','-I',str(ROOT/'update_askpass.py')],env=env,capture_output=True,timeout=8)
            self.assertEqual(third.returncode,0)

    def test_invalid_buffers_rejected(self):
        for value in (b'',b'a\nb',b'a\x00b',b'x'*1025):
            with self.assertRaises(ValueError):PasswordBroker(bytearray(value))

    def test_cross_process_update_lock(self):
        with UpdateLock():
            with self.assertRaisesRegex(RuntimeError,'bereits'):
                with UpdateLock():pass
        with UpdateLock():pass


class ProductIntegrationTests(unittest.TestCase):
    def test_product_help_answers_new_settings_questions_without_execution(self):
        for q in ('Kann ich mein sudo Passwort speichern?', 'Wie speichere ich das Passwort für den Update Button?',
                  'Passwort vom Update Button löschen'):
            self.assertEqual(match_app_question(q).entry_id,'app.update_password')
        self.assertEqual(match_app_question('Was macht der Update Button?').entry_id,'app.update_button')

    def test_normal_systemupdate_search_keeps_old_behavior(self):
        from auralyn_terminal.smart_search import SearchEngine
        answer=SearchEngine().answer('Wie update ich mein System?',False,'qwen3:4b')
        self.assertEqual(answer.command,'sudo apt update && sudo apt upgrade')

    def test_package_installs_executable_private_helper_and_dependency(self):
        source=(ROOT/'packaging/build_deb.py').read_text()
        self.assertIn("'update_askpass.py', mode=0o755",source)
        self.assertIn('gir1.2-secret-1',source)
        self.assertNotIn('postinst',source)

    def test_header_button_is_immediately_left_of_search(self):
        tree=ast.parse((ROOT/'auralyn_terminal/app.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
        init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
        calls=[ast.unparse(n.value) for n in init.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)]
        indices=[i for i,x in enumerate(calls) if x=='header.pack_end(self.smart_button)']
        self.assertEqual(len(indices),1)
        self.assertEqual(calls[indices[0]+1],'header.pack_end(self.update_button)')

    def test_button_uses_new_tab_not_terminal_paste_or_ai(self):
        tree=ast.parse((ROOT/'auralyn_terminal/app.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='launch_updates')
        ns={'Path':Path,'os':NS(geteuid=lambda:1000)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<test>','exec'),ns)
        owner=NS(destroying=False,pages=lambda:[],add_tab=Mock(),show_error=Mock())
        self.assertTrue(ns['launch_updates'](owner))
        owner.add_tab.assert_called_once_with(str(Path.home()),update_session=True)
        source=ast.unparse(node)
        self.assertNotIn('feed_child',source);self.assertNotIn('smart_action',source)

    def test_running_update_click_focuses_existing_tab(self):
        tree=ast.parse((ROOT/'auralyn_terminal/app.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MainWindow')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='launch_updates')
        ns={'Path':Path,'os':NS(geteuid=lambda:1000)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<test>','exec'),ns)
        page=NS(update_session=True,ready=False,terminal=Mock())
        owner=NS(destroying=False,pages=lambda:[page],add_tab=Mock(),show_error=Mock(),notebook=Mock())
        self.assertFalse(ns['launch_updates'](owner));owner.add_tab.assert_not_called()
        page.terminal.grab_focus.assert_called_once()
