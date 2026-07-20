from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from junto.config import Settings
from junto.main import create_app
from tests.conftest import (
  CapturingScheduler,
  ManualClock,
  create_prepared_room,
  join_participant,
  mutate,
)


def test_production_session_cookie_is_http_only_secure_and_same_site() -> None:
  app = create_app(
    app_settings=Settings(
      environment="production",
      engine_mode="openai",
      openai_api_key="test-key-never-used",
      session_secret="s" * 48,
      secure_cookies=True,
    ),
    scheduler=CapturingScheduler(),
    frontend_dist=None,
  )

  with TestClient(app, base_url="https://testserver") as client:
    response = client.get("/api/session")

  cookie = response.headers["set-cookie"].lower()
  assert "httponly" in cookie
  assert "secure" in cookie
  assert "samesite=lax" in cookie


def test_host_receives_authoritative_start_eligibility_and_reason() -> None:
  app = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  room_id, join_code, _question_id = create_prepared_room(host)
  mutate(host, "POST", f"/api/rooms/{room_id}/open")

  empty = host.get(f"/api/rooms/{room_id}").json()
  participants = [join_participant(app, join_code, name) for name in ("A", "B", "C")]
  ready = host.get(f"/api/rooms/{room_id}").json()

  assert empty["startEligibility"]["eligible"] is False
  assert empty["startEligibility"]["reasonCode"] == "minimum_participants"
  assert "startActivity" not in empty["allowedActions"]
  assert ready["startEligibility"] == {
    "eligible": True,
    "reasonCode": None,
    "message": "Starting freezes the participant list and begins everyone's shared timer.",
  }
  assert "startActivity" in ready["allowedActions"]
  for participant in participants:
    participant.close()


def test_start_eligibility_reports_an_infeasible_fixed_group_size() -> None:
  app = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  created = mutate(
    host,
    "POST",
    "/api/rooms",
    json={
      "title": "Fixed trios",
      "groupSize": {"minimum": 3, "preferred": 3, "maximum": 3},
    },
  ).json()
  room_id = created["roomId"]
  mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/questions",
    json={
      "prompt": "Compare the arguments.",
      "coverageUnits": [{"text": "States a supported conclusion"}],
    },
  )
  mutate(host, "POST", f"/api/rooms/{room_id}/open")
  participants = [join_participant(app, created["joinCode"], name) for name in ("A", "B", "C", "D")]

  view = host.get(f"/api/rooms/{room_id}").json()

  assert view["startEligibility"]["eligible"] is False
  assert view["startEligibility"]["reasonCode"] == "group_size_infeasible"
  assert "startActivity" not in view["allowedActions"]
  for participant in participants:
    participant.close()


def test_answer_and_status_rate_limits_return_retry_hints() -> None:
  app = create_app(
    app_settings=Settings(
      session_secret="test-session-secret",
      answer_rate_limit_per_minute=1,
      status_rate_limit_per_minute=1,
    ),
    scheduler=CapturingScheduler(),
    clock=ManualClock(),
  )
  host = TestClient(app)
  room_id, join_code, question_id = create_prepared_room(host)
  mutate(host, "POST", f"/api/rooms/{room_id}/open")
  participants = [join_participant(app, join_code, name) for name in ("A", "B", "C")]
  mutate(host, "POST", f"/api/rooms/{room_id}/start")

  first_status = host.get(f"/api/rooms/{room_id}/status")
  limited_status = host.get(f"/api/rooms/{room_id}/status")
  first_answer = mutate(
    participants[0],
    "PUT",
    f"/api/rooms/{room_id}/responses/{question_id}",
    json={"text": "First bounded answer"},
  )
  limited_answer = mutate(
    participants[0],
    "PUT",
    f"/api/rooms/{room_id}/responses/{question_id}",
    json={"text": "Second request in the same window"},
  )

  assert first_status.status_code == 200
  assert limited_status.status_code == 429
  assert int(limited_status.headers["Retry-After"]) >= 1
  assert limited_status.json()["error"]["code"] == "RATE_LIMITED"
  assert first_answer.status_code == 200
  assert limited_answer.status_code == 429
  assert int(limited_answer.headers["Retry-After"]) >= 1
  for participant in participants:
    participant.close()


def test_maintenance_never_deletes_rooms() -> None:
  clock = ManualClock()
  app = create_app(
    app_settings=Settings(
      session_secret="test-session-secret",
      analysis_stale_seconds=30,
    ),
    scheduler=CapturingScheduler(),
    clock=clock,
  )
  host = TestClient(app)
  room_id, join_code, _question_id = create_prepared_room(host, duration_minutes=180)
  mutate(host, "POST", f"/api/rooms/{room_id}/open")
  participants = [join_participant(app, join_code, name) for name in ("A", "B", "C")]
  mutate(host, "POST", f"/api/rooms/{room_id}/start")
  repository = app.state.room_repository

  clock.advance(days=365)
  assert app.state.room_service.run_maintenance() == 0
  assert repository.get(UUID(room_id)) is not None
  for participant in participants:
    participant.close()
