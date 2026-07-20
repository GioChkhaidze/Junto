"""Apply the checked-in Alembic migration chain as an explicit release step."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
REPOSITORY_DIRECTORY = BACKEND_DIRECTORY.parent
ALEMBIC_CONFIGURATION = BACKEND_DIRECTORY / "alembic.ini"


def build_command() -> list[str]:
  if not ALEMBIC_CONFIGURATION.is_file():
    raise RuntimeError(f"Alembic configuration is missing: {ALEMBIC_CONFIGURATION}")
  return [
    sys.executable,
    "-m",
    "alembic",
    "-c",
    str(ALEMBIC_CONFIGURATION),
    "upgrade",
    "head",
  ]


def child_environment() -> dict[str, str]:
  environment = dict(os.environ)
  existing_path = environment.get("PYTHONPATH")
  paths = [str(BACKEND_DIRECTORY)]
  if existing_path:
    paths.append(existing_path)
  environment["PYTHONPATH"] = os.pathsep.join(paths)
  return environment


def main() -> None:
  if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is required for the release operation.")
  subprocess.run(
    build_command(),
    cwd=REPOSITORY_DIRECTORY,
    env=child_environment(),
    check=True,
  )


if __name__ == "__main__":
  main()
