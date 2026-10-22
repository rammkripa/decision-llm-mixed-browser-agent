"""Loopback task console backed by one owned Browserbase session at a time."""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .browserbase import Browserbase
from .web_worker import redact, save

STATIC = Path(__file__).with_name('static')
ACTIVE = {'starting', 'planning', 'ready', 'running', 'awaiting_human', 'stopping', 'closing'}


def validate_task(body):
    goal, url = body.get('goal', ''), body.get('url', '') or 'https://www.google.com'
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 2000:
        raise ValueError('Enter a task of 1–2,000 characters.')
    if not isinstance(url, str) or len(url) > 2000:
        raise ValueError('Enter a valid starting URL.')
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Starting URL must be an HTTP or HTTPS address without credentials.')
    return {'goal': goal.strip(), 'url': url}


class Console:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.thread = None
        self.child = None
        self.folder = None
        self.client = None
        self.state = {'status': 'idle', 'session_status': 'none', 'history': [], 'events': []}

    def update(self, **values):
        with self.lock:
            self.state.update(redact(values))

    def snapshot(self):
        with self.lock:
            state = json.loads(json.dumps(self.state))
        state['configured'] = {key: bool(os.environ.get(key)) for key in
                               ('BROWSERBASE_API_KEY', 'BROWSERBASE_PROJECT_ID',
                                'TYPESAFE_API_KEY', 'TEXT_MODEL_API_KEY')}
        return state

    def start(self, body):
        task = validate_task(body)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('A task is already running.')
            if self.state.get('session_status') == 'release_failed':
                raise ValueError('Close the previous cloud session before starting another task.')
            self.client = Browserbase()
            if not os.environ.get('TYPESAFE_API_KEY') or not os.environ.get('TEXT_MODEL_API_KEY'):
                raise ValueError('Set TYPESAFE_API_KEY and TEXT_MODEL_API_KEY in .env, then restart the UI.')
            run_id = uuid.uuid4().hex
            self.folder = self.root / run_id
            self.folder.mkdir(parents=True)
            save(self.folder / 'task.json', task)
            self.state = {**task, 'run_id': run_id, 'status': 'starting', 'session_status': 'creating',
                          'history': [], 'events': [], 'tasks': [], 'evidence_count': 0, 'model_calls': {},
                          'result': None, 'live_url': None, 'started_at': time.time()}
            self.thread = threading.Thread(target=self.run, args=(task, run_id), daemon=True)
            self.thread.start()
        return self.snapshot()

    def release(self):
        session_id = self.state.get('session_id')
        if not session_id or self.state.get('session_status') == 'released':
            return
        try:
            self.client.release(session_id)
            self.update(session_status='released', live_url=None, cleanup_error=None)
        except Exception as exc:
            self.update(session_status='release_failed', cleanup_error=str(exc))

    def run(self, task, run_id):
        try:
            session = self.client.create()
            session_id = session['id']
            self.update(session_id=session_id, session_status='active', status='planning',
                        session_url=f'https://www.browserbase.com/sessions/{session_id}')
            connect = session.get('connectUrl', '')
            if not connect.startswith('wss://'):
                raise RuntimeError('Browserbase returned no secure browser connection.')
            try:
                self.update(live_url=self.client.live_url(session_id))
            except RuntimeError as exc:
                self.update(live_warning=str(exc))
            if (self.folder / 'cancel').exists():
                self.update(status='cancelled')
                return
            env = dict(os.environ)
            for name in ('BU_CDP_URL', 'BU_BROWSER_ID'):
                env.pop(name, None)
            env.update(BU_CDP_WS=connect, BU_NAME='jev-web-' + run_id[:12])
            target = None
            started = time.monotonic()
            with (self.folder / 'worker.log').open('w') as log:
                self.child = subprocess.Popen([sys.executable, '-u', '-m', 'jev_ultrafast.web_worker',
                                               '--folder', str(self.folder)], env=env,
                                              stdout=log, stderr=subprocess.STDOUT)
                while self.child.poll() is None:
                    self.read_progress()
                    current_target = self.state.get('target_id')
                    if current_target and target != current_target:
                        target = current_target
                        try:
                            self.update(live_url=self.client.live_url(session_id, target), live_warning=None)
                        except RuntimeError as exc:
                            self.update(live_warning=str(exc))
                    if time.monotonic() - started > 840:
                        (self.folder / 'cancel').touch()
                        self.update(status='stopping', blocked_reason='Reached the 14-minute web task limit.')
                        self.child.terminate()
                    if (self.folder / 'cancel').exists() and time.time() - (self.folder / 'cancel').stat().st_mtime > 5:
                        self.child.terminate()
                    time.sleep(.3)
                self.read_progress()
                if self.child.returncode and self.state.get('status') in ACTIVE:
                    self.update(status='error', blocked_reason='Agent worker stopped unexpectedly; inspect worker.log.')
        except Exception as exc:
            self.update(status='error', blocked_reason=str(exc))
        finally:
            final_status = self.state.get('status', 'error')
            if (self.folder / 'cancel').exists():
                final_status = 'cancelled'
            self.update(status='closing')
            self.release()
            if self.child:
                from browser_harness.admin import restart_daemon

                try:
                    restart_daemon('jev-web-' + run_id[:12])
                except Exception:
                    pass
            if final_status in ACTIVE:
                final_status = 'cancelled' if (self.folder / 'cancel').exists() else 'error'
            self.update(status=final_status, finished_at=time.time())
            if not (self.folder / 'trace.json').exists():
                save(self.folder / 'trace.json', {**task, 'status': final_status,
                                                 'blocked_reason': self.state.get('blocked_reason')})
            save(self.folder / 'console.json', self.snapshot())

    def read_progress(self):
        try:
            data = json.loads((self.folder / 'progress.json').read_text())
            if isinstance(data, dict):
                self.update(**data)
        except (OSError, ValueError):
            pass

    def control(self, action):
        if action == 'release':
            if self.thread and self.thread.is_alive():
                raise ValueError('Stop the task before retrying session cleanup.')
            self.release()
        else:
            if not self.folder or not self.thread or not self.thread.is_alive():
                raise ValueError('No active task.')
            if action not in {'cancel', 'pause', 'resume'}:
                raise ValueError('Unknown control.')
            (self.folder / action).touch()
        return self.snapshot()

    def close(self):
        if self.thread and self.thread.is_alive():
            (self.folder / 'cancel').touch()
            self.thread.join(timeout=40)
            if self.thread.is_alive() and self.child and self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                self.thread.join(timeout=3)
        self.release()


