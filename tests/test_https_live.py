"""Real TLS/HTTP regression tests, no fake SSL sockets.

Only DNS/address routing is redirected to a loopback fixture. A temporary
certificate is trusted by the test client; hostname/certificate checks stay on.
No public Internet, NVIDIA GPU or real model inference is implied by these tests.
"""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

from auralyn_terminal.web_sources import PublicHTTPS, WebError, WebSearch
from auralyn_terminal.local_ai import Cancelled


class TLSFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='auralyn-real-tls-')
        self.root = Path(self.temp.name)
        self.cert = self.root / 'certificate.pem'
        self.key = self.root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-days', '1', '-subj', '/CN=docs.example.org',
                        '-addext', 'subjectAltName=DNS:docs.example.org,DNS:html.duckduckgo.com,DNS:docs.nvidia.com,DNS:manpages.ubuntu.com,DNS:ollama.com',
                        '-addext', 'basicConstraints=critical,CA:TRUE',
                        '-addext', 'keyUsage=critical,digitalSignature,keyCertSign,cRLSign',
                        '-keyout', str(self.key), '-out', str(self.cert)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=12)
        self.requests = []
        self.received = threading.Event()
        self.release = threading.Event()
        self.create_connection = socket.create_connection
        self.create_context = ssl.create_default_context
        self.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_context.load_cert_chain(self.cert, self.key)
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *args):
                pass
            def do_GET(self):
                fixture.requests.append((self.headers.get('Host'), self.path))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/docs')
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    return
                if self.path == '/redirect-private':
                    self.send_response(302)
                    self.send_header('Location', 'https://127.0.0.1/private')
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    return
                if self.path.startswith('/html/'):
                    self.send_response(202)
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    return
                if self.path == '/404':
                    self.send_response(404)
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    return
                payload = (b'<html><head><title>NVIDIA-SMI documentation (TEST)</title></head>'
                           b'<body><h1>nvidia-smi</h1><p>This is a local test fixture, not a retrieved public source. '
                           b'nvidia-smi reports the Driver Version. Use nvidia-smi --query-gpu=driver_version '
                           b'--format=csv,noheader to display the driver version.</p></body></html>')
                if self.path == '/slow':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.flush()
                    fixture.received.set()
                    fixture.release.wait(5)
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                try:
                    self.wfile.write(payload)
                except (OSError, ssl.SSLError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.socket = self.server_context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @contextmanager
    def route(self, *, trust=True):
        contexts = []
        def context(*args, **kwargs):
            if trust:
                kwargs['cafile'] = str(self.cert)
            ctx = self.create_context(*args, **kwargs)
            assert ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED
            contexts.append(ctx)
            return ctx
        def connect(address, *args, **kwargs):
            if address == ('93.184.216.34', 443):
                address = self.server.server_address
            return self.create_connection(address, *args, **kwargs)
        with patch.object(PublicHTTPS, '_addresses', return_value=['93.184.216.34']), \
             patch('ssl.create_default_context', side_effect=context), \
             patch('socket.create_connection', side_effect=connect):
            yield contexts

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()


@unittest.skipUnless(shutil.which('openssl'), 'openssl required for temporary test TLS certificate')
class RealHTTPSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = TLSFixture()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def setUp(self):
        self.fixture.requests.clear()
        self.fixture.received.clear()
        self.fixture.release.clear()
        self.client = PublicHTTPS()
        self.cancel = threading.Event()

    def test_actual_https_get_does_not_duplicate_ssl_socket(self):
        # This fails on previous development version: NotImplementedError: Can't dup() SSLSocket instances.
        with self.fixture.route():
            url, body, kind = self.client.get('https://docs.example.org/docs', self.cancel)
        self.assertEqual(url, 'https://docs.example.org/docs')
        self.assertEqual(kind, 'text/html')
        self.assertIn('nvidia-smi', body)
        self.assertEqual(self.fixture.requests, [('docs.example.org', '/docs')])
        self.assertIsNone(self.client._connection)

    def test_real_tls_redirect_remains_verified(self):
        with self.fixture.route() as contexts:
            url, body, kind = self.client.get('https://docs.example.org/redirect', self.cancel)
        self.assertEqual(url, 'https://docs.example.org/docs')
        self.assertGreaterEqual(len(contexts), 2)
        self.assertIn('nvidia-smi', body)

    def test_untrusted_certificate_rejected(self):
        with self.fixture.route(trust=False), self.assertRaises(WebError):
            self.client.get('https://docs.example.org/docs', self.cancel)
        self.assertFalse(self.fixture.requests)

    def test_wrong_hostname_rejected(self):
        with self.fixture.route(), self.assertRaises(WebError):
            self.client.get('https://wrong.example.org/docs', self.cancel)
        self.assertFalse(self.fixture.requests)

    def test_real_tls_redirect_to_private_address_rejected(self):
        with self.fixture.route(), self.assertRaises(WebError):
            self.client.get('https://docs.example.org/redirect-private', self.cancel)
        self.assertEqual(len(self.fixture.requests), 1)

    def test_http_error_is_readable_not_generic_internal_error(self):
        with self.fixture.route(), self.assertRaisesRegex(WebError, '404'):
            self.client.get('https://docs.example.org/404', self.cancel)

    def test_real_connection_close_body_can_be_cancelled(self):
        errors = []
        def request():
            try:
                self.client.get('https://docs.example.org/slow', self.cancel, timeout=5)
            except Exception as exc:
                errors.append(exc)
        with self.fixture.route():
            thread = threading.Thread(target=request, daemon=True)
            thread.start()
            self.assertTrue(self.fixture.received.wait(2), 'real TLS request not sent')
            start = time.monotonic()
            self.cancel.set()
            self.client.cancel()
            thread.join(2)
            self.fixture.release.set()
        self.assertFalse(thread.is_alive(), 'cancellation failed to wake body read')
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], Cancelled)
        self.assertIsNone(self.client._connection)

    def test_real_tls_body_timeout_is_bounded(self):
        with self.fixture.route():
            start = time.monotonic()
            with self.assertRaises(WebError):
                self.client.get('https://docs.example.org/slow', self.cancel, timeout=.25)
            self.fixture.release.set()
        self.assertLess(time.monotonic() - start, 2)
        self.assertIsNone(self.client._connection)

    def test_real_tls_search_falls_back_from_202_to_online_docs(self):
        with self.fixture.route():
            batch = WebSearch(self.client).search('NVIDIA driver version nvidia-smi',
                [{'command': 'nvidia-smi', 'manual': 'nvidia-smi'}],
                {'id': 'ubuntu', 'codename': 'resolute', 'version': '26.04'}, self.cancel)
        self.assertTrue(batch.sources)
        self.assertTrue(any(s.url == 'https://docs.nvidia.com/deploy/nvidia-smi/index.html' for s in batch.sources))
        self.assertTrue(any('202' in n for n in batch.notes))
        self.assertFalse(batch.unavailable)
        self.assertTrue(any(s.mentions('nvidia-smi') for s in batch.sources))

