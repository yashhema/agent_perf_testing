"""SQLAlchemy engine and session configuration.

Supports both PostgreSQL and SQL Server backends.
The dialect is auto-detected from the database URL.
"""

from sqlalchemy import create_engine, event
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
        database_url: SQLAlchemy database URL.
            PostgreSQL:  postgresql://user:pass@host:5432/db
            SQL Server:  mssql+pyodbc://@host/db?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes
        echo: If True, log all SQL statements
    """
    global engine, SessionLocal

    engine_kwargs = {"echo": echo}

    # SQL Server: enable fast_executemany for better bulk insert performance
    if database_url.startswith("mssql"):
        engine_kwargs["fast_executemany"] = True

    engine = create_engine(database_url, **engine_kwargs)
    SessionLocal.configure(bind=engine)


def get_session():
    """Yield a database session. Use as a dependency or context manager."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
