"""previous development version: metadata-only diagnostics and robust Web error presentation."""
from __future__ import annotations
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from auralyn_terminal import __version__
from auralyn_terminal.diagnostics import record_failure, diagnostic_path, _LIMIT
from auralyn_terminal.local_ai import AIError, Cancelled
from auralyn_terminal.smart_search import Answer, SearchEngine, SearchWorker
from auralyn_terminal.web_sources import WebSearch, WebError, public_url, DDGLinks
from test_smart_search import FakeManual
from test_smart_ui import load_ui_class, owner, W, clipboard


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'XDG_STATE_HOME': self.temp.name})
        env.start(); self.addCleanup(env.stop)

    def failure(self, message='SECRET-TEST-TOKEN file=/home/alice/private https://example.org/?key=SECRET'):
        try:
            raise NotImplementedError(message)
        except Exception as exc:
            return record_failure(exc, stage='1/2 · Web: Dokumentation suchen', web=True)

    def test_local_log_and_copied_report_contain_no_sensitive_message_or_path(self):
        report = self.failure()
        self.assertTrue(report.saved)
        for text in (report.text, diagnostic_path().read_text()):
            self.assertIn(__version__, text)
            self.assertIn('NotImplementedError', text)
            self.assertIn('test_diagnostics_fixes.py', text)
            self.assertIn('1/2 Web', text)
            for secret in ('SECRET-TEST-TOKEN', '/home/alice', 'example.org', str(Path(__file__).resolve().parent)):
                self.assertNotIn(secret, text)
        self.assertEqual(stat.S_IMODE(diagnostic_path().stat().st_mode), 0o600)

    def test_diagnostics_never_call_exception_str(self):
        class HostileError(Exception):
            def __str__(self):
                raise AssertionError('must not format arbitrary exception text')
        report = record_failure(HostileError())
        self.assertIn('HostileError', report.text)
        self.assertTrue(report.saved)

    def test_log_symlink_is_not_followed_or_truncated(self):
        target = Path(self.temp.name) / 'do-not-touch'
        target.write_text('keep me')
        path = diagnostic_path()
        path.parent.mkdir()
        path.symlink_to(target)
        report = self.failure()
        self.assertFalse(report.saved)
        self.assertIn('kann trotzdem kopiert', report.text)
        self.assertEqual(target.read_text(), 'keep me')

    def test_symlinked_app_state_directory_not_used(self):
        target = Path(self.temp.name) / 'elsewhere'
        target.mkdir()
        diagnostic_path().parent.symlink_to(target, target_is_directory=True)
        self.assertFalse(self.failure().saved)
        self.assertFalse(list(target.iterdir()))

    def test_fifo_does_not_hang_error_handling(self):
        path = diagnostic_path()
        path.parent.mkdir()
        os.mkfifo(path)
        start = time.monotonic()
        self.assertFalse(self.failure().saved)
        self.assertLess(time.monotonic() - start, 1)

    def test_log_is_bounded(self):
        path = diagnostic_path()
        path.parent.mkdir()
        path.write_bytes(b'x' * (_LIMIT + 100))
        self.assertTrue(self.failure().saved)
        self.assertLess(path.stat().st_size, _LIMIT)
        self.assertNotIn('xxxxx', path.read_text())

    def test_existing_log_permissions_tightened(self):
        self.failure()
        diagnostic_path().chmod(0o644)
        self.failure()
        self.assertEqual(stat.S_IMODE(diagnostic_path().stat().st_mode), 0o600)

    def test_stage_does_not_leak_free_text(self):
        report = record_failure(ValueError('secret'), stage='2/2 · SECRET-tool fehlt: Installationsquelle', web=True)
        self.assertIn('2/2 Lokal', report.text)
        self.assertNotIn('SECRET', report.text)
        self.assertNotIn('secret', report.text)

    def test_invalid_environment_log_path_does_not_break_diagnostics(self):
        with patch.dict(os.environ, {'XDG_STATE_HOME': '/tmp/' + 'x' * 600}):
            report = self.failure()
        self.assertFalse(report.saved)

    def test_exception_chain_records_types_not_messages(self):
        try:
            try:
                raise OSError('inner-password')
            except OSError as cause:
                raise AIError('outer-secret') from cause
        except Exception as exc:
            report = record_failure(exc)
        self.assertIn('AIError', report.text)
        self.assertIn('OSError', report.text)
        self.assertNotIn('inner-password', report.text)
        self.assertNotIn('outer-secret', report.text)


class WorkerErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'XDG_STATE_HOME': self.temp.name})
        env.start(); self.addCleanup(env.stop)

    def test_unexpected_web_error_keeps_mode_stage_and_copyable_diagnostic(self):
        engine = Mock()
        def fail(*args, **kwargs):
            kwargs['progress']('1/2 · Web: Dokumentation suchen und lesen…')
            raise NotImplementedError("Can't dup() SSLSocket instances")
        engine.answer.side_effect = fail
        results, done = [], threading.Event()
        worker = SearchWorker(lambda serial, answer: (results.append(answer), done.set()), engine=engine)
        try:
            worker.submit(1, 'PRIVATE-QUESTION', True, 'test:small', web_enabled=True)
            self.assertTrue(done.wait(2))
        finally:
            worker.close(); worker._thread.join(2)
        a = results[0]
        self.assertEqual(a.state, 'unavailable')
        self.assertFalse(a.command or a.executable)
        self.assertIn('KI + Web', a.source)
        self.assertNotIn('Offline', a.source)
        self.assertIn('NotImplementedError', a.note)
        self.assertIn('1/2 Web', a.diagnostic)
        self.assertNotIn('PRIVATE-QUESTION', a.diagnostic)
        self.assertNotIn('Anfrage Abgelehnt', a.text)

    def test_known_model_error_has_copyable_diagnostic_and_usable_error_message(self):
        research = Mock()
        research.answer.side_effect = AIError('Lokales Ollama nicht erreichbar.')
        engine = SearchEngine(manual=FakeManual(), web_research=research)
        a = engine.answer('Was ist mein NVIDIA-Treiber?', True, 'test:small', web_enabled=True)
        self.assertEqual(a.state, 'unavailable')
        self.assertIn('Ollama nicht erreichbar', a.note)
        self.assertIn('KI + Web', a.source)
        self.assertIn('AIError', a.diagnostic)
        self.assertFalse(a.command or a.executable)

    def test_cancelled_worker_does_not_create_error_log(self):
        engine = Mock()
        engine.answer.side_effect = Cancelled('cancelled')
        results = []
        worker = SearchWorker(lambda *v: results.append(v), engine=engine)
        worker.submit(1, 'test', True, 'test:small', web_enabled=True)
        time.sleep(.05)
        worker.close(); worker._thread.join(2)
        self.assertFalse(results)
        self.assertFalse(diagnostic_path().exists())


class ErrorUITests(unittest.TestCase):
    def setUp(self):
        Popover, self.worker, _ = load_ui_class('SmartPopover')
        self.owner = owner()
        self.view = Popover(self.owner, W())
        self.view.open()
        self.addCleanup(self.view.destroy)

    def send_error(self):
        self.view.entry.set_text('Was ist mein NVIDIA-Treiber?')
        self.view._search()
        a = Answer('Technischer Fehler', 'Suche unterbrochen.', state='unavailable',
                   source='KI + Web', note='NotImplementedError', diagnostic='TESTDIAG (no question)')
        self.view._receive(self.view._serial, a)

    def test_error_button_copies_only_diagnostic_and_does_not_execute(self):
        self.send_error()
        self.assertTrue(self.view.error_copy_button.visible)
        self.assertFalse(self.view.execute_button.visible)
        self.view._copy_error()
        clipboard.set_text.assert_called_with('TESTDIAG (no question)', -1)
        self.owner.launch_smart_action.assert_not_called()

    def test_error_button_hidden_without_failure_and_on_edit(self):
        self.assertFalse(self.view.error_copy_button.visible)
        self.send_error()
        self.view.entry.set_text('Neue Frage')
        self.assertFalse(self.view.error_copy_button.visible)
        self.assertIsNone(self.view._current_answer())

    def test_success_does_not_retain_old_error_button(self):
        self.send_error()
        self.view._receive(self.view._serial, Answer('OK', 'Alles gut.'))
        self.assertFalse(self.view.error_copy_button.visible)

    def test_failed_search_allows_searching_again_without_restart(self):
        self.send_error()
        self.assertTrue(self.view.search_button.get_sensitive())
        self.assertFalse(self.view.spinner.running)
        self.view._search()
        self.assertEqual(self.worker.submit.call_count, 2)
        self.assertFalse(self.view.error_copy_button.visible)


class WebRobustnessTests(unittest.TestCase):
    def test_unicode_documentation_url_is_ascii_safe(self):
        url = public_url('https://example.org/über?q=größer&tag=c%2B%2B')
        self.assertEqual(url, 'https://example.org/%C3%BCber?q=gr%C3%B6%C3%9Fer&tag=c%2B%2B')
        url.encode('ascii')

    def test_invalid_url_inside_search_results_skipped_not_global_crash(self):
        p = DDGLinks()
        p.feed('<a class="result__a" href="https://[invalid">bad</a>'
               '<a class="result__a" href="https://example.org/docs">ok</a>')
        self.assertEqual(p.links, [('https://example.org/docs', 'ok')])

    def test_succesful_search_but_failed_pages_marked_unavailable(self):
        transport = Mock()
        transport.get.side_effect = [('https://html.duckduckgo.com/',
            '<a class="result__a" href="https://example.org/docs">Documentation</a>', 'text/html'),
            WebError('TLS-Zertifikat ungültig')]
        batch = WebSearch(transport).search('something docs', [], {}, threading.Event())
        self.assertTrue(batch.unavailable)
        self.assertFalse(batch.sources)
        self.assertTrue(any('TLS' in n for n in batch.notes))

    def test_direct_official_document_is_tried_before_arbitrary_result(self):
        urls = []
        def get(url, *args, **kwargs):
            urls.append(url)
            if 'duckduckgo' in url:
                return url, '<a class="result__a" href="https://blog.example.org/docs">blog</a>', 'text/html'
            return url, '<html><h1>nvidia-smi</h1><p>nvidia-smi shows the driver version of the NVIDIA GPU. More documentation follows here.</p></html>', 'text/html'
        WebSearch(Mock(get=get)).search('NVIDIA driver version', [{'command':'nvidia-smi', 'manual':'nvidia-smi'}],
                                       {'id':'ubuntu','codename':'resolute'}, threading.Event())
        self.assertEqual(urls[1], 'https://docs.nvidia.com/deploy/nvidia-smi/index.html')


if __name__ == '__main__':
    unittest.main()