@unittest.skipUnless(shutil.which('openssl'), 'openssl required for temporary test TLS certificate')
class RealCombinedFlowTests(unittest.TestCase):
    """Real model HTTP + real documentation TLS + real temp PATH + SearchWorker.

    The model responses and served web documents are fixtures, not inference
    or Internet search results. All transports and parsers are production code.
    """
    def test_screenshot_question_entire_worker_flow_over_http_and_tls(self):
        from auralyn_terminal.capabilities import CapabilityReader
        from auralyn_terminal.local_ai import OllamaClient
        from auralyn_terminal.web_command_ai import WebCommandResearch
        from auralyn_terminal.smart_search import SearchEngine, SearchWorker
        from test_local_ai import FakeServer, MODEL, DETAILS, chat
        from test_web_research import plan, choice, final, DISTRO
        from test_smart_search import FakeManual
        fixture = TLSFixture()
        self.addCleanup(fixture.close)
        responses = iter([plan(), choice(), final('nvidia-smi --query-gpu=driver_version --format=csv,noheader')])
        def route(handler):
            if handler.path == '/api/chat':
                value = chat(json.dumps(next(responses)))
            else:
                value = {'/api/tags': {'models': [MODEL]}, '/api/show': DETAILS}[handler.path]
            payload = json.dumps(value).encode()
            handler.send_response(200)
            handler.send_header('Content-Length', str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
        with tempfile.TemporaryDirectory() as temp, FakeServer(route) as model, fixture.route(), \
             patch.dict(os.environ, {'PATH': temp, 'XDG_STATE_HOME': temp}):
            root = Path(temp)
            executable = root / 'nvidia-smi'
            marker = root / 'PROGRAM_WAS_EXECUTED'
            executable.write_text('#!/bin/sh\necho SHOULD_NOT_RUN > ' + str(marker) + '\n')
            executable.chmod(0o755)
            client = OllamaClient()
            reader = CapabilityReader(roots=[root / 'manuals'])
            research = WebCommandResearch(client, reader, web=WebSearch(PublicHTTPS()), distro=DISTRO)
            engine = SearchEngine(client=client, manual=FakeManual(), capabilities=reader, web_research=research)
            delivered = []
            ready = threading.Event()
            stages = []
            worker = SearchWorker(lambda serial, answer: (delivered.append(answer), ready.set()),
                                  engine=engine, progress=lambda serial, text: stages.append(text))
            try:
                worker.submit(1, 'Was ist mein NVIDIA-Treiber?', True, 'test:small', web_enabled=True)
                self.assertTrue(ready.wait(8), 'worker did not finish real transports')
            finally:
                worker.close()
                worker._thread.join(2)
            answer = delivered[0]
            self.assertEqual(answer.command, 'nvidia-smi --query-gpu=driver_version --format=csv,noheader')
            self.assertIn('Web + Lokal', answer.source)
            self.assertTrue(answer.executable)
            self.assertFalse(answer.diagnostic)
            self.assertIn('im Suchpfad gefunden', answer.evidence)
            self.assertIn('1/2 Web', answer.evidence)
            self.assertTrue(any('1/2' in s for s in stages))
            self.assertTrue(any('2/2' in s for s in stages))
            self.assertEqual([p for p, _ in model.requests].count('/api/chat'), 3)
            self.assertTrue(any(host == 'docs.nvidia.com' for host, _ in fixture.requests))
            self.assertFalse(marker.exists(), 'search must never run nvidia-smi')


if __name__ == '__main__':
    unittest.main()
