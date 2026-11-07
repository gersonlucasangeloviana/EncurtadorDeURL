from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Protocol

from ..core import SEGMENT_MAX_LENGTH, generate_code, is_link_code, normalize_url, validate_name
from ..domain import Link
from .errors import CacheUnavailable, Conflict, InvalidInput, NotFound, StorageFailure, Unavailable

NAME_UNAVAILABLE = 'Não é possível cadastrar esse nome de encurtamento, escolha outro nome.'


class InsertConflict(Enum):
    CODE = auto()
    DESTINATION = auto()
    PROJECT = auto()
    PATH = auto()


class LinkStore(Protocol):
    async def next_sequence(self) -> int: ...
    async def insert(self, link: Link) -> InsertConflict | None: ...
    async def list(self) -> list[Link]: ...
    def lock(self, code: str) -> AbstractAsyncContextManager[None]: ...
    async def get(self, code: str) -> Link | None: ...
    async def mark_deleted(self, link: Link) -> None: ...


class Invalidation(Protocol):
    async def invalidate(self, code: str) -> None: ...


async def create_link(
    store: LinkStore, cfg, destination_url: str, short_code: str | None = None,
    project_name: str | None = None, public_path: str | None = None,
    expires_at: datetime | None = None,
) -> Link:
    try:
        destination = normalize_url(destination_url, cfg)
        if short_code is not None:
            validate_name(short_code, cfg)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc

    if expires_at is not None:
        if expires_at.utcoffset() is None:
            raise InvalidInput('Expiração deve estar no futuro e incluir fuso horário')
        try:
            expires_at = expires_at.astimezone(timezone.utc)
        except OverflowError as exc:
            raise InvalidInput('Expiração fora do intervalo de datas suportado') from exc
        if expires_at <= datetime.now(timezone.utc):
            raise InvalidInput('Expiração deve estar no futuro e incluir fuso horário')
    if project_name and (len(project_name) > SEGMENT_MAX_LENGTH or '\x00' in project_name):
        raise InvalidInput('Pasta inexistente')
    if public_path and not is_link_code(public_path):
        raise InvalidInput('Path inexistente')

    for _ in range(cfg.short_code_generation_max_attempts):
        sequence = await store.next_sequence()
        code = short_code if short_code is not None else generate_code(sequence, cfg)
        link = Link(code, sequence, destination, project_name or None, public_path or None, expires_at)
        match await store.insert(link):
            case None:
                return link
            case InsertConflict.CODE:
                if short_code is not None:
                    raise Conflict(NAME_UNAVAILABLE, 'short_name_unavailable')
            case InsertConflict.DESTINATION:
                raise Conflict('Esta URL não pode ser encurtada porque já existe.', 'destination_already_exists')
            case InsertConflict.PROJECT:
                raise InvalidInput('Pasta inexistente')
            case InsertConflict.PATH:
                raise InvalidInput('Path inexistente')
    raise Unavailable('Não foi possível gerar um código')


async def delete_link(store: LinkStore, cache: Invalidation, code: str) -> None:
    if not is_link_code(code):
        raise NotFound('Link inexistente')
    try:
        async with store.lock(code):
            link = await store.get(code)
            if link is None or link.deleted:
                raise NotFound('Link inexistente')
            await cache.invalidate(code)
            try:
                await store.mark_deleted(link)
            except StorageFailure:
                try:
                    await cache.invalidate(code)
                except CacheUnavailable:
                    pass
                raise
    except CacheUnavailable as exc:
        raise Unavailable('Cache indisponível. A exclusão não foi realizada.') from exc
    except StorageFailure as exc:
        raise Unavailable(
            'Não foi possível confirmar a exclusão. Atualize a página e confira o resultado antes de tentar novamente.'
        ) from exc
