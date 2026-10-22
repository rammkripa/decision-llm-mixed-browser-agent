"""Browserbase session lifecycle. API keys and CDP URLs never reach the UI."""

import os
from urllib.parse import urlparse

import httpx


class Browserbase:
    def __init__(self):
        self.key = os.environ.get('BROWSERBASE_API_KEY', '')
        self.project = os.environ.get('BROWSERBASE_PROJECT_ID', '')
        if not self.key or not self.project:
            raise ValueError('Set BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID in .env, then restart the UI.')

    def request(self, method, path, **kwargs):
        try:
            with httpx.Client(timeout=35) as client:
                response = client.request(method, 'https://api.browserbase.com/v1/sessions' + path,
                                          headers={'X-BB-API-Key': self.key}, **kwargs)
                if response.is_error:
                    raise RuntimeError(f'Browserbase returned HTTP {response.status_code}.')
                return response.json()
        except httpx.HTTPError:
            raise RuntimeError('Could not connect to Browserbase.') from None

    def create(self):
        return self.request('POST', '', json={'projectId': self.project, 'keepAlive': False,
                            'timeout': 900, 'browserSettings': {'viewport': {'width': 1120, 'height': 780}}})

    def live_url(self, session_id, target=None):
        links = self.request('GET', f'/{session_id}/debug')
        pages = links.get('pages', [])
        page = next((p for p in pages if p.get('id') == target), {}) if target else {}
        value = page.get('debuggerFullscreenUrl') or links.get('debuggerFullscreenUrl')
        parsed = urlparse(value or '')
        if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.browserbase.com'):
            raise RuntimeError('Browserbase did not return a valid live view URL.')
        return value

    def release(self, session_id):
        self.request('POST', f'/{session_id}', json={'projectId': self.project, 'status': 'REQUEST_RELEASE'})
