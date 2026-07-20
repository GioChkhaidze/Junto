from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from junto.config import Settings
from junto.domain.errors import DomainError
from junto.main import create_app
from junto.services.personas import (
  is_synthetic_participant,
  synthetic_participant_id,
  synthetic_personas,
)
from tests.conftest import (
  CapturingScheduler,
  ManualClock,
  create_prepared_room,
  join_participant,
  mutate,
)

BackendFixture = tuple[FastAPI, CapturingScheduler, ManualClock]


def _open_prepared_room(
  app: FastAPI,
  *,
  duration_minutes: int = 20,
) -> tuple[TestClient, str, str, str]:
  host = TestClient(app)
  room_id, join_code, question_id = create_prepared_room(
    host,
    duration_minutes=duration_minutes,
  )
  opened = mutate(host, "POST", f"/api/rooms/{room_id}/open")
  assert opened.status_code == 200, opened.text
  return host, room_id, join_code, question_id


def _create_exact_size_lobby(host: TestClient, *, size: int) -> tuple[str, str]:
  created = mutate(
    host,
    "POST",
    "/api/rooms",
    json={
      "title": "Exact-size room",
      "groupSize": {"minimum": size, "preferred": size, "maximum": size},
    },
  )
  assert created.status_code == 201, created.text
  room_id = created.json()["roomId"]
  question = mutate(
    host,
    "POST",
    f"/api/rooms/{room_id}/questions",
    json={
      "prompt": "Explain the choice.",
      "coverageUnits": [{"text": "Explains the choice"}],
    },
  )
  assert question.status_code == 201, question.text
  opened = mutate(host, "POST", f"/api/rooms/{room_id}/open")
  assert opened.status_code == 200, opened.text
  return room_id, question.json()["id"]


def _synthetic_ids(app: FastAPI, room_id: str) -> tuple[UUID, ...]:
  room = app.state.room_service.get_room(UUID(room_id))
  return tuple(
    participant_id for participant_id, participant in room.participants.items() if is_synthetic_participant(participant)
  )


def _answer_matrix(
  participant_ids: tuple[UUID, ...],
  question_ids: tuple[UUID, ...],
) -> dict[UUID, dict[UUID, str]]:
  return {
    participant_id: {
      question_id: f"Response {participant_index + 1} to question {question_index + 1}."
      for question_index, question_id in enumerate(question_ids)
    }
    for participant_index, participant_id in enumerate(participant_ids)
  }


def test_configure_synthetic_cohort_is_target_based_idempotent_and_preserves_humans(
  backend: BackendFixture,
) -> None:
  app, _scheduler, clock = backend
  host, room_id, join_code, _question_id = _open_prepared_room(app)
  human = join_participant(app, join_code, "Human participant")
  human_id = UUID(human.get(f"/api/rooms/{room_id}/participant").json()["participant"]["participantId"])
  service = app.state.room_service
  seed = 41
  five = synthetic_personas(5, seed=seed)

  configured = service.configure_synthetic_cohort(UUID(room_id), five, seed=seed)

  expected_five = {synthetic_participant_id(UUID(room_id), persona.id, seed=seed) for persona in five}
  assert human_id in configured.participants
  assert set(_synthetic_ids(app, room_id)) == expected_five
  first_updated_at = configured.updated_at

  clock.advance(minutes=5)
  repeated = service.configure_synthetic_cohort(UUID(room_id), five, seed=seed)
  assert repeated.updated_at == first_updated_at
  assert set(_synthetic_ids(app, room_id)) == expected_five

  ten = synthetic_personas(10, seed=seed)
  resized = service.configure_synthetic_cohort(UUID(room_id), ten, seed=seed)
  expected_ten = {synthetic_participant_id(UUID(room_id), persona.id, seed=seed) for persona in ten}
  assert set(_synthetic_ids(app, room_id)) == expected_ten
  assert expected_five < expected_ten
  assert human_id in resized.participants
  assert len(resized.participants) == 11

  removed = service.configure_synthetic_cohort(UUID(room_id), (), seed=seed)
  assert set(removed.participants) == {human_id}
  assert _synthetic_ids(app, room_id) == ()
  host.close()
  human.close()


def test_infeasible_synthetic_resize_rolls_back_without_changing_valid_roster(
  backend: BackendFixture,
) -> None:
  app, _scheduler, _clock = backend
  host = TestClient(app)
  room_id, _question_id = _create_exact_size_lobby(host, size=3)
  service = app.state.room_service
  service.configure_synthetic_cohort(
    UUID(room_id),
    synthetic_personas(6),
    seed=41,
  )
  before = service.get_room(UUID(room_id))

  with pytest.raises(DomainError) as captured:
    service.configure_synthetic_cohort(
      UUID(room_id),
      synthetic_personas(5),
      seed=41,
    )

  assert captured.value.code == "GROUP_SIZE_INFEASIBLE"
  assert service.get_room(UUID(room_id)) == before
  host.close()


def test_synthetic_resize_enforces_room_capacity_atomically(tmp_path: Path) -> None:
  clock = ManualClock()
  scheduler = CapturingScheduler()
  app = create_app(
    app_settings=Settings(
      session_secret="synthetic-capacity-test-secret",
      max_participants_per_room=5,
    ),
    scheduler=scheduler,
    clock=clock,
    frontend_dist=tmp_path / "no-frontend-build",
  )
  host, room_id, _join_code, _question_id = _open_prepared_room(app)
  service = app.state.room_service
  service.configure_synthetic_cohort(UUID(room_id), synthetic_personas(5), seed=41)
  before = service.get_room(UUID(room_id))

  with pytest.raises(DomainError) as captured:
    service.configure_synthetic_cohort(
      UUID(room_id),
      synthetic_personas(6),
      seed=41,
    )

  assert captured.value.code == "ROOM_FULL"
  assert service.get_room(UUID(room_id)) == before
  host.close()


def test_bulk_synthetic_completion_writes_once_and_claims_analysis_once(
  backend: BackendFixture,
) -> None:
  app, scheduler, _clock = backend
  host, room_id, _join_code, question_id = _open_prepared_room(app)
  service = app.state.room_service
  service.configure_synthetic_cohort(UUID(room_id), synthetic_personas(5), seed=41)
  started = mutate(host, "POST", f"/api/rooms/{room_id}/start")
  assert started.status_code == 200, started.text
  participant_ids = _synthetic_ids(app, room_id)
  matrix = _answer_matrix(participant_ids, (UUID(question_id),))
  matrix[participant_ids[0]][UUID(question_id)] = "   "

  response_count = service.complete_synthetic_responses(UUID(room_id), matrix)

  saved = service.get_room(UUID(room_id))
  assert response_count == 4
  assert len(saved.responses) == 4
  assert all(saved.participants[item].submitted_at is not None for item in participant_ids)
  assert saved.status == "analyzing"
  assert saved.analysis_trigger == "all_submitted"
  assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 1

  with pytest.raises(DomainError) as captured:
    service.complete_synthetic_responses(UUID(room_id), {})
  assert captured.value.code == "ROOM_NOT_ANSWERING"
  assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 1
  host.close()


def test_synthetic_mutations_enforce_lobby_and_answering_phases(
  backend: BackendFixture,
) -> None:
  app, _scheduler, _clock = backend
  host, room_id, _join_code, question_id = _open_prepared_room(app)
  service = app.state.room_service
  personas = synthetic_personas(5)
  service.configure_synthetic_cohort(UUID(room_id), personas, seed=41)
  participant_ids = _synthetic_ids(app, room_id)

  with pytest.raises(DomainError) as before_start:
    service.complete_synthetic_responses(
      UUID(room_id),
      _answer_matrix(participant_ids, (UUID(question_id),)),
    )
  assert before_start.value.code == "ROOM_NOT_ANSWERING"

  mutate(host, "POST", f"/api/rooms/{room_id}/start")
  with pytest.raises(DomainError) as after_start:
    service.configure_synthetic_cohort(UUID(room_id), personas, seed=41)
  assert after_start.value.code == "ROOM_NOT_IN_LOBBY"
  host.close()


def test_concurrent_bulk_synthetic_completion_claims_and_schedules_once(
  backend: BackendFixture,
) -> None:
  app, scheduler, _clock = backend
  host, room_id, _join_code, question_id = _open_prepared_room(app)
  service = app.state.room_service
  service.configure_synthetic_cohort(UUID(room_id), synthetic_personas(5), seed=41)
  mutate(host, "POST", f"/api/rooms/{room_id}/start")
  matrix = _answer_matrix(_synthetic_ids(app, room_id), (UUID(question_id),))

  def complete() -> int | str:
    try:
      return int(service.complete_synthetic_responses(UUID(room_id), matrix))
    except DomainError as error:
      return error.code

  with ThreadPoolExecutor(max_workers=2) as executor:
    outcomes = tuple(executor.map(lambda _index: complete(), range(2)))

  assert outcomes.count(5) == 1
  assert outcomes.count("ROOM_NOT_ANSWERING") == 1
  assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 1
  host.close()


