from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from junto.persistence.database import normalize_postgres_url
from junto.persistence.models import Base

config = context.config

if config.config_file_name is not None:
  fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
  database_url = config.get_main_option("sqlalchemy.url") or os.getenv("DATABASE_URL")
  if not database_url:
    raise RuntimeError("Set DATABASE_URL before running database migrations.")
  try:
    return normalize_postgres_url(database_url)
  except ValueError as error:
    raise RuntimeError("DATABASE_URL must point to PostgreSQL.") from error


def run_migrations_offline() -> None:
  context.configure(
    url=_database_url(),
    target_metadata=target_metadata,
    literal_binds=True,
    dialect_opts={"paramstyle": "named"},
    compare_type=True,
  )
  with context.begin_transaction():
    context.run_migrations()


def run_migrations_online() -> None:
  configuration = config.get_section(config.config_ini_section, {})
  configuration["sqlalchemy.url"] = _database_url()
  connectable = engine_from_config(
    configuration,
    prefix="sqlalchemy.",
    poolclass=pool.NullPool,
  )
  with connectable.connect() as connection:
    context.configure(
      connection=connection,
      target_metadata=target_metadata,
      compare_type=True,
    )
    with context.begin_transaction():
      context.run_migrations()


if context.is_offline_mode():
  run_migrations_offline()
else:
  run_migrations_online()
