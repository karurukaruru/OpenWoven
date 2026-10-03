from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.client
import json
import tempfile
import threading
import unittest

from adaptive_companion.role_package import import_package
from adaptive_companion.turns import composer_gate
from openwoven.web import WebApp, WebServer, MAX_BODY, STATIC


class WebClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = WebApp(self.tmp.name)
        self.server = WebServer(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.headers = {'Cookie': 'openwoven_session=' + self.app.token,
                        'Origin': self.server.origin, 'X-OpenWoven': self.app.token,
                        'Content-Type': 'application/json'}
        composer_gate.states.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.app.close()
        self.tmp.cleanup()
        composer_gate.states.clear()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        connection.request(method, path, json.dumps(data) if data is not None else None,
                           self.headers if headers is None else headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_page_assets_headers_and_authenticated_state(self):
        status, body, headers = self.request('GET', '/', headers={})
        self.assertEqual(200, status)
        self.assertIn(b'OpenWoven', body)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        for path in ('/app.js', '/style.css'):
            self.assertEqual(200, self.request('GET', path, headers={})[0])
        self.assertEqual(200, self.request('GET', '/api/state')[0])
        self.assertEqual(403, self.request('GET', '/api/state', headers={})[0])
        self.assertEqual(404, self.request('GET', '/../web.py')[0])

    def test_cross_origin_host_and_csrf_are_blocked(self):
        for headers in ({**self.headers, 'Origin': 'https://hostile.example'},
                        {**self.headers, 'Host': 'hostile.example'},
                        {**self.headers, 'X-OpenWoven': 'wrong'},
                        {**self.headers, 'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(403, self.request('POST', '/api/send', {'text': 'hello'}, headers)[0])
        self.assertEqual(0, self.app.core.store.count_messages())

    def test_bounded_body_and_invalid_types_do_not_mutate(self):
        self.assertEqual(400, self.request('POST', '/api/send', {'text': 42})[0])
        status = self.request('POST', '/api/send', {}, {**self.headers, 'Content-Length': str(MAX_BODY + 1)})[0]
        self.assertEqual(400, status)

    def test_roles_switch_keep_chats_separate_and_export_only_character(self):
        self.app.command('send', {'text': 'private legacy message'})
        saved = self.app.command('create', {'name': 'Case', 'description': 'calm'})
        self.app.command('switch', {'id': saved['id']})
        self.assertEqual([], self.app.state()['messages'])
        self.app.command('send', {'text': 'private second message'})
        self.app.command('switch', {'id': 'legacy'})
        self.assertEqual(['private legacy message'], [m['content'] for m in self.app.state()['messages']])
        old = self.app.core.store.list_scheduled_messages('cancelled')
        self.assertTrue(any(x.topic.startswith('reply:') for x in old))
        raw = self.request('GET', '/api/export?id=' + saved['id'])[1]
        self.assertEqual('Case', import_package(raw)['role']['name'])
        self.assertNotIn('private', str(import_package(raw)))

    def test_composer_accepts_boolean_only_without_transmitting_draft(self):
        self.assertEqual(200, self.request('POST', '/api/composer', {'has_draft': True})[0])
        self.assertFalse(composer_gate.idle('default', 0))
        self.assertEqual(400, self.request('POST', '/api/composer', {'has_draft': 'false'})[0])

    def test_schedule_uses_core_and_saves_exact_content(self):
        target = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        status, raw, _ = self.request('POST', '/api/schedule', {'text': '你好', 'when': target, 'generate': False})
        self.assertEqual(200, status)
        self.assertEqual('你好', json.loads(raw)['draft_intent'])
        self.assertEqual(1, len(self.app.state()['scheduled']))

    def test_key_is_session_only_and_not_sent_to_browser_or_disk(self):
        # No provider constructed/requested: test the state and persistence boundary directly.
        self.app.api_key = 'synthetic-key-not-real'
        self.app._save_settings()
        self.assertNotIn(self.app.api_key, json.dumps(self.app.state()))
        self.assertNotIn(self.app.api_key, (self.app.root / 'settings.json').read_text())
        self.app.api_key = ''

    def test_untrusted_text_uses_text_content_not_html_and_assets_exist(self):
        script = (STATIC / 'app.js').read_text(encoding='utf-8')
        self.assertNotIn('innerHTML', script)
        self.assertNotIn('localStorage', script)
        self.assertIn('el.textContent=text', script)

    def test_old_learning_error_does_not_leave_switch_with_a_closed_core(self):
        saved = self.app.command('create', {'name': 'Case', 'description': 'calm'})
        self.app.core.learning._errors.append(RuntimeError('synthetic old observer failure'))
        self.app.command('switch', {'id': saved['id']})
        self.assertEqual(saved['id'], self.app.state()['settings']['active'])


if __name__ == '__main__':
    unittest.main()
