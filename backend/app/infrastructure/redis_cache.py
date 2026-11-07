import json
import uuid
from datetime import datetime, timedelta, timezone

from redis.exceptions import RedisError

from ..application.errors import CacheUnavailable
from ..application.resolution import CachedLink
from ..domain import Link

_PUBLISH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[2], ARGV[2], 'PXAT', ARGV[3])
    redis.call('DEL', KEYS[1])
end
"""


class RedisLinkCache:
    def __init__(self, client, prefix: str, ttl_seconds: int, *, fill_ttl_seconds: int = 5):
        self.client = client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds
        self.fill_ttl_seconds = fill_ttl_seconds

    def _entry_key(self, code):
        return f'{self.prefix}:link:{code}'

    def _fill_key(self, code):
        return f'{self.prefix}:fill:{code}'

    def get(self, code: str) -> CachedLink | None:
        try:
            raw = self.client.get(self._entry_key(code))
        except RedisError as exc:
            raise CacheUnavailable() from exc
        if not raw:
            return None
        try:
            entry = json.loads(raw)
            destination, path, expires = entry['destination'], entry['path'], entry['expires_at']
            expires_at = datetime.fromisoformat(expires) if expires is not None else None
            if (not isinstance(destination, str) or not destination or
                    (path is not None and not isinstance(path, str)) or
                    (expires_at is not None and expires_at.utcoffset() is None)):
                return None
        except (ValueError, KeyError, TypeError):
            return None
        return CachedLink(destination, path, expires_at)

    def begin_fill(self, code: str) -> str:
        token = uuid.uuid4().hex
        try:
            self.client.set(self._fill_key(code), token, ex=self.fill_ttl_seconds)
        except RedisError as exc:
            raise CacheUnavailable() from exc
        return token

    def publish(self, link: Link, token: str) -> None:
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(seconds=self.ttl_seconds)
        if link.expires_at is not None:
            deadline = min(deadline, link.expires_at)
        if deadline <= now:
            return
        entry = {
            'destination': link.destination_url,
            'path': link.public_path,
            'version': link.version,
            'expires_at': link.expires_at.isoformat() if link.expires_at is not None else None,
        }
        try:
            self.client.eval(
                _PUBLISH, 2, self._fill_key(link.short_code), self._entry_key(link.short_code),
                token, json.dumps(entry), int(deadline.timestamp() * 1000),
            )
        except RedisError as exc:
            raise CacheUnavailable() from exc

    def invalidate(self, code: str) -> None:
        try:
            self.client.delete(self._entry_key(code), self._fill_key(code))
        except RedisError as exc:
            raise CacheUnavailable() from exc
