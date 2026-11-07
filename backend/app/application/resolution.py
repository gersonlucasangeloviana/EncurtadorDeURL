from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Protocol

from ..core import is_link_code
from ..domain import Link
from .errors import CacheUnavailable


class Outcome(Enum):
    REDIRECT = auto()
    NOT_FOUND = auto()
    GONE = auto()


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    destination: str | None = None
    found: bool = True


@dataclass(frozen=True)
class CachedLink:
    destination: str
    path: str | None
    expires_at: datetime | None


class ResolutionStore(Protocol):
    async def get(self, code: str) -> Link | None: ...
    def lock(self, code: str) -> AbstractAsyncContextManager[None]: ...


class ResolutionCache(Protocol):
    async def get(self, code: str) -> CachedLink | None: ...
    async def begin_fill(self, code: str) -> str: ...
    async def publish(self, link: Link, token: str) -> None: ...


def _resolve_target(destination, expected_path, expires_at, path, *, active=True, deleted=False):
    if expected_path != path:
        return Resolution(Outcome.NOT_FOUND)
    if deleted or (expires_at is not None and expires_at <= datetime.now(timezone.utc)):
        return Resolution(Outcome.GONE)
    if not active:
        return Resolution(Outcome.NOT_FOUND)
    return Resolution(Outcome.REDIRECT, destination)


def _from_link(link, path):
    if link is None:
        return Resolution(Outcome.NOT_FOUND, found=False)
    return _resolve_target(
        link.destination_url, link.public_path, link.expires_at, path,
        active=link.active, deleted=link.deleted,
    )


async def resolve(code: str, path: str | None, store: ResolutionStore, cache: ResolutionCache) -> Resolution:
    if not is_link_code(code):
        return Resolution(Outcome.NOT_FOUND, found=False)
    try:
        entry = await cache.get(code)
    except CacheUnavailable:
        return _from_link(await store.get(code), path)
    if entry is not None:
        return _resolve_target(entry.destination, entry.path, entry.expires_at, path)

    async with store.lock(code):
        try:
            # A concurrent request may have filled Redis while this request was waiting.
            entry = await cache.get(code)
            if entry is not None:
                return _resolve_target(entry.destination, entry.path, entry.expires_at, path)
            token = await cache.begin_fill(code)
        except CacheUnavailable:
            return _from_link(await store.get(code), path)

        link = await store.get(code)
        result = _from_link(link, path)
        if result.outcome is Outcome.REDIRECT:
            try:
                await cache.publish(link, token)
            except CacheUnavailable:
                pass
        return result
