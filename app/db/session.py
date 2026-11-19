from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base


def create_db_engine(url: str, *, echo: bool = False) -> Engine:
    kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=5, max_overflow=5, pool_recycle=1800)
    return create_engine(url, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine) -> None:
    """Create tables if missing. For schema evolution, adopt Alembic (see README)."""
    from app.db import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
