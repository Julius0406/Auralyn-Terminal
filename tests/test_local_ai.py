"""Ollama adapter tests using recorded-shaped fixtures and a loopback HTTP server.

No real model inference. No external requests. Fixtures include malicious output.
"""
import contextlib
import http.server
import json
import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

from auralyn_terminal.local_ai import (AIError, Cancelled, OllamaClient, local_models,
                                      valid_model_name, json_object, MAX_RESPONSE)

MODEL = {'name': 'test:small', 'model': 'test:small', 'size': 2_000_000,
         'details': {'format': 'gguf', 'parameter_size': '4B'}}
DETAILS = {'capabilities': ['completion'], 'model_info': {'general.architecture': 'qwen3',
                                                       'qwen3.block_count': 32}}

def chat(content='{"id":"system.update"}'):
    return {'done': True, 'message': {'role': 'assistant', 'content': content}}


class AdapterTests(unittest.TestCase):
    def client(self, output=None, models=None, details=None):
        client = OllamaClient()
        client.request = Mock(side_effect=[{'models': [MODEL]} if models is None else models,
                                          DETAILS if details is None else details,
                                          chat() if output is None else output])
        return client

    def test_installed_local_model_and_valid_catalogue_id(self):
        client = self.client()
        self.assertEqual(client.choose('Wie update ich Ubuntu?', 'test:small', threading.Event()), 'system.update')
        calls = client.request.call_args_list
        self.assertEqual([c.args[0] for c in calls], ['/api/tags', '/api/show', '/api/chat'])
        body = calls[2].args[1]
        self.assertIs(body['stream'], False)
        self.assertIs(body['think'], False)
        self.assertEqual(body['keep_alive'], 0)
        self.assertEqual(body['options']['temperature'], 0)
        self.assertEqual(set(body['format']['properties']), {'id'})
        self.assertFalse(body['format']['additionalProperties'])
        self.assertNotIn('tools', body)

    def test_request_context_is_only_catalogue_and_typed_question(self):
        client = self.client()
        with patch.dict(os.environ, {'SUPER_SECRET_TEST': 'SECRET_PASSWORD_MUST_NOT_BE_SENT'}):
            client.choose('Wie update ich Ubuntu?', 'test:small', threading.Event())
        body = client.request.call_args_list[2].args[1]
        self.assertEqual(len(body['messages']), 2)
        self.assertEqual(body['messages'][1], {'role': 'user', 'content': 'Wie update ich Ubuntu?'})
        self.assertNotIn('SECRET_PASSWORD_MUST_NOT_BE_SENT', json.dumps(body))
        self.assertNotIn('history', body)
        self.assertNotIn('files', body)

    def test_ai_may_reject(self):
        self.assertEqual(self.client(chat('{"id":"reject"}')).choose('Linux?', 'test:small', threading.Event()), 'reject')

    def test_model_cannot_return_arbitrary_commands(self):
        for content in ('{"command":"sudo rm -rf /"}', '{"id":"system.update","command":"rm -rf /"}',
                        '{"id":"$(touch /tmp/never)"}', '{"id":false}', '[]',
                        '```json\n{"id":"system.update"}\n```',
                        '{"id":"system.update","id":"reject"}', '{"id":["system.update"]}',
                        '{"text":"Elon Musk is..."}', '<think>text</think>{"id":"system.update"}'):
            with self.subTest(content=content):
                with self.assertRaises(AIError):
                    self.client(chat(content)).choose('Wie update ich Ubuntu?', 'test:small', threading.Event())

    def test_incomplete_response_rejected(self):
        for value in ({'done': False, 'message': {'role': 'assistant', 'content': '{"id":"system.update"}'}},
                      {'done': True}, {'done': True, 'message': {'role': 'user', 'content': '{}'}},
                      {'done': True, 'message': {'role': 'assistant', 'content': '{}', 'tool_calls': ['bad']}}):
            with self.assertRaises(AIError):
                self.client(value).choose('Wie update ich Ubuntu?', 'test:small', threading.Event())

    def test_missing_model_never_generates_or_pulls(self):
        client = self.client(models={'models': []})
        with self.assertRaisesRegex(AIError, 'nicht installiert'):
            client.choose('Wie update ich Ubuntu?', 'test:small', threading.Event())
        self.assertEqual(client.request.call_count, 1)

    def test_remote_model_never_receives_question(self):
        client = self.client(details={**DETAILS, 'remote_host': 'https://ollama.com'})
        with self.assertRaisesRegex(AIError, 'Remote'):
            client.choose('Wie update ich Ubuntu?', 'test:small', threading.Event())
        self.assertEqual(client.request.call_count, 2)
        self.assertNotIn('Wie update ich Ubuntu?', repr(client.request.call_args_list))

    def test_embeddings_or_unknown_metadata_rejected(self):
        for details in ({'capabilities': ['embedding'], 'model_info': {'x': 1}},
                        {'capabilities': ['completion'], 'model_info': {}}, {}):
            client = self.client(details=details)
            with self.assertRaises(AIError):
                client.choose('Wie update ich Ubuntu?', 'test:small', threading.Event())
            self.assertEqual(client.request.call_count, 2)

    def test_invalid_model_names_rejected_before_network(self):
        for name in ('remote-cloud', 'QWEN-CLOUD', 'https://example/model', '../model', 'a;rm',
                     'a\nmodel', '', None, 42, 'a' * 121, 'a:b:c'):
            client = self.client()
            with self.assertRaises(AIError):
                client.choose('Wie update ich Ubuntu?', name, threading.Event())
            client.request.assert_not_called()
        for name in ('qwen3:4b', 'test/small:latest', 'my-model', 'qwen3:4b-q4_K_M'):
            self.assertTrue(valid_model_name(name))

    def test_model_list_excludes_remote_and_nonlocal_stubs(self):
        examples = [MODEL, {**MODEL, 'name': 'remote:cloud'}, {**MODEL, 'name': 'bad:tag', 'remote_model': 'x'},
                    {**MODEL, 'name': 'stub:latest', 'size': 50}, {'name': 'invalid'},
                    {**MODEL, 'name': 'nested:latest', 'details': {'format': 'gguf', 'remote_host': 'x'}}]
        self.assertEqual(local_models({'models': examples}), ['test:small'])

    def test_invalid_json_and_output_limits(self):
        for value in (b'[]', b'null', b'not json', b'{"x":1,"x":2}', b'\xff'):
            with self.assertRaises(AIError):
                json_object(value)
        with self.assertRaises(AIError):
            json_object(b' ' * (MAX_RESPONSE + 1))

    def test_api_path_allowlist(self):
        with self.assertRaises(AIError), patch('http.client.HTTPConnection') as connection:
            OllamaClient().request('/api/pull', {'name': 'anything'})
        connection.assert_not_called()


