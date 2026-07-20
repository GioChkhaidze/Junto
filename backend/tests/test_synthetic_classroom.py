from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from junto.config import Settings
from junto.domain.errors import DomainError
from junto.engine.openrouter import OpenRouterCompletion, OpenRouterError, OpenRouterUsage
from junto.main import create_app
from junto.services.personas import is_synthetic_participant, synthetic_personas
from junto.services.simulation import (
  OpenRouterSyntheticAnswerProvider,
  SyntheticAnswerOutput,
  SyntheticBatchOutput,
  SyntheticGenerationResult,
  SyntheticQuestion,
  SyntheticStudent,
  SyntheticStudentOutput,
)
from tests.conftest import CapturingScheduler, ManualClock, join_participant, mutate


class _RecordingProvider:
  def __init__(self, *, failure: OpenRouterError | None = None) -> None:
    self.failure = failure
    self.calls: list[dict[str, Any]] = []

  async def generate(
    self,
    *,
    room_title: str,
    questions: Sequence[SyntheticQuestion],
    students: Sequence[SyntheticStudent],
  ) -> SyntheticGenerationResult:
    self.calls.append(
      {
        "room_title": room_title,
        "questions": tuple(questions),
        "students": tuple(students),
      }
    )
    if self.failure is not None:
      raise self.failure
    answers = {
      student.participant_id: {
        question.id: f"{student.persona.display_name}: answer {index + 1}" for index, question in enumerate(questions)
      }
      for student in students
    }
    return SyntheticGenerationResult(
      source="openrouter",
      answers=answers,
      models=("test/cheap-model",),
    )


class _InvalidMatrixProvider(_RecordingProvider):
  async def generate(self, **kwargs: Any) -> SyntheticGenerationResult:
    generated = await super().generate(**kwargs)
    answers = dict(generated.answers)
    answers.pop(next(iter(answers)))
    return SyntheticGenerationResult(
      source=generated.source,
      answers=answers,
      models=generated.models,
    )


class _StructuredClientStub:
  def __init__(self, output: SyntheticBatchOutput) -> None:
    self.output = output
    self.calls: list[dict[str, Any]] = []

  async def complete(self, **kwargs: Any) -> OpenRouterCompletion[SyntheticBatchOutput]:
    self.calls.append(kwargs)
    return OpenRouterCompletion(
      value=self.output,
      usage=OpenRouterUsage(
        request_id="offline-request",
        model="test/cheap-model",
        input_tokens=10,
        output_tokens=10,
        reasoning_tokens=0,
        total_tokens=20,
        elapsed_milliseconds=1,
      ),
    )


def _application(
  tmp_path: Path,
  *,
  enabled: bool,
  provider: _RecordingProvider | None = None,
) -> tuple[FastAPI, CapturingScheduler, ManualClock]:
  scheduler = CapturingScheduler()
  clock = ManualClock()
  app = create_app(
    app_settings=Settings(
      environment="test",
      session_secret="synthetic-classroom-offline-test-secret",
      synthetic_classroom_enabled=enabled,
    ),
    scheduler=scheduler,
    clock=clock,
    frontend_dist=tmp_path / "no-frontend-build",
    openrouter_synthetic_provider=provider,
  )
  return app, scheduler, clock


def _create_open_room(
  host: TestClient,
  *,
  reference_material: str = "Private reference notes",
  coverage_text: str = "Private coverage unit",
) -> tuple[str, str, str]:
  created = mutate(
    host,
    "POST",
    "/api/rooms",
    json={"title": "Synthetic classroom", "durationMinutes": 20},
  )
  assert created.status_code == 201, created.text
  room = created.json()
  question = mutate(
    host,
    "POST",
    f"/api/rooms/{room['roomId']}/questions",
    json={
      "prompt": "Explain the most important tradeoff.",
      "referenceMaterial": reference_material,
      "coverageUnits": [{"text": coverage_text}],
    },
  )
  assert question.status_code == 201, question.text
  opened = mutate(host, "POST", f"/api/rooms/{room['roomId']}/open")
  assert opened.status_code == 200, opened.text
  return room["roomId"], room["joinCode"], question.json()["id"]


def _synthetic_participants(app: FastAPI, room_id: str) -> tuple[UUID, ...]:
  room = app.state.room_service.get_room(UUID(room_id))
  return tuple(
    participant_id for participant_id, participant in room.participants.items() if is_synthetic_participant(participant)
  )


