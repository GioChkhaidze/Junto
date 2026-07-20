from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from junto.config import Settings
from junto.engine.compiler import SemanticCompiler
from junto.engine.optimizer import CoverageFirstOptimizer, OptimizerConfig
from junto.engine.provider import RecordedSemanticProvider
from junto.main import create_app
from junto.services.analysis import CoverageAnalysisPipeline
from junto.services.personas import synthetic_personas
from tests.conftest import RecordingScheduler, mutate

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "semantic"
FIXTURE_PATHS = (
  FIXTURE_DIRECTORY / "programming_dynamic_programming.json",
  FIXTURE_DIRECTORY / "machine_learning_trm_architecture.json",
)


def _fixtures() -> tuple[dict[str, Any], ...]:
  fixtures: list[dict[str, Any]] = []
  for path in FIXTURE_PATHS:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    fixtures.append(value)
  return tuple(fixtures)


def _app(tmp_path: Path, scheduler: RecordingScheduler) -> tuple[FastAPI, RecordedSemanticProvider]:
  provider = RecordedSemanticProvider.from_fixture_files(FIXTURE_PATHS)
  timeout = 3.0
  pipeline = CoverageAnalysisPipeline(
    compiler=SemanticCompiler(provider, transport_retry_delay_seconds=0),
    optimizer=CoverageFirstOptimizer(OptimizerConfig(timeout_seconds=timeout, random_seed=41)),
    solver_timeout_seconds=timeout,
  )
  app = create_app(
    app_settings=Settings(
      environment="test",
      session_secret="multi-question-lifecycle-secret-with-enough-entropy",
      engine_mode="recorded",
      answer_rate_limit_per_minute=10_000,
      join_rate_limit_per_minute=1_000,
      room_create_rate_limit_per_minute=1_000,
      status_rate_limit_per_minute=10_000,
      solver_timeout_seconds=timeout,
    ),
    scheduler=scheduler,
    frontend_dist=tmp_path / "no-frontend-build",
    analysis_pipeline=pipeline,
  )
  return app, provider


def _all_keys(value: object) -> set[str]:
  if isinstance(value, dict):
    return set(value) | {key for item in value.values() for key in _all_keys(item)}
  if isinstance(value, list):
    return {key for item in value for key in _all_keys(item)}
  return set()


def _non_empty_answers(fixture: dict[str, Any]) -> tuple[str, ...]:
  answers = tuple(
    str(participant["answer"]) for participant in fixture["participants"] if str(participant["answer"]).strip()
  )
  assert answers
  return answers


