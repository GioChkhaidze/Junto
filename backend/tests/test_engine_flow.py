from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from junto.config import Settings
from junto.domain.entities import Room
from junto.engine.compiler import SemanticCompiler
from junto.engine.models import GroupingArtifact, SemanticArtifact
from junto.engine.optimizer import CoverageFirstOptimizer, OptimizerConfig
from junto.engine.provider import RecordedSemanticProvider
from junto.main import create_app
from junto.services.analysis import CoverageAnalysisPipeline
from tests.conftest import MutableClock, RecordingScheduler, mutate

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "semantic" / "programming_dynamic_programming.json"


@dataclass(slots=True)
class FailFirstOptimizationPipeline:
  """Exercise the real compiler/optimizer while failing between their stages once."""

  delegate: CoverageAnalysisPipeline
  semantic: SemanticArtifact | None = None
  optimize_calls: int = 0

  def compile(self, room: Room) -> SemanticArtifact:
    if self.semantic is None:
      self.semantic = self.delegate.compile(room)
    return self.semantic

  def optimize(
    self,
    room: Room,
    semantic_artifact: SemanticArtifact,
    *,
    trigger: str,
  ) -> GroupingArtifact:
    self.optimize_calls += 1
    if self.optimize_calls == 1:
      raise RuntimeError("private optimizer diagnostic that must not escape")
    return self.delegate.optimize(room, semantic_artifact, trigger=trigger)


def _fixture() -> dict[str, Any]:
  value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
  assert isinstance(value, dict)
  return value


def _pipeline() -> CoverageAnalysisPipeline:
  provider = RecordedSemanticProvider.from_fixture_files([FIXTURE_PATH])
  return CoverageAnalysisPipeline(
    compiler=SemanticCompiler(provider, transport_retry_delay_seconds=0),
    optimizer=CoverageFirstOptimizer(OptimizerConfig(timeout_seconds=5.0, random_seed=41)),
    solver_timeout_seconds=5.0,
  )


def _app(
  tmp_path: Path,
  *,
  scheduler: RecordingScheduler,
  pipeline: CoverageAnalysisPipeline | FailFirstOptimizationPipeline | None = None,
) -> FastAPI:
  return create_app(
    app_settings=Settings(
      environment="test",
      session_secret="engine-flow-session-secret-with-enough-entropy",
      engine_mode="recorded",
      solver_timeout_seconds=5.0,
    ),
    scheduler=scheduler,
    clock=MutableClock(),
    frontend_dist=tmp_path / "no-frontend-build",
    analysis_pipeline=pipeline,
  )


