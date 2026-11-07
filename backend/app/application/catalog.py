from enum import Enum, auto
from typing import Protocol

from ..core import SEGMENT_MAX_LENGTH, validate_name, validate_project_name
from .errors import Conflict, InvalidInput, NotFound
from .links import NAME_UNAVAILABLE


class Removal(Enum):
    REMOVED = auto()
    MISSING = auto()
    IN_USE = auto()


class CatalogStore(Protocol):
    async def list(self) -> list[str]: ...
    async def insert(self, name: str) -> bool: ...
    async def remove(self, name: str) -> Removal: ...


async def create_project(store: CatalogStore, name: str) -> str:
    try:
        name = validate_project_name(name)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    if not await store.insert(name):
        raise Conflict('Pasta já existe')
    return name


async def create_path(store: CatalogStore, name: str, cfg) -> str:
    try:
        name = validate_name(name, cfg, path=True)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    if not await store.insert(name):
        raise Conflict(NAME_UNAVAILABLE, 'path_unavailable')
    return name


async def delete_entry(store: CatalogStore, name: str, label: str) -> None:
    if len(name) > SEGMENT_MAX_LENGTH or '\x00' in name:
        raise NotFound(f'{label} inexistente')
    match await store.remove(name):
        case Removal.MISSING:
            raise NotFound(f'{label} inexistente')
        case Removal.IN_USE:
            raise Conflict(f'{label} em uso por links')
