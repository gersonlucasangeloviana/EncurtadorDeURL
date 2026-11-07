import hashlib
from contextlib import asynccontextmanager

from psycopg.errors import ForeignKeyViolation, SequenceGeneratorLimitExceeded, UniqueViolation
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from ..application.catalog import Removal
from ..application.errors import StorageFailure, Unavailable
from ..application.links import InsertConflict
from ..domain import Link
from . import models

_LINK_CONFLICTS = {
    (UniqueViolation, 'links_pkey'): InsertConflict.CODE,
    (UniqueViolation, 'links_destination_url_key'): InsertConflict.DESTINATION,
    (ForeignKeyViolation, 'links_project_name_fkey'): InsertConflict.PROJECT,
    (ForeignKeyViolation, 'links_public_path_fkey'): InsertConflict.PATH,
}


def advisory_key(code: str) -> int:
    digest = hashlib.blake2b(code.encode('utf-8'), digest_size=8, person=b'url-lock').digest()
    return int.from_bytes(digest, 'big', signed=True)


def _snapshot(row) -> Link:
    return Link(
        row.short_code, row.sequence_id, row.destination_url,
        row.project_name, row.public_path, row.expires_at,
        row.active, row.deleted, row.version,
    )


class PostgresLinks:
    def __init__(self, db):
        self.db = db

    async def next_sequence(self):
        try:
            return await self.db.scalar(select(models.link_sequence.next_value()))
        except DBAPIError as exc:
            if isinstance(exc.orig, SequenceGeneratorLimitExceeded):
                raise Unavailable('Sequência de links esgotada') from exc
            raise

    async def insert(self, link):
        self.db.add(models.Link(
            short_code=link.short_code, sequence_id=link.sequence_id,
            destination_url=link.destination_url, project_name=link.project_name,
            public_path=link.public_path, expires_at=link.expires_at,
        ))
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            name = getattr(getattr(exc.orig, 'diag', None), 'constraint_name', None)
            conflict = _LINK_CONFLICTS.get((type(exc.orig), name))
            if conflict is None:
                raise
            return conflict
        return None

    async def list(self):
        query = select(models.Link).where(models.Link.deleted.is_(False)).order_by(models.Link.sequence_id.desc())
        return [_snapshot(row) for row in (await self.db.scalars(query))]

    async def get(self, code):
        row = await self.db.get(models.Link, code)
        return _snapshot(row) if row is not None else None

    @asynccontextmanager
    async def lock(self, code):
        try:
            # Commit, rollback or disconnect releases the advisory lock.
            await self.db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': advisory_key(code)})
            try:
                yield
            finally:
                await self.db.rollback()
        except SQLAlchemyError as exc:
            raise StorageFailure() from exc

    async def mark_deleted(self, link):
        try:
            await self.db.execute(
                update(models.Link).where(models.Link.short_code == link.short_code)
                .values(deleted=True, version=models.Link.version + 1)
            )
            await self.db.commit()
        except SQLAlchemyError as exc:
            raise StorageFailure() from exc


class PostgresCatalog:
    def __init__(self, db, model, key, link_constraint):
        self.db = db
        self.model = model
        self.key = key
        self.link_constraint = link_constraint

    async def list(self):
        return list(await self.db.scalars(select(self.key)))

    async def insert(self, name):
        self.db.add(self.model(**{self.key.key: name}))
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if isinstance(exc.orig, UniqueViolation):
                return False
            raise
        return True

    async def remove(self, name):
        try:
            result = await self.db.execute(delete(self.model).where(self.key == name))
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if (isinstance(exc.orig, ForeignKeyViolation)
                    and exc.orig.diag.constraint_name == self.link_constraint):
                return Removal.IN_USE
            raise
        return Removal.REMOVED if result.rowcount else Removal.MISSING


def postgres_projects(db):
    return PostgresCatalog(db, models.Project, models.Project.name, 'links_project_name_fkey')


def postgres_paths(db):
    return PostgresCatalog(db, models.PublicPath, models.PublicPath.path, 'links_public_path_fkey')


def _check_legacy_schema(connection):
    # Inspector has no async API; run_sync adapts its I/O to the async driver.
    inspector = inspect(connection)
    if inspector.has_table('links') and any(
        column['name'] == 'owner_id' for column in inspector.get_columns('links')
    ):
        raise RuntimeError('Esquema anterior com usuários detectado; migre os dados antes de iniciar')


async def initialize_schema(engine, fingerprint):
    async with engine.begin() as connection:
        # Serialize initialization with a lock separate from the one-key link locks.
        await connection.execute(text('SELECT pg_advisory_xact_lock(82425, 1)'))
        await connection.run_sync(_check_legacy_schema)
        await connection.run_sync(models.Base.metadata.create_all)
        current = await connection.scalar(
            select(models.AppConfig.value).where(models.AppConfig.name == 'code_fingerprint')
        )
        if current is None:
            await connection.execute(insert(models.AppConfig).values(name='code_fingerprint', value=fingerprint))
        elif current != fingerprint:
            raise RuntimeError('Configuração do gerador incompatível com códigos existentes')


async def save_event(sessions, payload):
    async with sessions() as db:
        db.add(models.AccessEvent(payload=payload))
        await db.commit()


async def prune_access_events(engine, max_events):
    event = models.AccessEvent
    cutoff = select(func.max(event.id) - max_events).scalar_subquery()
    expired = (
        select(event.id).where(event.id <= cutoff).order_by(event.id)
        .limit(10_000).with_for_update(skip_locked=True)
    )
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL statement_timeout = '2s'"))
        await connection.execute(delete(event).where(event.id.in_(expired)))