def _create_fixture_room(
  host: TestClient,
  fixture: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
  created = mutate(
    host,
    "POST",
    "/api/rooms",
    json={
      "title": "Dynamic programming route workshop",
      "policy": "teach",
      "durationMinutes": 20,
      "groupSize": {"minimum": 3, "preferred": 3, "maximum": 3},
    },
  )
  assert created.status_code == 201, created.text
  room = created.json()
  question = mutate(
    host,
    "POST",
    f"/api/rooms/{room['roomId']}/questions",
    json={
      "prompt": fixture["questionPrompt"],
      "referenceMaterial": fixture["referenceMaterial"],
      # IDs are deliberately omitted: the recorded provider must match reviewed
      # content and remap its fixture IDs to room-local generated IDs.
      "coverageUnits": [{"text": unit["text"]} for unit in fixture["coverageUnits"]],
    },
  )
  assert question.status_code == 201, question.text
  opened = mutate(host, "POST", f"/api/rooms/{room['roomId']}/open")
  assert opened.status_code == 200, opened.text
  assert opened.json()["analysisMode"] == "coverage_aware"
  return room["roomId"], room["joinCode"], question.json()


def _join_fixture_participants(
  app: FastAPI,
  join_code: str,
  fixture: dict[str, Any],
) -> list[tuple[TestClient, str, dict[str, Any], str]]:
  joined: list[tuple[TestClient, str, dict[str, Any], str]] = []
  for index, participant in enumerate(fixture["participants"], start=1):
    client = TestClient(app)
    response = mutate(
      client,
      "POST",
      f"/api/join/{join_code}",
      json={"displayName": f"Participant {index}"},
    )
    assert response.status_code == 201, response.text
    joined.append((client, response.json()["participantId"], participant, f"Participant {index}"))
  return joined


def _answer_and_submit_everyone(
  host: TestClient,
  room_id: str,
  question_id: str,
  participants: list[tuple[TestClient, str, dict[str, Any], str]],
) -> None:
  started = mutate(host, "POST", f"/api/rooms/{room_id}/start")
  assert started.status_code == 200, started.text
  assert started.json()["status"] == "answering"

  for index, (client, _participant_id, fixture_participant, _name) in enumerate(
    participants,
    start=1,
  ):
    answer = fixture_participant["answer"]
    if answer:
      saved = mutate(
        client,
        "PUT",
        f"/api/rooms/{room_id}/responses/{question_id}",
        json={"text": answer},
      )
      assert saved.status_code == 200, saved.text
    submitted = mutate(client, "POST", f"/api/rooms/{room_id}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["analysisStarted"] is (index == len(participants))


def _close_participants(
  participants: list[tuple[TestClient, str, dict[str, Any], str]],
) -> None:
  for client, _participant_id, _fixture_participant, _name in participants:
    client.close()


def test_recorded_coverage_pipeline_publishes_auditable_private_groups(
  tmp_path: Path,
) -> None:
  fixture = _fixture()
  scheduler = RecordingScheduler()
  app = _app(tmp_path, scheduler=scheduler)

  with TestClient(app) as host:
    room_id, join_code, question = _create_fixture_room(host, fixture)
    participants = _join_fixture_participants(app, join_code, fixture)
    try:
      _answer_and_submit_everyone(host, room_id, question["id"], participants)
      analyzing = host.get(f"/api/rooms/{room_id}/status")
      assert analyzing.status_code == 200
      assert analyzing.json()["status"] == "analyzing"
      assert analyzing.json()["analysisPhase"] == "analyzing_responses"

      # Coverage compilation and optimization are one deterministic background job.
      assert scheduler.run_ready() == 1

      published = host.get(f"/api/rooms/{room_id}/status")
      assert published.status_code == 200
      assert published.json()["status"] == "published"
      assert published.json()["analysisPhase"] == "complete"
      assert published.json()["analysisMode"] == "coverage_aware"

      host_result = host.get(f"/api/rooms/{room_id}/groups")
      assert host_result.status_code == 200, host_result.text
      result = host_result.json()
      assert result["generationMode"] == "coverage_aware"
      assert result["policy"] == "teach"
      assert result["trigger"] == "all_submitted"
      assert result["solver"]["status"] == "optimal"
      assert result["solver"]["completeCoverageStatus"] == "feasible"
      assert result["solver"]["timedOut"] is False
      assert result["coverageReport"] == {
        "fullyCoveredGroupQuestions": 2,
        "totalGroupQuestions": 2,
      }
      assert [len(group["members"]) for group in result["groups"]] == [3, 3]

      runtime_ids_by_name = {
        name: participant_id for _client, participant_id, _fixture_participant, name in participants
      }
      flattened_members = [member for group in result["groups"] for member in group["members"]]
      assert {member["participantId"] for member in flattened_members} == set(runtime_ids_by_name.values())
      assert len(flattened_members) == len(participants)

      runtime_unit_by_fixture_id = {
        fixture_unit["id"]: runtime_unit["id"]
        for fixture_unit, runtime_unit in zip(
          fixture["coverageUnits"],
          question["coverageUnits"],
          strict=True,
        )
      }
      expected_coverage_by_name = {
        f"Participant {index}": {
          runtime_unit_by_fixture_id[unit_id]
          for unit_id in next(
            (
              assignment["coveredUnitIds"]
              for assignment in fixture["expectedCoverage"]["assignments"]
              if assignment["participantId"] == participant["participantId"]
            ),
            [],
          )
        }
        for index, participant in enumerate(fixture["participants"], start=1)
      }
      host_audit = [
        audit
        for group in result["groups"]
        for group_question in group["questions"]
        for audit in group_question["responseAudit"]
      ]
      assert len(host_audit) == 6
      for audit in host_audit:
        name = audit["participant"]["displayName"]
        fixture_participant = fixture["participants"][int(name.split()[-1]) - 1]
        assert audit["answer"] == (fixture_participant["answer"] or None)
        assert set(audit["coveredUnitIds"]) == expected_coverage_by_name[name]
      assert {audit["family"]["label"] for audit in host_audit if audit["family"] is not None} == {
        "Top-down memoization",
        "Bottom-up tabulation",
        "Forward route propagation",
      }

      all_host_answers = {audit["answer"] for audit in host_audit if audit["answer"] is not None}
      for client, participant_id, _fixture_participant, _name in participants:
        private = client.get(f"/api/rooms/{room_id}/my-group")
        assert private.status_code == 200, private.text
        private_result = private.json()
        assert set(private_result) == {
          "generationMode",
          "policy",
          "generatedAt",
          "completeCoverageStatus",
          "group",
        }
        assert participant_id in {member["participantId"] for member in private_result["group"]["members"]}
        assert len(private_result["group"]["members"]) == 3
        serialized_private = json.dumps(private_result, sort_keys=True)
        assert "responseAudit" not in serialized_private
        assert "answer" not in serialized_private.casefold()
        assert all(answer not in serialized_private for answer in all_host_answers)

        # A participant grant cannot be escalated into host-wide rosters or groups.
        assert client.get(f"/api/rooms/{room_id}").status_code == 404
        assert client.get(f"/api/rooms/{room_id}/groups").status_code == 404
    finally:
      _close_participants(participants)


def test_failed_optimizer_publishes_no_partial_artifact_and_retry_is_atomic(
  tmp_path: Path,
) -> None:
  fixture = _fixture()
  scheduler = RecordingScheduler()
  pipeline = FailFirstOptimizationPipeline(_pipeline())
  app = _app(tmp_path, scheduler=scheduler, pipeline=pipeline)

  with TestClient(app) as host:
    room_id, join_code, question = _create_fixture_room(host, fixture)
    participants = _join_fixture_participants(app, join_code, fixture)
    try:
      _answer_and_submit_everyone(host, room_id, question["id"], participants)
      assert scheduler.run_ready() == 1

      failed = host.get(f"/api/rooms/{room_id}")
      assert failed.status_code == 200
      assert failed.json()["status"] == "failed"
      assert failed.json()["analysisPhase"] == "failed"
      assert failed.json()["allowedActions"] == ["viewFailure", "retryAnalysis"]
      assert failed.json()["lastError"] == ("Groups could not be formed from this response set.")
      assert "private optimizer diagnostic" not in failed.text

      stored_after_failure = app.state.room_repository.get(UUID(room_id))
      assert stored_after_failure is not None
      assert stored_after_failure.analysis_result is None
      assert stored_after_failure.grouping_result is None
      unavailable = host.get(f"/api/rooms/{room_id}/groups")
      assert unavailable.status_code == 409
      assert unavailable.json()["error"]["code"] == "GROUPS_NOT_PUBLISHED"

      retry = mutate(host, "POST", f"/api/rooms/{room_id}/analysis/retry")
      assert retry.status_code == 202, retry.text
      assert retry.json() == {
        "status": "analyzing",
        "analysisPhase": "analyzing_responses",
      }
      assert scheduler.run_ready() == 1

      published = host.get(f"/api/rooms/{room_id}/groups")
      assert published.status_code == 200, published.text
      assert published.json()["generationMode"] == "coverage_aware"
      assert pipeline.optimize_calls == 2

      stored_after_retry = app.state.room_repository.get(UUID(room_id))
      assert stored_after_retry is not None
      assert stored_after_retry.status == "published"
      assert stored_after_retry.analysis_attempt_count == 2
      assert stored_after_retry.analysis_result is not None
      assert stored_after_retry.grouping_result is not None
    finally:
      _close_participants(participants)


def test_host_early_finish_claims_once_and_immediately_freezes_answers(
  tmp_path: Path,
) -> None:
  fixture = _fixture()
  scheduler = RecordingScheduler()
  app = _app(tmp_path, scheduler=scheduler)

  with TestClient(app) as host:
    room_id, join_code, question = _create_fixture_room(host, fixture)
    participants = _join_fixture_participants(app, join_code, fixture)
    try:
      started = mutate(host, "POST", f"/api/rooms/{room_id}/start")
      assert started.status_code == 200, started.text

      # Save every non-empty reviewed answer, but finalize only four people.
      # The remaining saved answer must still be part of the frozen room snapshot.
      for index, (client, _participant_id, fixture_participant, _name) in enumerate(
        participants[:5],
        start=1,
      ):
        saved = mutate(
          client,
          "PUT",
          f"/api/rooms/{room_id}/responses/{question['id']}",
          json={"text": fixture_participant["answer"]},
        )
        assert saved.status_code == 200, saved.text
        if index <= 4:
          submitted = mutate(client, "POST", f"/api/rooms/{room_id}/submit")
          assert submitted.status_code == 200, submitted.text
          assert submitted.json()["analysisStarted"] is False

      claimed = mutate(host, "POST", f"/api/rooms/{room_id}/analysis")
      assert claimed.status_code == 202, claimed.text
      assert claimed.json() == {
        "status": "analyzing",
        "analysisPhase": "analyzing_responses",
      }
      assert sum(delay <= 0 for delay, _callback in scheduler.callbacks) == 1

      duplicate = mutate(host, "POST", f"/api/rooms/{room_id}/analysis")
      assert duplicate.status_code == 409
      assert duplicate.json()["error"]["code"] == "ROOM_NOT_ANSWERING"
      assert sum(delay <= 0 for delay, _callback in scheduler.callbacks) == 1

      unsubmitted_with_answer = participants[4][0]
      late_save = mutate(
        unsubmitted_with_answer,
        "PUT",
        f"/api/rooms/{room_id}/responses/{question['id']}",
        json={"text": "A late replacement must not enter the snapshot."},
      )
      late_submit = mutate(
        unsubmitted_with_answer,
        "POST",
        f"/api/rooms/{room_id}/submit",
      )
      never_answered = mutate(
        participants[5][0],
        "POST",
        f"/api/rooms/{room_id}/submit",
      )
      for blocked in (late_save, late_submit, never_answered):
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "ROOM_NOT_ANSWERING"

      assert scheduler.run_ready() == 1
      result = host.get(f"/api/rooms/{room_id}/groups")
      assert result.status_code == 200, result.text
      assert result.json()["trigger"] == "host"

      stored = app.state.room_repository.get(UUID(room_id))
      assert stored is not None
      assert stored.analysis_attempt_count == 1
      assert stored.status == "published"
      assert stored.participants[UUID(participants[4][1])].submitted_at is None
      assert stored.participants[UUID(participants[5][1])].submitted_at is None
      assert (
        stored.responses[(UUID(participants[4][1]), UUID(question["id"]))].text
        == (fixture["participants"][4]["answer"])
      )
    finally:
      _close_participants(participants)
