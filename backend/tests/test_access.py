import unittest
from contextlib import nullcontext

from fastapi.testclient import TestClient

from app.application.catalog import Removal
from app.config import Settings
from app.web import create_app

API_KEY = 'a' * 64
PASSWORD = 'test-administrator-password'


class EmptyStore:
    def lock(self, code):
        return nullcontext()

    def get(self, code):
        return None

    def remove(self, name):
        return Removal.MISSING


class AccessTests(unittest.TestCase):
    def setUp(self):
        cfg = Settings(_env_file=None, api_key=API_KEY, admin_password=PASSWORD, allowed_hosts='testserver')
        store = lambda: nullcontext(EmptyStore())
        self.client = TestClient(create_app(cfg, store, store, store, None, None))
        self.addCleanup(self.client.close)
        self.api = {'X-API-Key': API_KEY}

    def test_all_deletions_require_admin_password(self):
        for path in ('/api/links/code', '/api/projects/folder', '/api/projects?name=a%2Fb', '/api/paths/path'):
            with self.subTest(path=path):
                self.assertEqual(self.client.delete(path, headers=self.api).status_code, 403)
                self.assertEqual(self.client.delete(path, headers={**self.api, 'X-Admin-Password': 'wrong'}).status_code, 403)
                self.assertEqual(self.client.delete(path, headers={**self.api, 'X-Admin-Password': PASSWORD}).status_code, 404)
                self.assertEqual(self.client.delete(path, headers={'X-Admin-Password': PASSWORD}).status_code, 401)

    def test_edits_are_unavailable(self):
        response = self.client.patch('/api/links/code', headers=self.api, json={'active': False})
        self.assertEqual(response.status_code, 405)

    def test_malformed_host_cannot_bypass_api_or_admin_authentication(self):
        headers = {'Host': 'testserver:#'}
        self.assertEqual(self.client.delete('/api/links/code', headers=headers).status_code, 401)
        self.assertEqual(self.client.delete('/api/links/code', headers={**headers, **self.api}).status_code, 403)

    def test_expiration_must_be_representable_in_utc(self):
        response = self.client.post('/api/links', headers=self.api, json={
            'destination_url': 'https://example.com/',
            'expires_at': '9999-12-31T23:59:59-12:00',
        })
        self.assertEqual(response.status_code, 422)