class Runs:
    """Each console owns its own worker, browser, controls, and audit folder."""

    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.consoles = {}

    @staticmethod
    def valid_id(run_id):
        return isinstance(run_id, str) and re.fullmatch(r'minotaur-[a-f0-9]{32}', run_id) is not None

    def start(self, body):
        console = Console(self.root)
        state = console.start(body)
        run_id = 'minotaur-' + state['run_id']
        with self.lock:
            self.consoles[run_id] = console
        return self.snapshot(run_id)

    def get(self, run_id):
        if not self.valid_id(run_id):
            return None
        with self.lock:
            if run_id not in self.consoles:
                folder = self.root / run_id.removeprefix('minotaur-')
                try:
                    state = json.loads((folder / 'console.json').read_text())
                except (OSError, ValueError):
                    return None
                console = Console(self.root)
                console.folder, console.state = folder, state
                self.consoles[run_id] = console
            return self.consoles[run_id]

    def snapshot(self, run_id=None):
        if run_id is None:
            return Console(self.root).snapshot()
        console = self.get(run_id)
        if console is None:
            return None
        return {**console.snapshot(), 'run_id': run_id, 'console_url': '/runs/' + run_id}

    def control(self, run_id, action):
        console = self.get(run_id)
        if console is None:
            raise ValueError('Run not found.')
        if action == 'release' and console.client is None:
            console.client = Browserbase()
        console.control(action)
        return self.snapshot(run_id)

    def close(self):
        for console in list(self.consoles.values()):
            console.close()


def run_request(value):
    parsed = urlparse(value)
    route = re.fullmatch(r'/api/runs/(minotaur-[a-f0-9]{32})/(state|control|trace)', parsed.path)
    if route:
        return '/api/' + route[2], route[1]
    return parsed.path, parse_qs(parsed.query).get('run_id', [None])[0]


class Handler(BaseHTTPRequestHandler):
    def send(self, status, value, mime='application/json'):
        data = value if isinstance(value, bytes) else value.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(data)

    def allowed(self, api=False):
        host = self.headers.get('Host')
        port = self.server.server_address[1]
        return host in {f'127.0.0.1:{port}', f'localhost:{port}'} and (not api or (
            self.headers.get('X-Console-Token') == self.server.token and
            self.headers.get('Origin') in (None, f'http://{host}')))

    def do_GET(self):
        path, run_id = run_request(self.path)
        if not self.allowed(path.startswith('/api/')):
            return self.send(403, 'Forbidden', 'text/plain')
        if path == '/api/state':
            state = self.server.runs.snapshot(run_id)
            return self.send(200 if state is not None else 404, json.dumps(
                state if state is not None else {'error': 'Run not found.'}))
        if path == '/api/trace':
            console = self.server.runs.get(run_id)
            folder = console.folder if console else None
            if not folder or not (folder / 'trace.json').exists():
                return self.send(404, json.dumps({'error': 'Trace will be available after the run ends.'}))
            return self.send(200, (folder / 'trace.json').read_bytes())
        files = {'/': ('landing.html', 'text/html'), '/console.js': ('console.js', 'text/javascript'),
                 '/landing.js': ('landing.js', 'text/javascript'),
                 '/task-examples.js': ('task-examples.js', 'text/javascript'),
                 '/console.css': ('console.css', 'text/css'),
                 '/minotaur.png': ('minotaur.png', 'image/png'),
                 '/minotaur-maze.png': ('minotaur-maze.png', 'image/png')}
        if path.startswith('/runs/') and Runs.valid_id(path.removeprefix('/runs/')):
            files[path] = ('console.html', 'text/html')
        if path not in files:
            return self.send(404, 'Not found', 'text/plain')
        filename, mime = files[path]
        if mime == 'image/png':
            return self.send(200, (STATIC / filename).read_bytes(), mime)
        content = (STATIC / filename).read_text().replace('__CONSOLE_TOKEN__', self.server.token)
        self.send(200, content, mime + '; charset=utf-8')

    def do_POST(self):
        if not self.allowed(True):
            return self.send(403, 'Forbidden', 'text/plain')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 12000:
                raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Invalid request.')
            path, run_id = run_request(self.path)
            if path == '/api/start':
                state = self.server.runs.start(body)
            elif path == '/api/control':
                state = self.server.runs.control(run_id, body.get('action'))
            else:
                return self.send(404, json.dumps({'error': 'Not found'}))
            self.send(200, json.dumps(state))
        except (ValueError, RuntimeError) as exc:
            self.send(400, json.dumps({'error': redact(str(exc))}))

    def log_message(self, *_args):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local task console with Browserbase cloud execution.')
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args(argv)
    runs = Runs(Path.cwd() / 'artifacts' / 'web')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.runs, server.token = runs, secrets.token_urlsafe(32)
    print(f'Minotaur task console: http://127.0.0.1:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runs.close()
        server.server_close()


if __name__ == '__main__':
    main()
