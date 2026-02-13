"""SQLAlchemy engine and session configuration."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# Engine and session factory — configured at app startup via init_db()
engine = None
SessionLocal = sessionmaker()


def init_db(database_url: str, echo: bool = False):
    """Initialize the database engine and bind the session factory.

    Args:
        database_url: SQLAlchemy database URL (e.g. postgresql://user:pass@host/db)
        echo: If True, log all SQL statements
    """
    global engine, SessionLocal
    engine = create_engine(database_url, echo=echo)
    SessionLocal.configure(bind=engine)


def get_session():
    """Yield a database session. Use as a dependency or context manager."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
