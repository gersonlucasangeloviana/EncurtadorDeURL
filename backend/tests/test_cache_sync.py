import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

from app.application.errors import CacheUnavailable, StorageFailure, Unavailable
from app.application.links import delete_link
from app.domain import Link
from app.infrastructure.postgres import advisory_key


class MutationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.link = Link('abc', 1, 'https://example.com')
        self.store = Mock()
        self.store.lock.side_effect = self.lock
        self.store.get = AsyncMock(return_value=self.link)
        self.store.mark_deleted = AsyncMock(side_effect=lambda link: self.events.append('commit'))
        self.cache = Mock()
        self.cache.invalidate = AsyncMock(side_effect=lambda code: self.events.append('invalidate'))

    @asynccontextmanager
    async def lock(self, code):
        self.events.append('lock')
        yield

    async def test_lock_keys_stable_and_specific(self):
        self.assertEqual(advisory_key('abc'), advisory_key('abc'))
        self.assertNotEqual(advisory_key('abc'), advisory_key('xyz'))

    async def test_invalidation_precedes_write(self):
        await delete_link(self.store, self.cache, 'abc')
        self.assertEqual(self.events, ['lock', 'invalidate', 'commit'])

    async def test_database_error_retries_invalidation_and_reports_uncertain_commit(self):
        def fail(link):
            self.events.append('commit failure')
            raise StorageFailure()

        self.store.mark_deleted.side_effect = fail
        with self.assertRaisesRegex(Unavailable, 'confirme|confira'):
            await delete_link(self.store, self.cache, 'abc')
        self.assertEqual(self.events, ['lock', 'invalidate', 'commit failure', 'invalidate'])

    async def test_invalidation_failure_prevents_database_write(self):
        self.cache.invalidate.side_effect = CacheUnavailable()
        with self.assertRaisesRegex(Unavailable, 'Cache indisponível'):
            await delete_link(self.store, self.cache, 'abc')
        self.store.mark_deleted.assert_not_awaited()
