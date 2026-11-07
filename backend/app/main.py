import asyncio
import logging
from contextlib import asynccontextmanager, contextmanager, suppress
from functools import partial

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .application.events import AccessRecorder
from .config import settings
from .infrastructure.postgres import (
    PostgresLinks, initialize_schema, postgres_paths, postgres_projects,
    prune_access_events, save_event,
)
from .infrastructure.redis_cache import RedisLinkCache
from .web import create_app

_LOG = logging.getLogger('shortener')


async def maintain_event_retention(engine, max_events):
    while True:
        try:
            await asyncio.to_thread(prune_access_events, engine, max_events)
        except SQLAlchemyError:
            _LOG.warning('Não foi possível aplicar a retenção de eventos de acesso')
        await asyncio.sleep(30)


def build_app(cfg):
    engine = create_engine(
        cfg.database_url, pool_pre_ping=True, hide_parameters=True,
        connect_args={'connect_timeout': 2},
    )
    sessions = sessionmaker(engine)
    event_engine = create_engine(
        cfg.database_url, pool_pre_ping=True, hide_parameters=True,
        pool_size=4, max_overflow=0, pool_timeout=0.02,
        connect_args={'connect_timeout': 2, 'options': '-c statement_timeout=100ms'},
    )
    event_sessions = sessionmaker(event_engine)
    redis = Redis.from_url(
        cfg.redis_url, decode_responses=True,
        socket_connect_timeout=cfg.redis_socket_timeout_seconds,
        socket_timeout=cfg.redis_socket_timeout_seconds,
    )
    cache = RedisLinkCache(
        redis, cfg.cache_key_prefix, cfg.redis_cache_ttl_seconds,
        fill_ttl_seconds=cfg.redis_fill_ttl_seconds,
    )
    record_event = AccessRecorder(
        partial(save_event, event_sessions), cfg.analytics_redacted_headers,
        cfg.analytics_redacted_header_pattern, cfg.analytics_redaction_marker,
    )

    @contextmanager
    def store(repository):
        with sessions() as db:
            yield repository(db)

    @asynccontextmanager
    async def lifespan(app):
        try:
            initialize_schema(engine, cfg.fingerprint())
            retention = asyncio.create_task(maintain_event_retention(engine, cfg.analytics_max_events))
            try:
                yield
            finally:
                retention.cancel()
                with suppress(asyncio.CancelledError):
                    await retention
        finally:
            redis.close()
            event_engine.dispose()
            engine.dispose()

    return create_app(
        cfg, partial(store, PostgresLinks), partial(store, postgres_projects),
        partial(store, postgres_paths), cache, record_event, lifespan=lifespan,
    )


app = build_app(settings())