class FakeServer:
    """Only listens on an ephemeral loopback port, never an external address."""
    def __init__(self, route=None):
        self.requests = []
        self.entered = threading.Event()
        self.route = route
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.reply()
            def do_POST(self):
                self.reply()
            def reply(self):
                length=int(self.headers.get('Content-Length', '0'))
                body=self.rfile.read(length) if length else b''
                fixture.requests.append((self.path, json.loads(body) if body else None))
                fixture.entered.set()
                if fixture.route:
                    fixture.route(self)
                    return
                value = {'/api/tags': {'models': [MODEL]}, '/api/show': DETAILS,
                         '/api/chat': chat()}[self.path]
                data=json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
    def __enter__(self):
        self.thread.start()
        self.patch=patch('auralyn_terminal.local_ai.PORT', self.server.server_address[1])
        self.patch.start()
        return self
    def __exit__(self, *args):
        self.patch.stop(); self.server.shutdown(); self.server.server_close(); self.thread.join(2)


class RealLoopbackHTTPTests(unittest.TestCase):
    def test_real_socket_roundtrip_ignores_proxy_environment(self):
        with FakeServer() as server, patch.dict(os.environ, {'HTTP_PROXY': 'http://never.invalid:1',
                                                            'ALL_PROXY': 'http://never.invalid:1'}):
            result=OllamaClient().choose('Wie update ich Ubuntu?', 'test:small', threading.Event())
        self.assertEqual(result, 'system.update')
        self.assertEqual([p for p,b in server.requests], ['/api/tags', '/api/show', '/api/chat'])

    def test_redirect_is_not_followed(self):
        def route(handler):
            handler.send_response(302); handler.send_header('Location', 'http://never.invalid/api/chat'); handler.end_headers()
        with FakeServer(route) as server, self.assertRaisesRegex(AIError, 'HTTP 302'):
            OllamaClient().request('/api/tags')
        self.assertEqual(len(server.requests), 1)

    def test_absolute_deadline_during_slow_body(self):
        def route(handler):
            handler.send_response(200); handler.send_header('Content-Length', '500'); handler.end_headers()
            try:
                for _ in range(100):
                    handler.wfile.write(b' '); handler.wfile.flush(); time.sleep(.04)
            except (BrokenPipeError, ConnectionResetError):
                pass
        with FakeServer(route):
            before=time.monotonic()
            with self.assertRaises(AIError):
                OllamaClient().request('/api/tags', timeout=.15)
            self.assertLess(time.monotonic()-before, .8)

    def test_cancellation_interrupts_waiting_for_headers(self):
        def route(handler):
            time.sleep(.6)
            handler.send_response(200); handler.end_headers()
        with FakeServer(route) as server:
            client=OllamaClient(); cancelled=threading.Event(); errors=[]
            def call():
                try:
                    client.request('/api/tags', cancelled=cancelled)
                except AIError as error:
                    errors.append(error)
            thread=threading.Thread(target=call, daemon=True); thread.start()
            self.assertTrue(server.entered.wait(1))
            cancelled.set(); client.cancel(); thread.join(.5)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(errors[0], Cancelled)

    def test_cancellation_interrupts_waiting_for_body(self):
        def route(handler):
            handler.send_response(200); handler.send_header('Content-Length', '100'); handler.end_headers()
            try:
                handler.wfile.write(b'{'); handler.wfile.flush(); time.sleep(.6)
            except (BrokenPipeError, ConnectionResetError):
                pass
        with FakeServer(route) as server:
            client=OllamaClient(); cancelled=threading.Event(); errors=[]
            def call():
                try:
                    client.request('/api/tags', cancelled=cancelled)
                except AIError as error:
                    errors.append(error)
            thread=threading.Thread(target=call, daemon=True); thread.start()
            self.assertTrue(server.entered.wait(1)); time.sleep(.05)
            cancelled.set(); client.cancel(); thread.join(.5)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(errors[0], Cancelled)


if __name__ == '__main__':
    unittest.main()