def test_recorded_multi_question_room_completes_the_public_lifecycle_without_projection_leaks(
  tmp_path: Path,
) -> None:
  fixtures = _fixtures()
  scheduler = RecordingScheduler()
  app, provider = _app(tmp_path, scheduler)

  with TestClient(app) as host:
    created = mutate(
      host,
      "POST",
      "/api/rooms",
      json={
        "title": "Cross-subject reasoning workshop",
        "policy": "teach",
        "durationMinutes": 20,
        "groupSize": {"minimum": 3, "preferred": 4, "maximum": 5},
      },
    )
    assert created.status_code == 201, created.text
    room_id = created.json()["roomId"]
    join_code = created.json()["joinCode"]
    question_ids: list[str] = []
    for position, fixture in enumerate(fixtures):
      question = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/questions",
        json={
          "position": position,
          "prompt": fixture["questionPrompt"],
          "referenceMaterial": fixture["referenceMaterial"],
          "coverageUnits": [{"text": unit["text"]} for unit in fixture["coverageUnits"]],
        },
      )
      assert question.status_code == 201, question.text
      question_ids.append(question.json()["id"])
    opened = mutate(host, "POST", f"/api/rooms/{room_id}/open")
    assert opened.status_code == 200, opened.text

    participants: list[tuple[TestClient, str]] = []
    expected_names = [persona.display_name for persona in synthetic_personas(20, seed=41)]
    reviewed_answers = tuple(_non_empty_answers(fixture) for fixture in fixtures)
    draft_only_text = {str(fixture["referenceMaterial"]) for fixture in fixtures} | {
      str(value)
      for fixture in fixtures
      for value in (
        *(unit["text"] for unit in fixture["coverageUnits"]),
        *(family["label"] for family in fixture["expectedFamilies"]["families"]),
      )
    }
    assert len(set(expected_names)) == 20
    try:
      for name in expected_names:
        client = TestClient(app)
        joined = mutate(client, "POST", f"/api/join/{join_code}", json={"displayName": name})
        assert joined.status_code == 201, joined.text
        participants.append((client, joined.json()["participantId"]))

      started = mutate(host, "POST", f"/api/rooms/{room_id}/start")
      assert started.status_code == 200, started.text
      forbidden_questionnaire_keys = {
        "coverageUnits",
        "groupSize",
        "joinCode",
        "label",
        "lastError",
        "materials",
        "participants",
        "policy",
        "progress",
        "referenceMaterial",
        "representedFamilies",
        "responseAudit",
        "solver",
      }
      for participant_index, (client, _participant_id) in enumerate(participants):
        questionnaire = client.get(f"/api/rooms/{room_id}/participant")
        assert questionnaire.status_code == 200, questionnaire.text
        projection = questionnaire.json()
        assert projection["questionCount"] == len(fixtures)
        assert len(projection["questions"]) == len(fixtures)
        assert _all_keys(projection).isdisjoint(forbidden_questionnaire_keys)
        projection_text = json.dumps(projection, sort_keys=True)
        assert all(text not in projection_text for text in draft_only_text)

        for question_index, (question_id, answers) in enumerate(zip(question_ids, reviewed_answers, strict=True)):
          saved = mutate(
            client,
            "PUT",
            f"/api/rooms/{room_id}/responses/{question_id}",
            json={"text": answers[(participant_index + question_index) % len(answers)]},
          )
          assert saved.status_code == 200, saved.text
          assert saved.json()["answeredQuestionCount"] == question_index + 1

        submitted = mutate(client, "POST", f"/api/rooms/{room_id}/submit")
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["answeredQuestionCount"] == len(fixtures)
        assert submitted.json()["questionCount"] == len(fixtures)
        assert submitted.json()["analysisStarted"] is (participant_index == len(participants) - 1)

      assert scheduler.run_ready() == 1
      host_result_response = host.get(f"/api/rooms/{room_id}/groups")
      assert host_result_response.status_code == 200, host_result_response.text
      host_result = host_result_response.json()
      assert host_result["generationMode"] == "coverage_aware"
      assert host_result["trigger"] == "all_submitted"
      assert host_result["solver"]["status"] in {"optimal", "feasible"}

      groups = host_result["groups"]
      expected_ids = {participant_id for _client, participant_id in participants}
      member_ids = [member["participantId"] for group in groups for member in group["members"]]
      assert len(member_ids) == len(expected_ids) == 20
      assert set(member_ids) == expected_ids
      assert len(member_ids) == len(set(member_ids))
      assert {member["displayName"] for group in groups for member in group["members"]} == set(expected_names)
      assert all(3 <= len(group["members"]) <= 5 for group in groups)
      assert all(len(group["questions"]) == len(fixtures) for group in groups)
      assert all({question["questionId"] for question in group["questions"]} == set(question_ids) for group in groups)

      group_questions = [question for group in groups for question in group["questions"]]
      report = host_result["coverageReport"]
      assert report["totalGroupQuestions"] == len(groups) * len(fixtures) == len(group_questions)
      assert report["fullyCoveredGroupQuestions"] == sum(question["fullyCovered"] for question in group_questions)
      coverage_calls = [call for call in provider.calls if call.branch == "coverage"]
      family_calls = [call for call in provider.calls if call.branch == "family"]
      assert len(coverage_calls) == len(fixtures) * 4
      assert len(family_calls) == len(fixtures)
      assert all(call.answer_count == 5 for call in coverage_calls)
      assert all(call.answer_count == 20 for call in family_calls)
      assert all(
        sum(call.answer_count for call in coverage_calls if call.question_id == question_id) == 20
        for question_id in question_ids
      )
      assert all(not call.repair for call in provider.calls)

      host_group_by_member = {member["participantId"]: group for group in groups for member in group["members"]}
      all_reviewed_answers = {answer for answers in reviewed_answers for answer in answers}
      for client, participant_id in participants:
        published_room = client.get(f"/api/rooms/{room_id}/participant")
        assert published_room.status_code == 200, published_room.text
        assert _all_keys(published_room.json()).isdisjoint(forbidden_questionnaire_keys)

        private_response = client.get(f"/api/rooms/{room_id}/my-group")
        assert private_response.status_code == 200, private_response.text
        private = private_response.json()
        expected_group = host_group_by_member[participant_id]
        assert private["group"]["id"] == expected_group["id"]
        assert {member["participantId"] for member in private["group"]["members"]} == {
          member["participantId"] for member in expected_group["members"]
        }
        assert len(private["group"]["questions"]) == len(fixtures)
        private_text = json.dumps(private, sort_keys=True)
        assert "referenceMaterial" not in private_text
        assert "responseAudit" not in private_text
        assert "solver" not in private_text
        assert all(str(fixture["referenceMaterial"]) not in private_text for fixture in fixtures)
        assert all(answer not in private_text for answer in all_reviewed_answers)
        assert client.get(f"/api/rooms/{room_id}").status_code == 404
        assert client.get(f"/api/rooms/{room_id}/groups").status_code == 404
    finally:
      for client, _participant_id in participants:
        client.close()
