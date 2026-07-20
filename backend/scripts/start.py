"""Start the single-process Junto web runtime.

Database migrations are deliberately not run here. Execute ``scripts/release.py``
as a separate release operation before replacing the application process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


def _integer_environment(name: str, *, default: int, minimum: int, maximum: int) -> int:
  raw = os.getenv(name, str(default))
  try:
    value = int(raw)
  except ValueError as error:
    raise RuntimeError(f"{name} must be an integer.") from error
  if value < minimum or value > maximum:
    raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
  return value


def build_command() -> list[str]:
  """Build the fixed one-worker Uvicorn command from bounded environment values."""

  workers = 1
  port = _integer_environment("PORT", default=8000, minimum=1, maximum=65_535)
  log_level = os.getenv("LOG_LEVEL", "info").strip().lower()
  if log_level not in {"critical", "error", "warning", "info", "debug"}:
    raise RuntimeError("LOG_LEVEL must be critical, error, warning, info, or debug.")

  forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1").strip()
  if not forwarded_allow_ips:
    raise RuntimeError("FORWARDED_ALLOW_IPS cannot be empty.")

  return [
    sys.executable,
    "-m",
    "uvicorn",
    "junto.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    str(port),
    "--workers",
    str(workers),
    "--log-level",
    log_level,
    "--forwarded-allow-ips",
    forwarded_allow_ips,
    "--no-access-log",
    "--no-server-header",
    "--timeout-keep-alive",
    "5",
  ]


def main() -> None:
  os.chdir(BACKEND_DIRECTORY)
  command = build_command()
  if os.name == "nt":
    # Windows does not reliably preserve the attached console across os.execv.
    # The production Linux container still replaces the launcher process below.
    raise SystemExit(subprocess.run(command, check=False).returncode)
  os.execv(command[0], command)


if __name__ == "__main__":
  main()
