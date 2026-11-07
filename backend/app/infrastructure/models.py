from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, Sequence, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..core import CODE_BITS, DESTINATION_MAX_LENGTH, SEGMENT_MAX_LENGTH


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = 'projects'
    name: Mapped[str] = mapped_column(String(SEGMENT_MAX_LENGTH), primary_key=True)


class PublicPath(Base):
    __tablename__ = 'public_paths'
    path: Mapped[str] = mapped_column(String(SEGMENT_MAX_LENGTH), primary_key=True)


link_sequence = Sequence('link_sequence', start=1, maxvalue=2**CODE_BITS - 1, cycle=False)


class Link(Base):
    __tablename__ = 'links'
    short_code: Mapped[str] = mapped_column(String(SEGMENT_MAX_LENGTH), primary_key=True)
    sequence_id: Mapped[int] = mapped_column(BigInteger, link_sequence, unique=True, nullable=False)
    destination_url: Mapped[str] = mapped_column(String(DESTINATION_MAX_LENGTH), unique=True, nullable=False)
    project_name: Mapped[str | None] = mapped_column(ForeignKey('projects.name', onupdate='CASCADE'))
    public_path: Mapped[str | None] = mapped_column(ForeignKey('public_paths.path'))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class AppConfig(Base):
    __tablename__ = 'app_config'
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))


class AccessEvent(Base):
    __tablename__ = 'access_events'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, 'postgresql'), nullable=False)
