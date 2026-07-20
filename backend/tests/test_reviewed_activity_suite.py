from __future__ import annotations

import json
import urllib.error
from argparse import Namespace
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from junto.config import Settings
from junto.main import create_app
from junto.services.personas import synthetic_personas
from scripts import load_demo
from tests.conftest import RecordingScheduler


class AppBrowserClient:
  def __init__(self, app: FastAPI, scheduler: RecordingScheduler) -> None:
    self._client = TestClient(app)
    self._scheduler = scheduler

  def request(
    self,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    if method == "GET" and path.endswith("/status"):
      self._scheduler.run_ready()
    headers: dict[str, str] = {}
    if method not in {"GET", "HEAD", "OPTIONS"}:
      session = self._client.get("/api/session")
      assert session.status_code == 200
      headers["X-CSRF-Token"] = session.json()["csrfToken"]
    response = self._client.request(method, path, headers=headers, json=payload)
    if response.status_code >= 400:
      body = response.json().get("error", {})
      raise load_demo.ApiFailure(f"{response.status_code} {body.get('code', 'UNKNOWN')}")
    if not response.content:
      return {}
    result = response.json()
    assert isinstance(result, dict)
    return result


class RecordingOpenRouterClient:
  def __init__(self, participant_count: int, *, status: str = "published", last_error: str | None = None) -> None:
    self.participant_count = participant_count
    self.status = status
    self.last_error = last_error
    self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
    self.uploads: list[tuple[str, str, str]] = []

  def request(
    self,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    self.calls.append((method, path, payload))
    if method == "POST" and path == "/api/rooms":
      return {"roomId": "room-1", "joinCode": "ABC123"}
    if method == "POST" and path.endswith("/questions"):
      return {"id": "question-1"}
    if method == "PUT" and path.endswith("/synthetic-cohort"):
      return {"syntheticParticipantCount": self.participant_count}
    if method == "POST" and path.endswith("/synthetic-responses"):
      return {"models": ["example/model"]}
    if method == "GET" and path.endswith("/status"):
      return {"status": self.status}
    if method == "GET" and path == "/api/rooms/room-1":
      return {"lastError": self.last_error, "debugDetails": "must not be copied"}
    if method == "GET" and path.endswith("/groups"):
      members = [{"participantId": f"participant-{index:02d}"} for index in range(self.participant_count)]
      groups = [{"members": members[index : index + 5]} for index in range(0, len(members), 5)]
      return {
        "generationMode": "coverage_aware",
        "groups": groups,
        "solver": {"status": "optimal"},
        "coverageReport": {
          "fullyCoveredGroupQuestions": len(groups),
          "totalGroupQuestions": len(groups),
        },
      }
    return {}

  def upload_text(self, path: str, *, file_name: str, text: str) -> dict[str, Any]:
    self.uploads.append((path, file_name, text))
    return {"material": {"id": "material-1"}}


def _arguments(**overrides: Any) -> Namespace:
  values = {
    "base_url": "http://127.0.0.1:8000",
    "duration_minutes": 20,
    "fixture_paths": None,
    "participants": 20,
    "poll_rounds": 0,
    "seed": 41,
    "student_source": "reviewed",
    "wait_seconds": 5.0,
  }
  values.update(overrides)
  return Namespace(**values)


def _fixture_by_id() -> dict[str, dict[str, Any]]:
  return {
    fixture["fixtureId"]: fixture
    for path in load_demo.discover_reviewed_activity_paths()
    if isinstance((fixture := json.loads(path.read_text(encoding="utf-8"))), dict)
  }


def test_activity_discovery_is_sorted_and_includes_the_cross_subject_corpus() -> None:
  paths = load_demo.discover_reviewed_activity_paths()
  fixtures = load_demo.load_reviewed_questions(paths)

  assert [path.name for path in paths] == sorted(path.name for path in paths)
  assert len(paths) == len(fixtures) == 10
  assert {fixture.subject for fixture in fixtures} >= {"design", "history", "philosophy", "programming"}
  assert len({fixture.fixture_id for fixture in fixtures}) == len(fixtures)


def test_reviewed_answers_are_permuted_by_activity_without_changing_their_multiset() -> None:
  fixtures = load_demo.load_reviewed_questions(load_demo.discover_reviewed_activity_paths())

  for fixture in fixtures:
    unpermuted = tuple(fixture.answer_for(index) for index in range(20))
    first = fixture.answer_schedule(20, seed=41)
    assert first == fixture.answer_schedule(20, seed=41)
    assert sorted(first) == sorted(unpermuted)
  assert any(
    fixture.answer_schedule(20, seed=41) != tuple(fixture.answer_for(index) for index in range(20))
    for fixture in fixtures
  )


def test_reviewed_suite_runs_each_fixture_as_a_full_independent_activity(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  scheduler = RecordingScheduler()
  app = create_app(
    app_settings=Settings(
      environment="test",
      session_secret="reviewed-activity-suite-secret",
      engine_mode="recorded",
      join_rate_limit_per_minute=1_000,
      room_create_rate_limit_per_minute=1_000,
      answer_rate_limit_per_minute=10_000,
      status_rate_limit_per_minute=10_000,
      solver_timeout_seconds=5.0,
    ),
    scheduler=scheduler,
    frontend_dist=tmp_path / "no-frontend-build",
  )
  monkeypatch.setattr(load_demo, "BrowserClient", lambda _base_url: AppBrowserClient(app, scheduler))

  result = load_demo.load_activity_suite(_arguments())

  fixture_by_id = _fixture_by_id()
  activities = result["activities"]
  assert result["allPublished"] is True
  assert result["activityCount"] == len(activities) == len(fixture_by_id) == 10
  assert len({activity["roomId"] for activity in activities}) == len(activities)
  assert len({activity["joinCode"] for activity in activities}) == len(activities)
  expected_names = {persona.display_name for persona in synthetic_personas(20, seed=41)}

  for activity in activities:
    assert activity["studentSource"] == "reviewed"
    assert activity["status"] == "published"
    assert activity["participantCount"] == 20
    assert sum(activity["groupSizes"]) == 20
    assert all(3 <= size <= 5 for size in activity["groupSizes"])
    assert activity["coverageReport"]["totalGroupQuestions"] == activity["groupCount"]
    assert activity["coverageReport"]["fullyCoveredGroupQuestions"] > 0

    room = app.state.room_service.get_room(UUID(activity["roomId"]))
    assert len(room.questions) == 1
    assert {participant.display_name for participant in room.participants.values()} == expected_names
    fixture = fixture_by_id[activity["fixtureId"]]
    question = room.questions[0]
    assert question.prompt == fixture["questionPrompt"]
    assert {response.text for response in room.responses.values()} == {
      participant["answer"] for participant in fixture["participants"] if participant["answer"]
    }
    assert room.analysis_result is not None
    assert room.analysis_result.model == "recorded-semantic-v1"


def test_openrouter_activity_uses_only_the_public_material_and_generation_routes(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  fixture = load_demo.load_reviewed_questions((load_demo.discover_reviewed_activity_paths()[0],))[0]
  recorder = RecordingOpenRouterClient(participant_count=20)
  captured_timeouts: list[float] = []

  def browser_client(_base_url: str, *, timeout_seconds: float = 10.0) -> RecordingOpenRouterClient:
    captured_timeouts.append(timeout_seconds)
    return recorder

  monkeypatch.setattr(load_demo, "BrowserClient", browser_client)

  result = load_demo.run_openrouter_activity(_arguments(student_source="openrouter"), fixture)

  assert result["status"] == "published"
  assert result["models"] == ["example/model"]
  assert captured_timeouts == [5.0]
  assert recorder.uploads == [("/api/rooms/room-1/materials", "student-reference.txt", fixture.reference_material)]
  generation_calls = [call for call in recorder.calls if call[1].endswith("/synthetic-responses")]
  assert generation_calls == [("POST", "/api/development/rooms/room-1/synthetic-responses", {"source": "openrouter"})]
  question_calls = [call for call in recorder.calls if call[1].endswith("/questions")]
  assert len(question_calls) == 1
  assert question_calls[0][2] is not None
  assert "referenceMaterial" not in question_calls[0][2]
  assert all("expectedCoverage" not in json.dumps(call) for call in recorder.calls)
  assert all("expectedFamilies" not in json.dumps(call) for call in recorder.calls)


def test_failed_activity_reports_only_the_host_visible_sanitized_error(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  fixture = load_demo.load_reviewed_questions((load_demo.discover_reviewed_activity_paths()[0],))[0]
  recorder = RecordingOpenRouterClient(
    participant_count=20,
    status="failed",
    last_error="Response analysis did not finish within the configured time limit.",
  )
  monkeypatch.setattr(load_demo, "BrowserClient", lambda _url, **_kwargs: recorder)

  result = load_demo.run_openrouter_activity(_arguments(student_source="openrouter"), fixture)

  assert result["status"] == "failed"
  assert result["lastError"] == "Response analysis did not finish within the configured time limit."
  assert "debugDetails" not in result
  assert ("GET", "/api/rooms/room-1", None) in recorder.calls


def test_long_analysis_wait_uses_a_rate_limit_safe_polling_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
  now = 0.0
  request_times: list[float] = []

  class CountingClient:
    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
      del method, path, payload
      request_times.append(now)
      return {"status": "analyzing"}

  def monotonic() -> float:
    return now

  def sleep(seconds: float) -> None:
    nonlocal now
    now += seconds

  monkeypatch.setattr("scripts.load_demo.time.monotonic", monotonic)
  monkeypatch.setattr("scripts.load_demo.time.sleep", sleep)

  status = load_demo.wait_for_result(CountingClient(), "room-1", wait_seconds=240.0)  # type: ignore[arg-type]

  assert status == "analyzing"
  assert len(request_times) == 160
  assert all(
    second - first == load_demo.POLL_INTERVAL_SECONDS
    for first, second in zip(request_times, request_times[1:], strict=False)
  )
  maximum_requests_per_minute = max(
    sum(start <= request_time < start + 60 for request_time in request_times) for start in request_times
  )
  assert maximum_requests_per_minute == 40
  assert maximum_requests_per_minute < Settings().status_rate_limit_per_minute


def test_wait_for_answering_uses_the_same_polling_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
  now = 0.0
  request_times: list[float] = []

  class CountingClient:
    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
      del method, path, payload
      request_times.append(now)
      return {"status": "answering" if len(request_times) == 3 else "lobby"}

  def sleep(seconds: float) -> None:
    nonlocal now
    now += seconds

  monkeypatch.setattr("scripts.load_demo.time.monotonic", lambda: now)
  monkeypatch.setattr("scripts.load_demo.time.sleep", sleep)
  client = CountingClient()

  room = load_demo.wait_for_answering([client], "room-1", wait_seconds=10.0)  # type: ignore[list-item]

  assert room["status"] == "answering"
  assert request_times == [0.0, load_demo.POLL_INTERVAL_SECONDS, load_demo.POLL_INTERVAL_SECONDS * 2]


def test_suite_failure_preserves_only_safe_created_room_context(monkeypatch: pytest.MonkeyPatch) -> None:
  fixture_path = load_demo.discover_reviewed_activity_paths()[0]
  fixture = load_demo.load_reviewed_questions((fixture_path,))[0]

  class FailingClient(RecordingOpenRouterClient):
    def request(
      self,
      method: str,
      path: str,
      payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
      if path.endswith("/synthetic-cohort"):
        raise load_demo.ApiFailure("sanitized failure")
      return super().request(method, path, payload)

  recorder = FailingClient(participant_count=20)
  monkeypatch.setattr(load_demo, "BrowserClient", lambda _url, **_kwargs: recorder)

  result = load_demo.load_activity_suite(
    _arguments(student_source="openrouter", fixture_paths=[fixture_path]),
  )

  assert result["activities"] == [
    {
      "fixtureId": fixture.fixture_id,
      "roomId": "room-1",
      "joinCode": "ABC123",
      "status": "loader_failed",
      "error": "sanitized failure",
    }
  ]


def test_openrouter_suite_rejects_unsupported_cohort_size_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
  client_created = False

  def browser_client(_base_url: str, *, timeout_seconds: float = 10.0) -> RecordingOpenRouterClient:
    del timeout_seconds
    nonlocal client_created
    client_created = True
    return RecordingOpenRouterClient(participant_count=11)

  monkeypatch.setattr(load_demo, "BrowserClient", browser_client)

  with pytest.raises(ValueError, match="must be 5, 10, or 20"):
    load_demo.load_activity_suite(_arguments(student_source="openrouter", participants=11))
  assert client_created is False


@pytest.mark.parametrize("participants", [5, 10, 20])
def test_openrouter_suite_accepts_each_advertised_cohort_size(
  monkeypatch: pytest.MonkeyPatch,
  participants: int,
) -> None:
  fixture_path = load_demo.discover_reviewed_activity_paths()[0]
  observed: list[int] = []

  def run_activity(arguments: Namespace, _fixture: load_demo.FixtureQuestion) -> dict[str, Any]:
    observed.append(arguments.participants)
    return {"status": "published"}

  monkeypatch.setattr(load_demo, "discover_reviewed_activity_paths", lambda: (fixture_path,))
  monkeypatch.setattr(load_demo, "run_openrouter_activity", run_activity)

  result = load_demo.load_activity_suite(_arguments(student_source="openrouter", participants=participants))

  assert result["allPublished"] is True
  assert observed == [participants]


def test_reviewed_suite_still_accepts_other_classroom_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
  fixture_path = load_demo.discover_reviewed_activity_paths()[0]

  def run_activity(arguments: Namespace, _fixture: load_demo.FixtureQuestion) -> dict[str, Any]:
    return {"participantCount": arguments.participants, "status": "published"}

  monkeypatch.setattr(load_demo, "discover_reviewed_activity_paths", lambda: (fixture_path,))
  monkeypatch.setattr(load_demo, "run_reviewed_activity", run_activity)

  result = load_demo.load_activity_suite(_arguments(student_source="reviewed", participants=11))

  assert result["allPublished"] is True
  assert result["activities"] == [{"participantCount": 11, "status": "published"}]


@pytest.mark.parametrize("loader", (load_demo.load_activity_suite, load_demo.load_fixture))
def test_loaders_reject_a_non_positive_wait_before_http(loader: Any) -> None:
  with pytest.raises(ValueError, match="--wait-seconds must be greater than zero"):
    loader(_arguments(wait_seconds=0.0))


def test_browser_client_maps_socket_timeout_to_sanitized_api_failure(monkeypatch: pytest.MonkeyPatch) -> None:
  client = load_demo.BrowserClient("http://127.0.0.1:8000")

  def time_out(*_args: Any, **_kwargs: Any) -> Any:
    raise TimeoutError("private socket details")

  monkeypatch.setattr(client._opener, "open", time_out)

  with pytest.raises(load_demo.ApiFailure, match="fixture request timed out") as failure:
    client.request("GET", "/api/session")
  assert "private socket details" not in str(failure.value)


@pytest.mark.parametrize(
  "transport_error",
  (
    ConnectionAbortedError(10053, "private socket details"),
    urllib.error.URLError(ConnectionAbortedError(10053, "private socket details")),
  ),
)
def test_browser_client_sanitizes_connection_abort_without_retrying_mutation(
  monkeypatch: pytest.MonkeyPatch,
  transport_error: OSError,
) -> None:
  client = load_demo.BrowserClient("http://127.0.0.1:8000")
  client._csrf_token = "test-csrf"
  calls = 0

  def abort(*_args: Any, **_kwargs: Any) -> Any:
    nonlocal calls
    calls += 1
    raise transport_error

  monkeypatch.setattr(client._opener, "open", abort)

  with pytest.raises(load_demo.ApiFailure) as failure:
    client.request("POST", "/api/join/ABC123", {"displayName": "Student"})

  message = str(failure.value)
  assert message == "The connection to Junto was interrupted before the fixture request completed."
  assert "10053" not in message
  assert "private socket details" not in message
  assert "Traceback" not in message
  assert calls == 1


def test_activity_suite_preserves_connection_failure_context_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
  fixture_paths = load_demo.discover_reviewed_activity_paths()[:2]
  fixtures = load_demo.load_reviewed_questions(fixture_paths)
  calls: list[str] = []

  def run_activity(_arguments: Namespace, fixture: load_demo.FixtureQuestion) -> dict[str, Any]:
    calls.append(fixture.fixture_id)
    if fixture.fixture_id == fixtures[0].fixture_id:
      raise load_demo.ActivityRunFailure(
        "The connection to Junto was interrupted before the fixture request completed.",
        room_id="room-1",
        join_code="ABC123",
      )
    return {"fixtureId": fixture.fixture_id, "status": "published"}

  monkeypatch.setattr(load_demo, "run_reviewed_activity", run_activity)

  result = load_demo.load_activity_suite(_arguments(fixture_paths=list(fixture_paths)))

  assert calls == [fixture.fixture_id for fixture in fixtures]
  assert result["allPublished"] is False
  assert result["activities"] == [
    {
      "fixtureId": fixtures[0].fixture_id,
      "roomId": "room-1",
      "joinCode": "ABC123",
      "status": "loader_failed",
      "error": "The connection to Junto was interrupted before the fixture request completed.",
    },
    {"fixtureId": fixtures[1].fixture_id, "status": "published"},
  ]
  assert "private socket details" not in json.dumps(result)
  assert "Traceback" not in json.dumps(result)


def _rate_limit_error(retry_after: int) -> urllib.error.HTTPError:
  headers = Message()
  headers["Retry-After"] = str(retry_after)
  body = BytesIO(b'{"error":{"code":"RATE_LIMITED","message":"Wait briefly."}}')
  return urllib.error.HTTPError("http://127.0.0.1:8000/api/test", 429, "rate limited", headers, body)


def test_browser_client_handles_rounded_retry_hints_and_successive_limits(monkeypatch: pytest.MonkeyPatch) -> None:
  client = load_demo.BrowserClient("http://127.0.0.1:8000")
  now = 0.0
  sleeps: list[float] = []
  block_until = iter((1.49, 3.49, 5.49))
  attempts = 0

  def open_request(*_args: Any, **_kwargs: Any) -> BytesIO:
    nonlocal attempts
    attempts += 1
    try:
      deadline = next(block_until)
    except StopIteration:
      return BytesIO(b"{}")
    remaining = deadline - now
    raise _rate_limit_error(max(1, round(remaining)))

  def sleep(seconds: float) -> None:
    nonlocal now
    sleeps.append(seconds)
    now += seconds

  monkeypatch.setattr(client._opener, "open", open_request)
  monkeypatch.setattr("scripts.load_demo.time.sleep", sleep)

  assert client.request("GET", "/api/test") == {}
  assert attempts == 4
  assert sleeps == [2.0, 2.0, 2.0]


def test_browser_client_bounds_repeated_rate_limit_waits(monkeypatch: pytest.MonkeyPatch) -> None:
  client = load_demo.BrowserClient("http://127.0.0.1:8000")
  sleeps: list[float] = []
  attempts = 0

  def open_request(*_args: Any, **_kwargs: Any) -> BytesIO:
    nonlocal attempts
    attempts += 1
    raise _rate_limit_error(60)

  monkeypatch.setattr(client._opener, "open", open_request)
  monkeypatch.setattr("scripts.load_demo.time.sleep", sleeps.append)

  with pytest.raises(load_demo.ApiFailure, match="RATE_LIMITED"):
    client.request("GET", "/api/test")

  assert attempts == load_demo.RATE_LIMIT_MAX_RETRIES + 1
  assert sleeps == [61.0] * load_demo.RATE_LIMIT_MAX_RETRIES