def test_development_routes_require_host_and_csrf(tmp_path: Path) -> None:
  app, _scheduler, _clock = _application(tmp_path, enabled=True)
  with TestClient(app) as host, TestClient(app) as stranger:
    room_id, join_code, _question_id = _create_open_room(host)
    participant = join_participant(app, join_code, "Human participant")
    with participant:
      assert host.get(f"/api/development/rooms/{room_id}/synthetic-classroom").status_code == 200
      for non_host in (stranger, participant):
        response = non_host.get(f"/api/development/rooms/{room_id}/synthetic-classroom")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

      missing_csrf = host.put(
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 5},
      )
      assert missing_csrf.status_code == 403
      assert missing_csrf.json()["error"]["code"] == "CSRF_INVALID"

      stranger_write = mutate(
        stranger,
        "PUT",
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 5},
      )
      assert stranger_write.status_code == 404
      assert stranger_write.json()["error"]["code"] == "NOT_FOUND"


def test_disabled_projection_is_visible_but_all_mutations_are_unavailable(
  tmp_path: Path,
) -> None:
  app, _scheduler, _clock = _application(tmp_path, enabled=False)
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host)
    projection = host.get(f"/api/development/rooms/{room_id}/synthetic-classroom")

    assert projection.status_code == 200
    assert projection.json() == {
      "enabled": False,
      "stage": "lobby",
      "syntheticParticipantCount": 0,
      "pendingSyntheticParticipantCount": 0,
      "targetSizes": [],
      "canConfigure": False,
      "canGenerate": False,
      "patternedAvailable": False,
      "openRouterAvailable": False,
    }
    configure = mutate(
      host,
      "PUT",
      f"/api/development/rooms/{room_id}/synthetic-cohort",
      json={"targetSize": 5},
    )
    assert configure.status_code == 404
    assert configure.json()["error"]["code"] == "NOT_FOUND"


def test_api_configure_is_idempotent_resizable_and_preserves_humans(
  tmp_path: Path,
) -> None:
  app, _scheduler, clock = _application(tmp_path, enabled=True)
  with TestClient(app) as host:
    room_id, join_code, _question_id = _create_open_room(host)
    human = join_participant(app, join_code, "Human participant")
    with human:
      first = mutate(
        host,
        "PUT",
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 20, "seed": 41},
      )
      assert first.status_code == 200, first.text
      assert first.json()["syntheticParticipantCount"] == 20
      ids = set(_synthetic_participants(app, room_id))
      first_updated_at = app.state.room_service.get_room(UUID(room_id)).updated_at

      clock.advance(minutes=2)
      repeated = mutate(
        host,
        "PUT",
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 20, "seed": 41},
      )
      assert repeated.status_code == 200, repeated.text
      assert set(_synthetic_participants(app, room_id)) == ids
      assert app.state.room_service.get_room(UUID(room_id)).updated_at == first_updated_at

      resized = mutate(
        host,
        "PUT",
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 10, "seed": 41},
      )
      assert resized.status_code == 200, resized.text
      room = app.state.room_service.get_room(UUID(room_id))
      assert resized.json()["syntheticParticipantCount"] == 10
      assert len(room.participants) == 11
      assert any(
        participant.display_name == "Human participant" and not is_synthetic_participant(participant)
        for participant in room.participants.values()
      )

      removed = mutate(
        host,
        "PUT",
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 0, "seed": 41},
      )
      assert removed.status_code == 200, removed.text
      assert removed.json()["syntheticParticipantCount"] == 0
      room = app.state.room_service.get_room(UUID(room_id))
      assert len(room.participants) == 1
      assert next(iter(room.participants.values())).display_name == "Human participant"


def test_patterned_api_submits_full_cohort_atomically_and_claims_analysis_once(
  tmp_path: Path,
) -> None:
  app, scheduler, _clock = _application(tmp_path, enabled=True)
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host)
    configured = mutate(
      host,
      "PUT",
      f"/api/development/rooms/{room_id}/synthetic-cohort",
      json={"targetSize": 20},
    )
    assert configured.status_code == 200, configured.text
    assert mutate(host, "POST", f"/api/rooms/{room_id}/start").status_code == 200

    generated = mutate(
      host,
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      json={"source": "patterned"},
    )

    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["source"] == "patterned"
    assert body["participantCount"] == 20
    assert 0 < body["responseCount"] <= 20
    assert body["models"] == []
    room = app.state.room_service.get_room(UUID(room_id))
    assert room.status == "analyzing"
    assert room.analysis_trigger == "all_submitted"
    assert all(room.participants[participant_id].submitted_at is not None for participant_id in room.cohort_ids)
    assert sum(delay == 0 for delay, _callback in scheduler.callbacks) == 1