def test_bulk_synthetic_completion_preserves_human_drafts_and_waits_for_humans(
  backend: BackendFixture,
) -> None:
  app, scheduler, _clock = backend
  host, room_id, join_code, question_id = _open_prepared_room(app)
  human = join_participant(app, join_code, "Human participant")
  human_id = UUID(human.get(f"/api/rooms/{room_id}/participant").json()["participant"]["participantId"])
  service = app.state.room_service
  service.configure_synthetic_cohort(UUID(room_id), synthetic_personas(5), seed=41)
  started = mutate(host, "POST", f"/api/rooms/{room_id}/start")
  assert started.status_code == 200, started.text
  drafted = mutate(
    human,
    "PUT",
    f"/api/rooms/{room_id}/responses/{question_id}",
    json={"text": "A human draft that must remain untouched."},
  )
  assert drafted.status_code == 200, drafted.text
  participant_ids = _synthetic_ids(app, room_id)

  assert (
    service.complete_synthetic_responses(
      UUID(room_id),
      _answer_matrix(participant_ids, (UUID(question_id),)),
    )
    == 5
  )

  saved = service.get_room(UUID(room_id))
  assert saved.status == "answering"
  assert saved.participants[human_id].submitted_at is None
  assert saved.responses[(human_id, UUID(question_id))].text == ("A human draft that must remain untouched.")
  assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 0
  assert service.complete_synthetic_responses(UUID(room_id), {}) == 0
  host.close()
  human.close()


def test_bulk_synthetic_completion_rejects_non_exact_or_oversized_matrices_atomically(
  backend: BackendFixture,
) -> None:
  app, _scheduler, _clock = backend
  host, room_id, _join_code, question_id = _open_prepared_room(app)
  service = app.state.room_service
  service.configure_synthetic_cohort(UUID(room_id), synthetic_personas(5), seed=41)
  mutate(host, "POST", f"/api/rooms/{room_id}/start")
  participant_ids = _synthetic_ids(app, room_id)
  question_uuid = UUID(question_id)
  valid = _answer_matrix(participant_ids, (question_uuid,))
  before = service.get_room(UUID(room_id))

  missing_participant = dict(valid)
  del missing_participant[participant_ids[0]]
  extra_participant = dict(valid)
  extra_participant[uuid4()] = {question_uuid: "Invented participant."}
  missing_question = {
    participant_id: ({} if participant_id == participant_ids[0] else answers)
    for participant_id, answers in valid.items()
  }
  extra_question = {
    participant_id: ({**answers, uuid4(): "Invented question."} if participant_id == participant_ids[0] else answers)
    for participant_id, answers in valid.items()
  }
  oversized = {
    participant_id: ({question_uuid: "x" * 1_501} if participant_id == participant_ids[0] else answers)
    for participant_id, answers in valid.items()
  }
  cases: tuple[tuple[Mapping[UUID, Mapping[UUID, str]], str], ...] = (
    (missing_participant, "SYNTHETIC_PARTICIPANT_MATRIX_INVALID"),
    (extra_participant, "SYNTHETIC_PARTICIPANT_MATRIX_INVALID"),
    (missing_question, "SYNTHETIC_QUESTION_MATRIX_INVALID"),
    (extra_question, "SYNTHETIC_QUESTION_MATRIX_INVALID"),
    (oversized, "ANSWER_TOO_LONG"),
  )

  for matrix, expected_code in cases:
    with pytest.raises(DomainError) as captured:
      service.complete_synthetic_responses(UUID(room_id), matrix)
    assert captured.value.code == expected_code
    assert service.get_room(UUID(room_id)) == before
  host.close()


def test_bulk_synthetic_completion_rejects_late_answers_and_claims_deadline(
  backend: BackendFixture,
) -> None:
  app, scheduler, clock = backend
  host, room_id, _join_code, question_id = _open_prepared_room(
    app,
    duration_minutes=1,
  )
  service = app.state.room_service
  service.configure_synthetic_cohort(UUID(room_id), synthetic_personas(5), seed=41)
  mutate(host, "POST", f"/api/rooms/{room_id}/start")
  participant_ids = _synthetic_ids(app, room_id)
  clock.advance(minutes=1, seconds=1)

  with pytest.raises(DomainError) as captured:
    service.complete_synthetic_responses(
      UUID(room_id),
      _answer_matrix(participant_ids, (UUID(question_id),)),
    )

  assert captured.value.code == "DEADLINE_PASSED"
  saved = service.get_room(UUID(room_id))
  assert saved.status == "analyzing"
  assert saved.analysis_trigger == "deadline"
  assert saved.responses == {}
  assert all(saved.participants[item].submitted_at is None for item in participant_ids)
  assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 1
  host.close()
