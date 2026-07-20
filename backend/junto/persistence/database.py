from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool


def create_postgres_engine(
  database_url: str,
  *,
  echo: bool = False,
  pool_size: int = 5,
  max_overflow: int = 5,
) -> Engine:
  """Create the ordinary PostgreSQL engine used by the application adapter.

  Connection values stay at the composition root: this module deliberately does
  not read environment variables or import application settings.
  """

  return create_engine(
    normalize_postgres_url(database_url),
    echo=echo,
    pool_pre_ping=True,
    poolclass=QueuePool,
    pool_size=pool_size,
    max_overflow=max_overflow,
  )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
  """Create sessions that keep loaded values usable through aggregate mapping."""

  return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def normalize_postgres_url(database_url: str) -> str:
  """Make provider-style PostgreSQL URLs explicitly select psycopg 3."""

  if database_url.startswith("postgresql+psycopg://"):
    return database_url
  if database_url.startswith("postgresql://"):
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
  if database_url.startswith("postgres://"):
    return database_url.replace("postgres://", "postgresql+psycopg://", 1)
  raise ValueError("Junto persistence requires a PostgreSQL database URL.")
