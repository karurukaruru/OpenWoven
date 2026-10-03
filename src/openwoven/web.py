"""Local browser client: standard-library HTTP server, same Core and role format."""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit, parse_qs
import uuid

from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LocalCompanionProvider, OpenAICompatibleProvider
from adaptive_companion.persona import build_persona
from adaptive_companion.role_package import RoleLibrary, import_package, export_package, stored_role_facts
from adaptive_companion.turns import composer_gate

MAX_BODY = 12 * 1024 * 1024
STATIC = Path(__file__).with_name('static')


class WebApp:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.roles = RoleLibrary(self.root / 'roles')
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.next_maintenance = time.monotonic() + 3600
        self.token = secrets.token_urlsafe(32)
        self.settings = {'language': 'zh-CN', 'turn_idle_seconds': 20,
                         'base_url': 'https://api.openai.com/v1', 'model': '', 'active': 'legacy'}
        settings_file = self.root / 'settings.json'
        if settings_file.exists():
            saved = json.loads(settings_file.read_text(encoding='utf-8'))
            self.settings.update({key: saved[key] for key in self.settings if key in saved})
        self.api_key = ''  # Session-only: never written to disk or returned in responses.
        if not self.roles.path('legacy').exists():
            self.roles.save('legacy', {'name': '', 'description': '', 'preset': 'companion'}, [])
        self.core = None
        self._open(self.settings['active'])

    def _open(self, role_id):
        item = self.roles.read(role_id)
        persona = {**item['role'], 'character_id': role_id, 'language': self.settings['language']}
        provider = OpenAICompatibleProvider(base_url=self.settings['base_url'], api_key=self.api_key,
                                            model=self.settings['model']) if self.api_key else LocalCompanionProvider()
        database = self.root / ('adaptive_companion.db' if role_id == 'legacy' else f'role_{role_id}.db')
        core = CompanionCore(str(database), provider=provider, persona=build_persona(persona),
                             turn_idle_seconds=self.settings['turn_idle_seconds'],
                             memory_zone_name=None)
        try:
            core.character_book.seed(item['facts'])
            core.context_builder.clock = lambda: datetime.now().astimezone().isoformat()
        except Exception:
            core.close()
            raise
        self.core = core
        self.settings['active'] = role_id

    def _save_settings(self):
        temporary = self.root / 'settings.tmp'
        temporary.write_text(json.dumps(self.settings), encoding='utf-8')
        temporary.replace(self.root / 'settings.json')

    def _save_role(self):
        item = self.roles.read(self.settings['active'])
        self.roles.save(item['id'], item['role'], item['facts'], self.core.character_book.character_id)

    def switch(self, role_id):
        self.roles.read(role_id)  # Validate target before stopping the active role.
        old = self.settings['active']
        self._save_role()
        if old != role_id:
            for item in self.core.store.list_scheduled_messages('pending', limit=None):
                if item.topic.startswith('reply:'):
                    self.core.store.update_scheduled_status(item.id, 'cancelled')
                    for source in item.source_memory_ids:
                        self.core.store.update_message_status(source, 'failed', 'Role switched; reply cancelled')
                    self.core._discard_cached_turn(item.id, 'role switched')
        self.core.learning.wait(raise_errors=False)
        self.core.close()
        try:
            self._open(role_id)
            self._save_settings()
        except Exception:
            if self.core is not None:
                self.core.close()
            self._open(old)
            raise
        composer_gate.note('default', False)

    def state(self):
        messages = self.core.store.list_messages('default', 300)
        plans = self.core.store.delivery_plans_for([m.id for m in messages])
        return {'settings': self.settings, 'configured': bool(self.api_key), 'csrf': self.token,
                'roles': self.roles.list(), 'messages': [{**asdict(m), 'delivery_plan': plans.get(m.id)} for m in messages],
                'scheduled': [asdict(m) for m in self.core.store.list_scheduled_messages('pending', 50)]}

    def command(self, action, data):
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        if action == 'send':
            text = data.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                raise ValueError('Message must contain 1–12000 characters')
            composer_gate.note('default', False)
            return self.core.queue_user_turn(text, uuid.uuid4().hex)
        if action == 'retry':
            message_id = data.get('id')
            if not isinstance(message_id, str) or len(message_id) > 80:
                raise ValueError('Invalid message ID')
            return self.core.retry_message(message_id)
        if action == 'preview':
            value = data.get('file')
            if not isinstance(value, str) or len(value) > 11200000:
                raise ValueError('Role file too large')
            return import_package(base64.b64decode(value, validate=True))
        if action == 'import':
            return self.roles.add(data)
        if action == 'create':
            return self.roles.add({'role': data, 'facts': []})
        if action == 'switch':
            self.switch(data.get('id'))
            return {'ok': True}
        if action == 'settings':
            language = data.get('language', self.settings['language'])
            idle = data.get('turn_idle_seconds', self.settings['turn_idle_seconds'])
            endpoint = data.get('base_url', self.settings['base_url'])
            model = data.get('model', self.settings['model'])
            key = data.get('api_key', self.api_key)
            url = urlsplit(endpoint) if isinstance(endpoint, str) else None
            if language not in ('zh-CN', 'zh-TW', 'ja', 'en-US') or type(idle) is not int or not 10 <= idle <= 60:
                raise ValueError('Invalid language or wait interval')
            if url is None or url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.fragment or url.query:
                raise ValueError('Invalid model endpoint')
            if not isinstance(model, str) or len(model) > 120 or not isinstance(key, str) or len(key) > 4096 or (key and not model.strip()):
                raise ValueError('A model name is required when an API key is set')
            old_settings, old_key = self.settings.copy(), self.api_key
            self.settings = {**self.settings, 'language': language, 'turn_idle_seconds': idle,
                             'base_url': endpoint.rstrip('/'), 'model': model.strip()}
            self.api_key = key
            try:
                self.switch(self.settings['active'])
            except Exception:
                self.settings, self.api_key = old_settings, old_key
                self.core.close()
                self._open(old_settings['active'])
                raise
            return {'ok': True}
        if action == 'schedule':
            text, when = data.get('text'), data.get('when')
            if not isinstance(text, str) or not 1 <= len(text) <= 600 or not isinstance(when, str):
                raise ValueError('Invalid scheduled message')
            return self.core.schedule_custom(text, when, bool(data.get('generate')))
        raise ValueError('Unknown command')

    def tick(self):
        while not self.stop.wait(1):
            try:
                with self.lock:
                    for item in self.core.store.list_scheduled_messages('pending', 50):
                        if datetime.fromisoformat(item.scheduled_at) <= datetime.now().astimezone():
                            self.core.execute_scheduled(item.id)
                    if self.api_key:
                        self.core.proactive.plan_check_in('default')
                    if time.monotonic() >= self.next_maintenance:
                        self.core.learning.submit_background(self.core.memory.maintain)
                        self.next_maintenance = time.monotonic() + 3600
            except Exception:
                # Provider exceptions can contain secrets or private prompt text.
                # Retain queued work for Core's bounded retry; never log payloads.
                continue

    def close(self):
        self.stop.set()
        with self.lock:
            self._save_role()
            self.core.learning.wait(raise_errors=False)
            self.core.close()


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, app, port=8765):
        self.app = app
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log chat, keys, imported data or URLs with query strings.

    def _allowed(self, api=False, write=False):
        origin = self.headers.get('Origin')
        if self.headers.get('Host') != self.server.origin.removeprefix('http://') or (
            origin is not None and origin != self.server.origin) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        if not api:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            return False
        session = cookie.get('openwoven_session')
        return bool(session and secrets.compare_digest(session.value, self.server.app.token) and
                    (not write or (origin == self.server.origin and
                     secrets.compare_digest(self.headers.get('X-OpenWoven', ''), self.server.app.token))))

    def _reply(self, status, value, mime='application/json; charset=utf-8', cookie=False):
        payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', 'openwoven_session=' + self.server.app.token + '; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path)
        if not self._allowed(api=path.path.startswith('/api/')):
            self._reply(403, {'error': 'Request denied'})
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path.path in files:
            name, mime = files[path.path]
            self._reply(200, (STATIC / name).read_bytes(), mime, cookie=path.path == '/')
            return
        try:
            with self.server.app.lock:
                if path.path == '/api/state':
                    self._reply(200, self.server.app.state())
                elif path.path == '/api/export':
                    self.server.app._save_role()
                    item = self.server.app.roles.read(parse_qs(path.query).get('id', [''])[0])
                    self._reply(200, export_package(item['role'], stored_role_facts(
                        self.server.app.roles, item['id'], self.server.app.root)), 'application/zip')
                elif path.path == '/api/memory':
                    self._reply(200, {'aul': self.server.app.core.aul(),
                                     'archives': self.server.app.core.memory.archives.list('weekly', 30)})
                else:
                    self._reply(404, {'error': 'Not found'})
        except Exception:
            self._reply(400, {'error': 'Request failed; check the local configuration'})

    def do_POST(self):
        if not self._allowed(api=True, write=True):
            self.close_connection = True
            self._reply(403, {'error': 'Request denied'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY or self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
                raise ValueError('Invalid request body')
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(length))
            action = urlsplit(self.path).path.removeprefix('/api/')
            if action == 'composer':
                if not isinstance(data, dict) or type(data.get('has_draft')) is not bool:
                    raise ValueError('Invalid composer state')
                composer_gate.note('default', data['has_draft'])  # Never wait behind a model call.
                self._reply(200, {'ok': True})
            else:
                with self.server.app.lock:
                    self._reply(200, self.server.app.command(action, data))
        except Exception:
            self.close_connection = True
            self._reply(400, {'error': 'Operation failed. Check format, file size or model settings.'})


def main():
    parser = argparse.ArgumentParser(description='OpenWoven local Web client (not an internet-facing server)')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data', default='.openwoven', help='private local data directory')
    args = parser.parse_args()
    app = WebApp(args.data)
    server = WebServer(app, args.port)
    worker = threading.Thread(target=app.tick, daemon=True)
    worker.start()
    print('OpenWoven: ' + server.origin + ' (Ctrl+C to stop; keep this process running for scheduled messages)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == '__main__':
    main()
