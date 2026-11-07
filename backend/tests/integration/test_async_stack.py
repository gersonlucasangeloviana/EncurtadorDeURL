"""Run with backend/tests/compose.yml; never against a shared database."""
import asyncio
import os
import unittest
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.resolution import Outcome, resolve
from app.config import Settings
from app.infrastructure import models
from app.infrastructure.postgres import (
    PostgresLinks, advisory_key, initialize_schema, prune_access_events, save_event,
)
from app.infrastructure.redis_cache import RedisLinkCache


@unittest.skipUnless(os.environ.get('SHORTENER_INTEGRATION') == '1', 'requires isolated test services')
class AsyncStackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = Settings(_env_file=None).check()
        url = make_url(self.cfg.database_url)
        # These tests reset tables. Only the dedicated Compose service is accepted.
        if url.host != 'postgres-test' or url.database != 'shortener_async_test':
            raise RuntimeError('Use only the isolated backend/tests/compose.yml database')
        if make_url(self.cfg.redis_url).host != 'redis-test':
            raise RuntimeError('Use only the isolated backend/tests/compose.yml Redis')
        self.resources = AsyncExitStack()
        self.addAsyncCleanup(self.resources.aclose)
        self.engine = create_async_engine(self.cfg.database_url)
        self.resources.push_async_callback(self.engine.dispose)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.redis = Redis.from_url(self.cfg.redis_url, decode_responses=True)
        self.resources.push_async_callback(self.redis.aclose)
        async with self.engine.begin() as connection:
            # Also remove the legacy table used by the startup rejection test.
            await connection.execute(text('DROP TABLE IF EXISTS links CASCADE'))
            await connection.run_sync(models.Base.metadata.drop_all)
        await self.redis.flushdb()
        from app.main import build_app
        self.app = build_app(self.cfg)
        await self.resources.enter_async_context(self.app.router.lifespan_context(self.app))
        self.client = await self.resources.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url='http://testserver',
            headers={'X-API-Key': self.cfg.api_key}, follow_redirects=False,
        ))
        self.admin = {'X-Admin-Password': self.cfg.admin_password}

    async def create(self, code='AsyncLink', **data):
        response = await self.client.post('/api/links', json={
            'destination_url': f'https://example.com/{code}', 'short_code': code, **data,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def test_crud_cache_events_and_expiration(self):
        for collection, name in [('projects', 'Pasta / ç'), ('paths', 'Empresa')]:
            self.assertEqual((await self.client.post('/api/' + collection, json={'name': name})).status_code, 201)
            self.assertIn(name, (await self.client.get('/api/' + collection)).json())
        await self.create(project_name='Pasta / ç', public_path='Empresa')
        self.assertEqual(len((await self.client.get('/api/links')).json()), 1)
        key = self.cfg.cache_key_prefix + ':link:AsyncLink'
        self.assertIsNone(await self.redis.get(key))
        for method in ('GET', 'HEAD'):
            response = await self.client.request(method, '/Empresa/AsyncLink', headers={'X-Auth-Token': 'private'})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['location'], 'https://example.com/AsyncLink')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            if method == 'HEAD':
                self.assertEqual(response.content, b'')
        self.assertIsNotNone(await self.redis.get(key))
        self.assertEqual((await self.client.get('/Wrong/AsyncLink')).status_code, 404)
        async with self.sessions() as db:
            payloads = list(await db.scalars(select(models.AccessEvent.payload)))
        self.assertEqual([p['status'] for p in payloads], [302, 302, 404])
        for payload in payloads:
            for name, value in payload['headers']:
                if name.lower() in ('x-api-key', 'x-auth-token'):
                    self.assertEqual(value, '[REDACTED]')
        response = await self.client.delete('/api/projects', params={'name': 'Pasta / ç'}, headers=self.admin)
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.client.delete('/api/links/AsyncLink', headers=self.admin)).status_code, 200)
        self.assertIsNone(await self.redis.get(key))
        self.assertEqual((await self.client.get('/Empresa/AsyncLink')).status_code, 410)
        self.assertEqual((await self.client.get('/api/links')).json(), [])
        for collection, name in [('projects', 'Livre / ç'), ('paths', 'Livre')]:
            await self.client.post('/api/' + collection, json={'name': name})
            response = await self.client.delete(
                '/api/projects' if collection == 'projects' else '/api/paths/' + name,
                params={'name': name} if collection == 'projects' else None, headers=self.admin,
            )
            self.assertEqual(response.status_code, 200)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=1)
        await self.create('Expiring', expires_at=expiry.isoformat())
        self.assertEqual((await self.client.get('/Expiring')).status_code, 302)
        await asyncio.sleep(max(0, (expiry - datetime.now(timezone.utc)).total_seconds()) + .05)
        self.assertEqual((await self.client.get('/Expiring')).status_code, 410)

    async def test_concurrent_insert_conflicts_and_foreign_keys(self):
        responses = await asyncio.gather(*[
            self.client.post('/api/links', json={
                'short_code': 'Concurrent', 'destination_url': 'https://example.com/concurrent',
            }) for _ in range(8)
        ])
        self.assertEqual(sorted(r.status_code for r in responses), [201] + [409] * 7)
        for field in ('project_name', 'public_path'):
            response = await self.client.post('/api/links', json={
                'destination_url': 'https://example.com/missing', field: 'Missing',
            })
            self.assertEqual(response.status_code, 422)
        response = await self.client.post('/api/links', json={'destination_url': 'https://example.com/concurrent'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'destination_already_exists')
        automatic = await self.client.post('/api/links', json={'destination_url': 'https://example.com/automatic'})
        self.assertEqual(automatic.status_code, 201)
        self.assertEqual((await self.client.get('/' + automatic.json()['short_code'])).status_code, 302)

    async def test_redis_failure_falls_back_and_prevents_deletion(self):
        await self.create()
        from app.main import build_app
        cfg = self.cfg.model_copy(update={'redis_url': 'redis://127.0.0.1:1/0'})
        app = build_app(cfg)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver',
                                         headers={'X-API-Key': cfg.api_key}) as client:
                self.assertEqual((await client.get('/AsyncLink')).status_code, 302)
                response = await client.delete('/api/links/AsyncLink', headers=self.admin)
                self.assertEqual(response.status_code, 503)
        self.assertEqual((await self.client.get('/AsyncLink')).status_code, 302)

    async def test_cancelled_lock_is_released_and_pool_remains_usable(self):
        entered = asyncio.Event()

        async def hold():
            async with self.sessions() as db:
                async with PostgresLinks(db).lock('Cancelled'):
                    entered.set()
                    await asyncio.Event().wait()

        task = asyncio.create_task(hold())
        try:
            await asyncio.wait_for(entered.wait(), 3)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        async with self.engine.begin() as connection:
            self.assertTrue(await connection.scalar(
                text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': advisory_key('Cancelled')},
            ))
        await self.create()

    async def test_fill_and_delete_race_does_not_restore_stale_cache(self):
        await self.create()
        cache = RedisLinkCache(self.redis, self.cfg.cache_key_prefix, 1800)
        filling = asyncio.Event()
        release = asyncio.Event()
        deleting = asyncio.Event()
        original_lock = PostgresLinks.lock

        @asynccontextmanager
        async def track_lock(store, code):
            if filling.is_set() and not release.is_set():
                deleting.set()
            async with original_lock(store, code):
                yield

        class PausedCache:
            get = cache.get
            begin_fill = cache.begin_fill

            async def publish(self, link, token):
                filling.set()
                await release.wait()
                await cache.publish(link, token)

        async def fill():
            async with self.sessions() as db:
                return await resolve('AsyncLink', None, PostgresLinks(db), PausedCache())

        with patch.object(PostgresLinks, 'lock', track_lock):
            reader = asyncio.create_task(fill())
            deletion = None
            try:
                await asyncio.wait_for(filling.wait(), 3)
                deletion = asyncio.create_task(self.client.delete('/api/links/AsyncLink', headers=self.admin))
                await asyncio.wait_for(deleting.wait(), 3)
                self.assertFalse(deletion.done())
                release.set()
                result, response = await asyncio.wait_for(asyncio.gather(reader, deletion), 5)
                self.assertEqual(result.outcome, Outcome.REDIRECT)
                self.assertEqual(response.status_code, 200)
            finally:
                release.set()
                await asyncio.gather(*[task for task in (reader, deletion) if task is not None], return_exceptions=True)
        self.assertIsNone(await self.redis.get(self.cfg.cache_key_prefix + ':link:AsyncLink'))
        self.assertEqual((await self.client.get('/AsyncLink')).status_code, 410)

    async def test_event_retention_and_schema_guard(self):
        # Stop the app's retention task before testing the retention boundary.
        await self.resources.aclose()
        self.engine = create_async_engine(self.cfg.database_url)
        self.resources.push_async_callback(self.engine.dispose)
        sessions = async_sessionmaker(self.engine)
        for i in range(6):
            await save_event(sessions, {'event_id': str(i)})
        await prune_access_events(self.engine, 2)
        async with self.engine.connect() as connection:
            self.assertEqual(await connection.scalar(select(func.count()).select_from(models.AccessEvent)), 2)
        with self.assertRaisesRegex(RuntimeError, 'incompatível'):
            await initialize_schema(self.engine, 'different-fingerprint')
        async with self.engine.begin() as connection:
            await connection.run_sync(models.Base.metadata.drop_all)
            await connection.execute(text('CREATE TABLE links (owner_id integer)'))
        with self.assertRaisesRegex(RuntimeError, 'Esquema anterior'):
            await initialize_schema(self.engine, self.cfg.fingerprint())

    async def test_failed_startup_closes_all_async_resources(self):
        from app.main import build_app
        engines = [AsyncMock(), AsyncMock()]
        redis = AsyncMock()
        with patch('app.main.create_async_engine', side_effect=engines), \
                patch('app.main.Redis.from_url', return_value=redis), \
                patch('app.main.initialize_schema', side_effect=RuntimeError('startup failed')):
            app = build_app(self.cfg)
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                async with app.router.lifespan_context(app):
                    self.fail('startup should fail')
        for engine in engines:
            engine.dispose.assert_awaited_once()
        redis.aclose.assert_awaited_once()
