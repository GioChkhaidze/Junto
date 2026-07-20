from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from junto.persistence.database import (
  create_postgres_engine,
  create_session_factory,
  normalize_postgres_url,
)
from junto.repositories.postgres import PostgresRoomRepository

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@dataclass(frozen=True, slots=True)
class PostgresHarness:
  engine: Engine
  session_factory: sessionmaker[Session]
  repository: PostgresRoomRepository
  alembic_config: Config


def _alembic_config(database_url: str) -> Config:
  config = Config(str(BACKEND_ROOT / "alembic.ini"))
  config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
  return config


@pytest.fixture
def postgres_harness() -> Iterator[PostgresHarness]:
  if TEST_DATABASE_URL is None:
    pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests.")
  schema_name = f"junto_test_{uuid4().hex}"
  assert re.fullmatch(r"[a-z0-9_]+", schema_name)
  normalized_url = normalize_postgres_url(TEST_DATABASE_URL)
  admin_engine = create_engine(normalized_url, pool_pre_ping=True)
  with admin_engine.begin() as connection:
    connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')

  schema_url = make_url(normalized_url).update_query_dict({"options": f"-csearch_path={schema_name}"})
  rendered_url = schema_url.render_as_string(hide_password=False)
  alembic_config = _alembic_config(rendered_url)
  command.upgrade(alembic_config, "head")
  engine = create_postgres_engine(rendered_url, pool_size=3, max_overflow=2)
  session_factory = create_session_factory(engine)
  harness = PostgresHarness(
    engine=engine,
    session_factory=session_factory,
    repository=PostgresRoomRepository(session_factory),
    alembic_config=alembic_config,
  )
  try:
    yield harness
  finally:
    engine.dispose()
    command.downgrade(alembic_config, "base")
    with admin_engine.begin() as connection:
      connection.exec_driver_sql(f'DROP SCHEMA "{schema_name}" CASCADE')
    admin_engine.dispose()
