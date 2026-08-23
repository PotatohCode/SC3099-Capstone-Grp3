"""
SQLAlchemy engine, session factory, and declarative base.

`get_db` (the FastAPI dependency routers use) lives in `app/core/deps.py`,
not here — this module only wires up the connection itself.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# pool_size/max_overflow per docs/recommended_design/DATABASE-SCHEMA.md's
# "Performance Optimization" section.
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass
