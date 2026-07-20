from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from junto.config import Settings
from junto.main import create_app


@dataclass(slots=True)
class MutableClock:
  now: datetime = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)

  def __call__(self) -> datetime:
    return self.now

  def advance(self, **delta: float) -> None:
    self.now += timedelta(**delta)


@dataclass(slots=True)
class RecordingScheduler:
  """Deterministic scheduler: tests explicitly release only callbacks that are due now."""

  callbacks: list[tuple[float, Callable[[], None]]] = field(default_factory=list)

  def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> None:
    self.callbacks.append((delay_seconds, callback))

  def run_ready(self) -> int:
    run_count = 0
    while True:
      ready_index = next(
        (index for index, (delay, _) in enumerate(self.callbacks) if delay <= 0),
        None,
      )
      if ready_index is None:
        return run_count
      _, callback = self.callbacks.pop(ready_index)
      callback()
      run_count += 1


@dataclass(frozen=True, slots=True)
class AppHarness:
  app: FastAPI
  clock: MutableClock
  scheduler: RecordingScheduler


# Compatibility names used by the focused domain/API suites.
ManualClock = MutableClock
CapturingScheduler = RecordingScheduler


def mutate(
  client: TestClient,
  method: str,
  path: str,
  **kwargs: Any,
) -> Response:
  session = client.get("/api/session")
  assert session.status_code == 200
  headers = dict(kwargs.pop("headers", {}) or {})
  headers["X-CSRF-Token"] = session.json()["csrfToken"]
  return client.request(method, path, headers=headers, **kwargs)


def create_prepared_room(
  host: TestClient,
  *,
  duration_minutes: int = 20,
) -> tuple[str, str, str]:
  created = mutate(
    host,
    "POST",
    "/api/rooms",
    json={
      "title": "Prepared discussion",
      "policy": "teach",
      "durationMinutes": duration_minutes,
    },
  )
  assert created.status_code == 201, created.text
  room = created.json()
  question = mutate(
    host,
    "POST",
    f"/api/rooms/{room['roomId']}/questions",
    json={
      "prompt": "Explain the strongest tradeoff in this approach.",
      "coverageUnits": [{"text": "Identifies and supports a material tradeoff"}],
    },
  )
  assert question.status_code == 201, question.text
  return room["roomId"], room["joinCode"], question.json()["id"]


def join_participant(app: FastAPI, join_code: str, display_name: str) -> TestClient:
  participant = TestClient(app)
  joined = mutate(
    participant,
    "POST",
    f"/api/join/{join_code}",
    json={"displayName": display_name},
  )
  assert joined.status_code == 201, joined.text
  return participant


@pytest.fixture
def harness(tmp_path: Path) -> AppHarness:
  clock = MutableClock()
  scheduler = RecordingScheduler()
  app = create_app(
    app_settings=Settings(
      session_secret="test-session-secret-with-sufficient-entropy",
    ),
    scheduler=scheduler,
    clock=clock,
    frontend_dist=tmp_path / "no-frontend-build",
  )
  return AppHarness(app=app, clock=clock, scheduler=scheduler)


@pytest.fixture
def backend(tmp_path: Path) -> tuple[FastAPI, CapturingScheduler, ManualClock]:
  clock = ManualClock()
  scheduler = CapturingScheduler()
  app = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    scheduler=scheduler,
    clock=clock,
    frontend_dist=tmp_path / "no-frontend-build",
  )
  return app, scheduler, clock
