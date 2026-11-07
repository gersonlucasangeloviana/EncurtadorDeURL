import unittest
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from app.application.events import AccessRecorder
from app.application.resolution import CachedLink
from app.config import Settings
from app.web import create_app


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def test_redaction_keeps_repeated_headers_and_cannot_be_disabled(self):
        save = AsyncMock()
        record = AccessRecorder(save, 'x-custom-id', r'(?i)^x-private-', '[hidden]')
        await record('abc', None, 'HEAD', 302, True, [
            (b'Authorization', b'secret'), (b'authorization', b'another'),
            (b'X-Admin-Password', b'admin'), (b'X-Custom-ID', b'id'),
            (b'X-Private-Header', b'private'), (b'user-agent', b'test-agent'),
        ])
        save.assert_awaited_once()
        event = save.await_args.args[0]
        self.assertEqual(event['headers'], [
            ['Authorization', '[hidden]'], ['authorization', '[hidden]'],
            ['X-Admin-Password', '[hidden]'], ['X-Custom-ID', '[hidden]'],
            ['X-Private-Header', '[hidden]'], ['user-agent', 'test-agent'],
        ])
        self.assertEqual((event['short_code'], event['method'], event['status']), ('abc', 'HEAD', 302))

    async def test_invalid_custom_pattern_fails_at_initialization(self):
        with self.assertRaisesRegex(ValueError, 'ANALYTICS_REDACTED_HEADER_PATTERN'):
            AccessRecorder(Mock(), '', '[', '[REDACTED]')

    async def test_failed_insert_does_not_change_public_response(self):
        save = AsyncMock(side_effect=RuntimeError('failed'))
        record = AccessRecorder(save, '', '', '[REDACTED]')
        cfg = Settings(_env_file=None, allowed_hosts='testserver')
        cache = Mock()
        cache.get = AsyncMock()
        cache.get.return_value = CachedLink('https://example.com', None, None)
        store = lambda: nullcontext(Mock())
        app = create_app(cfg, store, store, store, cache, record)

        with TestClient(app, follow_redirects=False) as client, self.assertLogs('shortener', 'WARNING') as logs:
            redirect = client.head('/abc', headers={'X-Admin-Password': 'sensitive'})
            missing = client.get('/other/abc')
        self.assertEqual(redirect.status_code, 302)
        self.assertEqual(redirect.headers['location'], 'https://example.com')
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.headers['cache-control'], 'no-store')
        self.assertEqual(save.await_count, 2)
        self.assertNotIn('sensitive', '\n'.join(logs.output))
