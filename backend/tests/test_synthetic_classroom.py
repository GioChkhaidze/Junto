from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from junto.config import Settings
from junto.domain.errors import DomainError
from junto.domain.limits import MAX_ANSWER_CHARACTERS
from junto.engine.openrouter import (
  OpenRouterCategory,
  OpenRouterCompletion,
  OpenRouterError,
  OpenRouterReason,
  OpenRouterUsage,
)
from junto.main import create_app
from junto.services.personas import is_synthetic_participant, synthetic_personas
from junto.services.simulation import (
  OpenRouterSyntheticAnswerProvider,
  SyntheticAnswerReady,
  SyntheticGenerationResult,
  SyntheticQuestion,
  SyntheticStudent,
  SyntheticStudentOutput,
  _maximum_output_tokens,
  _normalize_synthetic_answer,
  _synthetic_student_output_type,
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
    simulation_context: str | None = None,
    questions: Sequence[SyntheticQuestion],
    students: Sequence[SyntheticStudent],
    on_student_ready: SyntheticAnswerReady | None = None,
  ) -> SyntheticGenerationResult:
    self.calls.append(
      {
        "room_title": room_title,
        "simulation_context": simulation_context,
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
    if on_student_ready is not None:
      for student in students:
        on_student_ready(student.participant_id, answers[student.participant_id])
    return SyntheticGenerationResult(
      source="openrouter",
      answers=answers,
      models=("test/model",),
    )


class _InvalidMatrixProvider(_RecordingProvider):
  async def generate(self, **kwargs: Any) -> SyntheticGenerationResult:
    kwargs.pop("on_student_ready", None)
    generated = await super().generate(**kwargs)
    answers = dict(generated.answers)
    answers.pop(next(iter(answers)))
    return SyntheticGenerationResult(
      source=generated.source,
      answers=answers,
      models=generated.models,
    )


class _BlockingProvider(_RecordingProvider):
  async def generate(self, **kwargs: Any) -> SyntheticGenerationResult:
    kwargs.pop("on_student_ready", None)
    await super().generate(**kwargs)
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


class _PartialThenSuccessfulProvider(_RecordingProvider):
  def __init__(self) -> None:
    super().__init__()
    self.attempt = 0

  async def generate(self, **kwargs: Any) -> SyntheticGenerationResult:
    on_student_ready = kwargs.pop("on_student_ready", None)
    generated = await super().generate(**kwargs)
    self.attempt += 1
    participants = tuple(generated.answers)
    ready = participants[:2] if self.attempt == 1 else participants
    if on_student_ready is not None:
      for participant_id in ready:
        on_student_ready(participant_id, generated.answers[participant_id])
    if self.attempt == 1:
      raise OpenRouterError("transient", "transport")
    return generated


class _StructuredClientStub:
  def __init__(self, output: SyntheticStudentOutput, *, delay_seconds: float = 0) -> None:
    self.output = output
    self.delay_seconds = delay_seconds
    self.calls: list[dict[str, Any]] = []
    self.active_calls = 0
    self.maximum_active_calls = 0

  async def complete(self, **kwargs: Any) -> OpenRouterCompletion[SyntheticStudentOutput]:
    self.calls.append(kwargs)
    self.active_calls += 1
    self.maximum_active_calls = max(self.maximum_active_calls, self.active_calls)
    try:
      if self.delay_seconds:
        await asyncio.sleep(self.delay_seconds)
      return OpenRouterCompletion(
        value=self.output,
        usage=OpenRouterUsage(
          request_id="offline-request",
          model="test/model",
          input_tokens=10,
          output_tokens=10,
          reasoning_tokens=0,
          total_tokens=20,
          elapsed_milliseconds=1,
        ),
      )
    finally:
      self.active_calls -= 1


class _FailOnceStructuredClientStub(_StructuredClientStub):
  def __init__(self, output: SyntheticStudentOutput, failure: OpenRouterError) -> None:
    super().__init__(output)
    self.failure = failure

  async def complete(self, **kwargs: Any) -> OpenRouterCompletion[SyntheticStudentOutput]:
    self.calls.append(kwargs)
    if len(self.calls) == 1:
      raise self.failure
    return OpenRouterCompletion(
      value=self.output,
      usage=OpenRouterUsage(
        request_id="retry-request",
        model=str(kwargs["model"]),
        input_tokens=10,
        output_tokens=10,
        reasoning_tokens=0,
        total_tokens=20,
        elapsed_milliseconds=1,
      ),
    )


class _AlwaysFailingStructuredClientStub(_StructuredClientStub):
  def __init__(self, output: SyntheticStudentOutput, failure: OpenRouterError) -> None:
    super().__init__(output)
    self.failure = failure

  async def complete(self, **kwargs: Any) -> OpenRouterCompletion[SyntheticStudentOutput]:
    self.calls.append(kwargs)
    raise self.failure


def _application(
  tmp_path: Path,
  *,
  enabled: bool,
  provider: _RecordingProvider | None = None,
  generation_timeout_seconds: float = 120.0,
  engine_mode: str = "placeholder",
) -> tuple[FastAPI, CapturingScheduler, ManualClock]:
  scheduler = CapturingScheduler()
  clock = ManualClock()
  app = create_app(
    app_settings=Settings(
      environment="test",
      session_secret="synthetic-classroom-offline-test-secret",
      engine_mode=engine_mode,
      synthetic_classroom_enabled=enabled,
      synthetic_generation_timeout_seconds=generation_timeout_seconds,
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
  room_attachment: str | None = None,
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
  if room_attachment is not None:
    uploaded = mutate(
      host,
      "POST",
      f"/api/rooms/{room['roomId']}/materials",
      files={"file": ("student-reading.txt", room_attachment.encode(), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
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
      "syntheticParticipantIds": [],
      "pendingSyntheticParticipantIds": [],
      "generation": None,
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


def test_response_source_is_required_and_patterned_is_placeholder_only(tmp_path: Path) -> None:
  provider = _RecordingProvider()
  app, _scheduler, _clock = _application(
    tmp_path,
    enabled=True,
    provider=provider,
    engine_mode="recorded",
  )
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host)
    configured = mutate(
      host,
      "PUT",
      f"/api/development/rooms/{room_id}/synthetic-cohort",
      json={"targetSize": 5},
    )
    assert configured.json()["patternedAvailable"] is False
    assert configured.json()["openRouterAvailable"] is True
    mutate(host, "POST", f"/api/rooms/{room_id}/start")

    missing = mutate(
      host,
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      json={},
    )
    patterned = mutate(
      host,
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      json={"source": "patterned"},
    )

    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "VALIDATION_FAILED"
    assert patterned.status_code == 404
    assert app.state.room_service.get_room(UUID(room_id)).responses == {}


def test_openrouter_provider_includes_only_bounded_disclosed_room_source(
  tmp_path: Path,
) -> None:
  provider = _RecordingProvider()
  app, _scheduler, _clock = _application(tmp_path, enabled=True, provider=provider)
  hidden_reference = "REFERENCE_SENTINEL_SHOULD_NOT_LEAVE_ROOM"
  hidden_coverage = "COVERAGE_SENTINEL_SHOULD_NOT_LEAVE_ROOM"
  source_context = "ROOM_SOURCE_SENTINEL " + "The host supplied source facts. " * 2_500
  with TestClient(app) as host:
    room_id, join_code, _question_id = _create_open_room(
      host,
      reference_material=hidden_reference,
      coverage_text=hidden_coverage,
      room_attachment=source_context,
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
    assert call["simulation_context"].startswith("ROOM_SOURCE_SENTINEL")
    assert len(call["simulation_context"]) == 60_000
    serialized = json.dumps(call, default=str)
    assert hidden_reference not in serialized
    assert hidden_coverage not in serialized
    assert "ROOM_SOURCE_SENTINEL" in serialized
    assert "student-reading.txt" not in serialized
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
def test_provider_failure_or_inexact_answer_set_leaves_room_untouched(
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


def test_partial_generation_keeps_completed_students_and_retries_only_pending_students(tmp_path: Path) -> None:
  provider = _PartialThenSuccessfulProvider()
  app, scheduler, _clock = _application(tmp_path, enabled=True, provider=provider)
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host)
    mutate(host, "PUT", f"/api/development/rooms/{room_id}/synthetic-cohort", json={"targetSize": 5})
    mutate(host, "POST", f"/api/rooms/{room_id}/start")

    first = mutate(
      host,
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      json={"source": "openrouter"},
    )

    assert first.status_code == 503
    assert "2 simulated participants submitted" in first.json()["error"]["message"]
    projection = host.get(f"/api/development/rooms/{room_id}/synthetic-classroom").json()
    assert projection["generation"]["status"] == "failed"
    assert projection["generation"]["completedParticipantCount"] == 2
    assert projection["generation"]["failedParticipantCount"] == 3
    assert projection["pendingSyntheticParticipantCount"] == 3
    assert len(projection["pendingSyntheticParticipantIds"]) == 3
    assert projection["canGenerate"] is True
    room = app.state.room_service.get_room(UUID(room_id))
    assert sum(participant.submitted_at is not None for participant in room.participants.values()) == 2

    second = mutate(
      host,
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      json={"source": "openrouter"},
    )

    assert second.status_code == 200, second.text
    assert second.json()["participantCount"] == 3
    assert second.json()["responseCount"] == 3
    room = app.state.room_service.get_room(UUID(room_id))
    assert room.status == "analyzing"
    assert all(room.participants[participant_id].submitted_at is not None for participant_id in room.cohort_ids)
    assert scheduler.run_ready() == 2
    assert app.state.room_service.get_room(UUID(room_id)).status == "published"


def test_openrouter_failure_logs_only_safe_diagnostics_and_keeps_public_error_generic(
  tmp_path: Path,
  caplog: pytest.LogCaptureFixture,
) -> None:
  provider = _RecordingProvider(failure=OpenRouterError("invalid", "schema_answer_count"))
  app, _scheduler, _clock = _application(tmp_path, enabled=True, provider=provider)
  with TestClient(app) as host:
    room_id, _join_code, _question_id = _create_open_room(host, room_attachment="SOURCE_TEXT_SENTINEL")
    mutate(host, "PUT", f"/api/development/rooms/{room_id}/synthetic-cohort", json={"targetSize": 5})
    mutate(host, "POST", f"/api/rooms/{room_id}/start")

    with caplog.at_level(logging.WARNING, logger="junto.synthetic"):
      result = mutate(
        host,
        "POST",
        f"/api/development/rooms/{room_id}/synthetic-responses",
        json={"source": "openrouter"},
      )

  assert result.status_code == 502
  assert result.json() == {
    "error": {
      "code": "SYNTHETIC_PROVIDER_FAILED",
      "message": "OpenRouter could not finish any simulated responses. Retry the simulated participants.",
      "details": {},
    }
  }
  assert "schema" not in json.dumps(result.json()).lower()
  records = [record for record in caplog.records if record.name == "junto.synthetic"]
  assert [record.getMessage() for record in records] == [
    "OpenRouter synthetic generation failed category=invalid reason=schema_answer_count"
  ]
  assert "SOURCE_TEXT_SENTINEL" not in caplog.text
  assert room_id not in caplog.text


def test_whole_cohort_generation_timeout_leaves_room_untouched(tmp_path: Path) -> None:
  provider = _BlockingProvider()
  app, _scheduler, _clock = _application(
    tmp_path,
    enabled=True,
    provider=provider,
    generation_timeout_seconds=0.01,
  )
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

    assert result.status_code == 503
    assert result.json()["error"]["code"] == "SYNTHETIC_PROVIDER_UNAVAILABLE"
    assert app.state.room_service.get_room(UUID(room_id)) == before


def test_openrouter_output_rejects_wrong_answer_count() -> None:
  question_ids = (uuid4(), uuid4())
  students = tuple(SyntheticStudent(participant_id=uuid4(), persona=persona) for persona in synthetic_personas(2))
  questions = tuple(
    SyntheticQuestion(id=question_id, prompt=f"Question {index + 1}") for index, question_id in enumerate(question_ids)
  )

  for output in (SyntheticStudentOutput(answers=["Answer one"]), SyntheticStudentOutput(answers=["1", "2", "3"])):
    provider = OpenRouterSyntheticAnswerProvider(
      client=_StructuredClientStub(output),  # type: ignore[arg-type]
      model="test/model",
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


def test_openrouter_student_schema_requires_exact_answer_count() -> None:
  output_type = _synthetic_student_output_type(2)
  schema = output_type.model_json_schema()
  answers = schema["properties"]["answers"]

  assert output_type.__bases__ == (SyntheticStudentOutput,)
  assert schema["additionalProperties"] is False
  assert answers["minItems"] == answers["maxItems"] == 2
  assert answers["items"]["maxLength"] == 6_000


def test_openrouter_student_wire_schema_allows_bounded_domain_overshoot() -> None:
  output_type = _synthetic_student_output_type(1)

  accepted = output_type.model_validate({"answers": ["x" * 6_000]})

  assert len(accepted.answers[0]) == 6_000
  with pytest.raises(ValidationError):
    output_type.model_validate({"answers": ["x" * 6_001]})


@pytest.mark.parametrize("answers", [["a"], ["a", "b", "c"]])
def test_openrouter_student_type_rejects_omitted_or_added_answers(answers: list[str]) -> None:
  output_type = _synthetic_student_output_type(2)

  with pytest.raises(ValidationError):
    output_type.model_validate({"answers": answers})


def test_openrouter_student_type_accepts_empty_answers_and_rejects_extra_fields() -> None:
  output_type = _synthetic_student_output_type(2)

  output = output_type.model_validate({"answers": ["", "answer"]})

  assert output.model_dump() == {"answers": ["", "answer"]}
  with pytest.raises(ValidationError):
    output_type.model_validate({"answers": ["", ""], "participantId": "private-id"})


@pytest.mark.parametrize("question_count", [0, -1, 9, True])
def test_openrouter_student_type_rejects_dimensions_outside_contract(question_count: int) -> None:
  with pytest.raises(ValueError):
    _synthetic_student_output_type(question_count)


def test_openrouter_uses_one_private_request_per_student_and_maps_answers_server_side() -> None:
  students = tuple(SyntheticStudent(participant_id=uuid4(), persona=persona) for persona in synthetic_personas(2))
  question = SyntheticQuestion(id=uuid4(), prompt="Explain the tradeoff.")
  simulation_context = "The supplied source says the intervention reduced median waiting time by 18 percent."
  output = SyntheticStudentOutput(answers=["A bounded answer"])
  client = _StructuredClientStub(output)
  provider = OpenRouterSyntheticAnswerProvider(
    client=client,  # type: ignore[arg-type]
    model="test/pinned-model",
  )

  result = asyncio.run(
    provider.generate(
      room_title="Fallback test",
      simulation_context=simulation_context,
      questions=(question,),
      students=students,
    )
  )

  assert [call["model"] for call in client.calls] == ["test/pinned-model", "test/pinned-model"]
  assert all(call["temperature"] == 0.65 for call in client.calls)
  assert all(call["reasoning_max_tokens"] == 1_024 for call in client.calls)
  assert all(call["exclude_reasoning"] is True for call in client.calls)
  for call, student in zip(client.calls, students, strict=True):
    user_content = call["messages"][1]["content"]
    wire_payload = json.loads(user_content.splitlines()[1])
    assert set(wire_payload) == {"activityTitle", "questions", "simulationContext", "studentTraits"}
    assert wire_payload["activityTitle"] == "Fallback test"
    assert wire_payload["simulationContext"] == simulation_context
    assert wire_payload["questions"] == ["Explain the tradeoff."]
    assert set(wire_payload["studentTraits"]) == {
      "knowledge_level",
      "confidence",
      "answer_style",
      "error_tendency",
      "participation",
    }
    serialized_messages = json.dumps(call["messages"])
    assert student.persona.display_name not in serialized_messages
    assert student.persona.id not in serialized_messages
    assert str(student.participant_id) not in serialized_messages
    assert str(question.id) not in serialized_messages
    assert "display_name" not in serialized_messages
    assert '"students"' not in serialized_messages
    assert simulation_context in serialized_messages
    assert "no longer than 1,200 characters" in serialized_messages
    for trait in (
      student.persona.knowledge_level,
      student.persona.confidence,
      student.persona.answer_style,
      student.persona.error_tendency,
      student.persona.participation,
    ):
      assert trait in serialized_messages
  assert result.answers == {student.participant_id: {question.id: "A bounded answer"} for student in students}
  assert result.models == ("test/model",)


@pytest.mark.parametrize(
  ("answer", "expected"),
  [("", ""), ("  A normal answer.  ", "A normal answer."), ("x" * MAX_ANSWER_CHARACTERS, "x" * 1_500)],
)
def test_synthetic_answer_normalization_preserves_empty_normal_and_exact_limit(
  answer: str,
  expected: str,
) -> None:
  assert _normalize_synthetic_answer(answer) == expected


def test_openrouter_normalizes_wire_overshoot_at_a_word_boundary() -> None:
  student = SyntheticStudent(participant_id=uuid4(), persona=synthetic_personas(1)[0])
  question = SyntheticQuestion(id=uuid4(), prompt="Explain the tradeoff.")
  output = SyntheticStudentOutput(answers=[("word " * 400).strip()])
  client = _StructuredClientStub(output)
  provider = OpenRouterSyntheticAnswerProvider(client=client, model="test/model")  # type: ignore[arg-type]

  result = asyncio.run(
    provider.generate(
      room_title="Normalization test",
      questions=(question,),
      students=(student,),
    )
  )
  answer = result.answers[student.participant_id][question.id]

  assert len(answer) <= MAX_ANSWER_CHARACTERS
  assert answer.endswith("word…")


def test_synthetic_answer_normalization_counts_unicode_characters_not_bytes() -> None:
  answer = _normalize_synthetic_answer("🙂" * (MAX_ANSWER_CHARACTERS + 100))

  assert len(answer) == MAX_ANSWER_CHARACTERS
  assert answer == "🙂" * (MAX_ANSWER_CHARACTERS - 1) + "…"
  assert len(answer.encode("utf-8")) > MAX_ANSWER_CHARACTERS


@pytest.mark.parametrize(("question_count", "expected"), [(1, 1_900), (4, 3_100), (8, 4_700)])
def test_synthetic_output_allowance_is_bounded(question_count: int, expected: int) -> None:
  assert _maximum_output_tokens(question_count) == expected


@pytest.mark.parametrize("question_count", [0, -1, 9, True])
def test_synthetic_output_allowance_rejects_invalid_counts(question_count: int) -> None:
  with pytest.raises(ValueError):
    _maximum_output_tokens(question_count)


def test_openrouter_limits_default_parallel_requests_to_five() -> None:
  students = tuple(SyntheticStudent(participant_id=uuid4(), persona=persona) for persona in synthetic_personas(20))
  question = SyntheticQuestion(id=uuid4(), prompt="Explain the tradeoff.")
  client = _StructuredClientStub(SyntheticStudentOutput(answers=["answer"]), delay_seconds=0.01)
  provider = OpenRouterSyntheticAnswerProvider(client=client, model="test/only-model")  # type: ignore[arg-type]

  result = asyncio.run(
    provider.generate(
      room_title="Concurrency test",
      questions=(question,),
      students=students,
    )
  )

  assert len(client.calls) == 20
  assert client.maximum_active_calls == 5
  assert len(result.answers) == 20


@pytest.mark.parametrize("reason", ["transport", "finish_error"])
def test_openrouter_retries_once_for_an_unchanged_call_that_can_recover(reason: OpenRouterReason) -> None:
  student = SyntheticStudent(participant_id=uuid4(), persona=synthetic_personas(1)[0])
  question = SyntheticQuestion(id=uuid4(), prompt="Explain the tradeoff.")
  output = SyntheticStudentOutput(answers=["A bounded answer"])
  client = _FailOnceStructuredClientStub(output, OpenRouterError("transient", reason))
  provider = OpenRouterSyntheticAnswerProvider(
    client=client,  # type: ignore[arg-type]
    model="test/only-model",
  )

  result = asyncio.run(
    provider.generate(
      room_title="Retry test",
      questions=(question,),
      students=(student,),
    )
  )

  assert [call["model"] for call in client.calls] == ["test/only-model", "test/only-model"]
  assert result.models == ("test/only-model",)


@pytest.mark.parametrize(
  ("category", "reason"),
  [
    ("transient", "http_status"),
    ("transient", "unspecified"),
    ("permanent", "finish_length"),
    ("permanent", "finish_other"),
    ("refusal", "finish_other"),
    ("invalid", "schema"),
    ("invalid", "schema_answer_too_long"),
  ],
)
def test_openrouter_does_not_retry_failures_that_need_a_changed_call(
  category: OpenRouterCategory,
  reason: OpenRouterReason,
) -> None:
  student = SyntheticStudent(participant_id=uuid4(), persona=synthetic_personas(1)[0])
  question = SyntheticQuestion(id=uuid4(), prompt="Explain the tradeoff.")
  failure = OpenRouterError(category, reason)
  client = _AlwaysFailingStructuredClientStub(SyntheticStudentOutput(answers=["unused"]), failure)
  provider = OpenRouterSyntheticAnswerProvider(
    client=client,  # type: ignore[arg-type]
    model="test/only-model",
  )

  with pytest.raises(OpenRouterError) as captured:
    asyncio.run(
      provider.generate(
        room_title="No retry test",
        questions=(question,),
        students=(student,),
      )
    )

  assert captured.value.category == category
  assert captured.value.reason == reason
  assert len(client.calls) == 1


def test_openrouter_retry_is_capped_at_two_unchanged_calls() -> None:
  student = SyntheticStudent(participant_id=uuid4(), persona=synthetic_personas(1)[0])
  question = SyntheticQuestion(id=uuid4(), prompt="Explain the tradeoff.")
  failure = OpenRouterError("transient", "transport")
  client = _AlwaysFailingStructuredClientStub(SyntheticStudentOutput(answers=["unused"]), failure)
  provider = OpenRouterSyntheticAnswerProvider(
    client=client,  # type: ignore[arg-type]
    model="test/only-model",
  )

  with pytest.raises(OpenRouterError) as captured:
    asyncio.run(
      provider.generate(
        room_title="Retry cap test",
        questions=(question,),
        students=(student,),
      )
    )

  assert captured.value is failure
  assert len(client.calls) == 2


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
