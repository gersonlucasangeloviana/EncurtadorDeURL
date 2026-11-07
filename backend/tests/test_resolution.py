import json
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

from redis.exceptions import ConnectionError

from app.application.resolution import Outcome, resolve
from app.domain import Link
from app.infrastructure.redis_cache import RedisLinkCache

DESTINATION = 'https://example.com/'


class RedisClient:
    def __init__(self, entry=None, fail=False):
        self.entry = entry
        self.fail = fail
        self.token = None
        self.fill_ttl = None
        self.writes = []

    async def get(self, key):
        if self.fail:
            raise ConnectionError()
        return json.dumps(self.entry) if self.entry else None

    async def set(self, key, token, ex):
        self.token = token
        self.fill_ttl = ex

    async def eval(self, script, count, token_key, key, token, value, deadline):
        if self.token == token:
            self.writes.append((key, deadline, json.loads(value)))
            self.token = None


class ResolutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Mock()
        self.store.lock.return_value = nullcontext()
        self.store.get = AsyncMock(return_value=Link('abc', 1, DESTINATION))

    async def test_cache_hit_does_not_query_or_lock_database(self):
        client = RedisClient({'destination': DESTINATION, 'path': None, 'version': 1, 'expires_at': None})
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual((result.outcome, result.destination), (Outcome.REDIRECT, DESTINATION))
        self.store.get.assert_not_called()
        self.store.lock.assert_not_called()

    async def test_cache_hit_checks_path(self):
        client = RedisClient({'destination': DESTINATION, 'path': 'empresa', 'expires_at': None})
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual(result.outcome, Outcome.NOT_FOUND)
        self.store.get.assert_not_called()

    async def test_cache_miss_fills_with_absolute_deadline_bounded_by_expiry(self):
        expiry = datetime.now(timezone.utc) + timedelta(milliseconds=800)
        self.store.get.return_value = Link('abc', 1, DESTINATION, expires_at=expiry)
        client = RedisClient()
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual(result.outcome, Outcome.REDIRECT)
        self.store.get.assert_awaited_once_with('abc')
        key, deadline, entry = client.writes[0]
        self.assertEqual((key, deadline, entry['destination']), (
            'test:link:abc', int(expiry.timestamp() * 1000), DESTINATION,
        ))

    async def test_invalidated_fill_token_cannot_publish_stale_value(self):
        client = RedisClient()

        def load(code):
            client.token = None
            return Link(code, 1, DESTINATION)

        self.store.get.side_effect = load
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual(result.outcome, Outcome.REDIRECT)
        self.assertEqual(client.writes, [])

    async def test_miss_for_unknown_code_uses_short_fill_ttl(self):
        client = RedisClient()
        self.store.get.return_value = None
        cache = RedisLinkCache(client, 'test', 1800, fill_ttl_seconds=4)
        self.assertEqual((await resolve('abc', None, self.store, cache)).outcome, Outcome.NOT_FOUND)
        self.assertEqual(client.fill_ttl, 4)
        self.assertEqual(client.writes, [])

    async def test_redis_failure_uses_database_without_lock(self):
        client = RedisClient(fail=True)
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual(result.outcome, Outcome.REDIRECT)
        self.store.get.assert_awaited_once_with('abc')
        self.store.lock.assert_not_called()

    async def test_expired_cache_does_not_redirect(self):
        expiry = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        client = RedisClient({'destination': DESTINATION, 'path': None, 'expires_at': expiry})
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual(result.outcome, Outcome.GONE)
        self.store.get.assert_not_called()

    async def test_invalid_cache_entry_is_treated_as_a_miss(self):
        client = RedisClient({'destination': None, 'path': None, 'expires_at': None})
        result = await resolve('abc', None, self.store, RedisLinkCache(client, 'test', 1800))
        self.assertEqual(result.outcome, Outcome.REDIRECT)
        self.store.get.assert_awaited_once_with('abc')
