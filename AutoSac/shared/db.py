from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from shared.config import Settings, get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache(maxsize=1)
def get_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    return create_engine(resolved.database_url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    engine = get_engine(settings)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db_session() -> Session:
    return get_session_factory()()


def db_session_dependency():
    session = get_db_session()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope(settings: Settings | None = None) -> Session:
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_database(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