def test_openrouter_provider_receives_only_visible_question_data(
  tmp_path: Path,
) -> None:
  provider = _RecordingProvider()
  app, _scheduler, _clock = _application(tmp_path, enabled=True, provider=provider)
  hidden_reference = "REFERENCE_SENTINEL_SHOULD_NOT_LEAVE_ROOM"
  hidden_coverage = "COVERAGE_SENTINEL_SHOULD_NOT_LEAVE_ROOM"
  with TestClient(app) as host:
    room_id, join_code, _question_id = _create_open_room(
      host,
      reference_material=hidden_reference,
      coverage_text=hidden_coverage,
    )
    human = join_participant(app, join_code, "Human participant")
    with human:
      mutate(
        host,
        "PUT",
        f"/api/development/rooms/{room_id}/synthetic-cohort",
        json={"targetSize": 5},
      )
      mutate(host, "POST", f"/api/rooms/{room_id}/start")
      generated = mutate(
        host,
        "POST",
        f"/api/development/rooms/{room_id}/synthetic-responses",
        json={"source": "openrouter"},
      )

    assert generated.status_code == 200, generated.text
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["room_title"] == "Synthetic classroom"
    assert len(call["questions"]) == 1
    assert set(call["questions"][0].__dataclass_fields__) == {"id", "prompt"}
    serialized = json.dumps(call, default=str)
    assert hidden_reference not in serialized
    assert hidden_coverage not in serialized
    assert "coverage_units" not in serialized
    assert "reference_material" not in serialized


@pytest.mark.parametrize(
  ("provider", "expected_status", "expected_code"),
  [
    (
      _RecordingProvider(failure=OpenRouterError("transient")),
      503,
      "SYNTHETIC_PROVIDER_UNAVAILABLE",
    ),
    (_InvalidMatrixProvider(), 502, "SYNTHETIC_PROVIDER_FAILED"),
  ],
)
def test_provider_failure_or_inexact_matrix_leaves_room_untouched(
  tmp_path: Path,
  provider: _RecordingProvider,
  expected_status: int,
  expected_code: str,
) -> None:
  app, _scheduler, _clock = _application(tmp_path, enabled=True, provider=provider)
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host)
    mutate(
      host,
      "PUT",
      f"/api/development/rooms/{room_id}/synthetic-cohort",
      json={"targetSize": 5},
    )
    mutate(host, "POST", f"/api/rooms/{room_id}/start")
    before = app.state.room_service.get_room(UUID(room_id))

    result = mutate(
      host,
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      json={"source": "openrouter"},
    )

    assert result.status_code == expected_status, result.text
    assert result.json()["error"]["code"] == expected_code
    assert app.state.room_service.get_room(UUID(room_id)) == before


def test_openrouter_output_rejects_duplicate_students_and_questions() -> None:
  question_ids = (uuid4(), uuid4())
  students = tuple(SyntheticStudent(participant_id=uuid4(), persona=persona) for persona in synthetic_personas(2))
  questions = tuple(
    SyntheticQuestion(id=question_id, prompt=f"Question {index + 1}") for index, question_id in enumerate(question_ids)
  )

  valid_answers = [
    SyntheticAnswerOutput.model_validate({"questionId": question_id, "text": "Answer"}) for question_id in question_ids
  ]
  duplicate_student = SyntheticBatchOutput(
    students=[
      SyntheticStudentOutput(
        participantId=students[0].participant_id,
        answers=valid_answers,
      ),
      SyntheticStudentOutput(
        participantId=students[0].participant_id,
        answers=valid_answers,
      ),
    ]
  )
  duplicate_question = SyntheticBatchOutput(
    students=[
      SyntheticStudentOutput(
        participantId=student.participant_id,
        answers=[valid_answers[0], valid_answers[0]],
      )
      for student in students
    ]
  )

  for output in (duplicate_student, duplicate_question):
    provider = OpenRouterSyntheticAnswerProvider(
      client=_StructuredClientStub(output),  # type: ignore[arg-type]
      models=("test/cheap-model",),
    )
    with pytest.raises(DomainError) as captured:
      asyncio.run(
        provider.generate(
          room_title="Offline validation",
          questions=questions,
          students=students,
        )
      )
    assert captured.value.code == "SYNTHETIC_OUTPUT_INVALID"


def test_concurrent_double_click_generates_once_and_second_call_is_idempotent(
  tmp_path: Path,
) -> None:
  provider = _RecordingProvider()
  app, _scheduler, _clock = _application(tmp_path, enabled=True, provider=provider)
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host)
    mutate(
      host,
      "PUT",
      f"/api/development/rooms/{room_id}/synthetic-cohort",
      json={"targetSize": 5},
    )
    mutate(host, "POST", f"/api/rooms/{room_id}/start")

    async def run_twice() -> tuple[Any, Any]:
      first, second = await asyncio.gather(
        app.state.synthetic_classroom.generate_and_submit(UUID(room_id), source="openrouter"),
        app.state.synthetic_classroom.generate_and_submit(UUID(room_id), source="openrouter"),
      )
      return first, second

    first, second = asyncio.run(run_twice())

    assert len(provider.calls) == 1
    assert sorted((first.participant_count, second.participant_count)) == [0, 5]
    assert app.state.room_service.get_room(UUID(room_id)).status == "analyzing"
