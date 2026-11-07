import asyncio
import unittest
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock

import httpx

from app.application.events import AccessRecorder
from app.application.resolution import CachedLink
from app.config import Settings
from app.web import create_app


class AsyncConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifty_pending_cache_reads_do_not_block_health(self):
        entered = 0
        all_entered = asyncio.Event()
        release = asyncio.Event()

        async def read(code):
            nonlocal entered
            entered += 1
            if entered == 50:
                all_entered.set()
            await release.wait()
            return CachedLink('https://example.com/', None, None)

        cache = Mock(get=AsyncMock(side_effect=read))
        save = AsyncMock()
        record = AccessRecorder(save, '', '', '[REDACTED]')
        store = lambda: nullcontext(Mock())
        app = create_app(Settings(_env_file=None, allowed_hosts='testserver'),
                         store, store, store, cache, record)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            requests = [asyncio.create_task(client.get('/abc')) for _ in range(50)]
            try:
                await asyncio.wait_for(all_entered.wait(), timeout=5)
                response = await asyncio.wait_for(client.get('/health'), timeout=2)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(any(request.done() for request in requests))
            finally:
                release.set()
                responses = await asyncio.gather(*requests)
            self.assertTrue(all(response.status_code == 302 for response in responses))
            self.assertEqual(save.await_count, 50)

    async def test_pending_event_write_does_not_block_other_requests(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def save(payload):
            entered.set()
            await release.wait()

        record = AccessRecorder(save, '', '', '[REDACTED]')
        cache = Mock(get=AsyncMock(return_value=CachedLink('https://example.com/', None, None)))
        store = lambda: nullcontext(Mock())
        app = create_app(Settings(_env_file=None, allowed_hosts='testserver'),
                         store, store, store, cache, record)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            redirect = asyncio.create_task(client.get('/abc'))
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                health = await asyncio.wait_for(client.get('/health'), timeout=2)
                self.assertEqual(health.status_code, 200)
                # Async I/O still awaits persistence; this migration adds no queue.
                self.assertFalse(redirect.done())
            finally:
                release.set()
                response = await redirect
            self.assertEqual(response.status_code, 302)

    async def test_cancellation_is_not_swallowed_by_event_recorder(self):
        record = AccessRecorder(AsyncMock(side_effect=asyncio.CancelledError()), '', '', '[REDACTED]')
        with self.assertRaises(asyncio.CancelledError):
            await record('abc', None, 'GET', 302, True, [])
