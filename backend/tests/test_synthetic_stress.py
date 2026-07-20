from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from scripts.evaluate_synthetic_stress import (
  DEFAULT_CHALLENGE_FIXTURE,
  DEFAULT_GOLD_DIRECTORY,
  activity_payloads,
  build_report,
  main,
)
from tests.conftest import AppHarness, mutate

COMMITTED_REPORT = Path(__file__).resolve().parents[2] / "docs" / "evidence" / ("synthetic-stress-offline.json")


def test_offline_stress_suite_exercises_diverse_structural_cases() -> None:
  report = build_report(
    gold_directory=DEFAULT_GOLD_DIRECTORY,
    challenge_fixture=DEFAULT_CHALLENGE_FIXTURE,
  )

  assert report["overallStatus"] == "pass"
  assert report["mode"] == "offline"
  assert report["semanticAccuracyClaim"] == "none"
  assert report["goldSuite"]["evaluatedByThisSuite"] is False
  assert report["activitySuite"]["activityCount"] == 12
  assert report["activitySuite"]["oneQuestionActivityCount"] == 12
  assert report["activitySuite"]["minimumCoverageUnitsPerActivity"] >= 3
  assert report["activitySuite"]["maximumCoverageUnitsPerActivity"] <= 6
  assert report["activitySuite"]["coverageUnitCountViolations"] == 0
  assert report["activitySuite"]["fieldViolations"] == []
  assert report["activitySuite"]["semanticAccuracyClaim"] == "none"
  assert report["challengeSuite"]["scenarioCount"] >= 10
  assert report["challengeSuite"]["subjectCount"] >= 10
  assert report["challengeSuite"]["personaCount"] == 20
  assert report["challengeSuite"]["uniquePersonaIdCount"] == 20
  assert report["challengeSuite"]["uniqueDisplayNameCount"] == 20
  assert report["challengeSuite"]["sourceAnswerTemplateCount"] == 49
  assert report["challengeSuite"]["sourceAnswerDuplicationRatio"] == 0.7958
  assert report["challengeSuite"]["diversityMeasure"].startswith("source answer templates")
  assert report["challengeSuite"]["missingRequiredCaseTags"] == []
  assert report["challengeSuite"]["semanticAccuracyClaim"] == "none"
  assert report["scaleSuite"]["maximumQuestionCount"] == 8
  assert report["scaleSuite"]["maximumParticipantCount"] == 20
  assert report["scaleSuite"]["maximumAssembledPayloadUtf8Bytes"] > 0
  assert all(case["assembledPayloadUtf8Bytes"] > 0 for case in report["scaleSuite"]["cases"])
  assert "compilerInputLimitBytes" not in report["scaleSuite"]
  assert "payloadsOverCompilerLimit" not in report["scaleSuite"]
  assert all("withinCompilerInputLimit" not in case for case in report["scaleSuite"]["cases"])
  assert report["scaleSuite"]["sourceTextPreservationViolations"] == 0
  assert report["scaleSuite"]["tagPreservationViolations"] == 0


def test_each_challenge_activity_creates_an_independent_one_question_room(harness: AppHarness) -> None:
  room_ids: set[str] = set()
  for activity in activity_payloads():
    host = TestClient(harness.app)
    created = mutate(host, "POST", "/api/rooms", json=activity["room"])
    assert created.status_code == 201, created.text
    room_id = created.json()["roomId"]
    room_ids.add(room_id)
    questions = activity["questions"]
    assert len(questions) == 1
    added = mutate(host, "POST", f"/api/rooms/{room_id}/questions", json=questions[0])
    assert added.status_code == 201, added.text
    room = host.get(f"/api/rooms/{room_id}")
    assert room.status_code == 200, room.text
    assert room.json()["title"] == activity["room"]["title"]
    assert len(room.json()["questions"]) == 1
    assert [unit["text"] for unit in room.json()["questions"][0]["coverageUnits"]] == [
      unit["text"] for unit in questions[0]["coverageUnits"]
    ]

  assert len(room_ids) == len(activity_payloads())


@pytest.mark.parametrize("field", ["id", "text"])
def test_challenge_fixture_rejects_duplicate_coverage_fields(tmp_path: Path, field: str) -> None:
  fixture = json.loads(DEFAULT_CHALLENGE_FIXTURE.read_text(encoding="utf-8"))
  fixture["scenarios"][1]["coverageUnits"][0][field] = fixture["scenarios"][0]["coverageUnits"][0][field]
  challenge = tmp_path / "duplicate.json"
  challenge.write_text(json.dumps(fixture), encoding="utf-8")

  with pytest.raises(ValueError, match=f"Duplicate coverage unit {field.upper() if field == 'id' else field}"):
    build_report(gold_directory=DEFAULT_GOLD_DIRECTORY, challenge_fixture=challenge)


def test_offline_stress_cli_writes_machine_readable_report(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
  output = tmp_path / "stress.json"
  monkeypatch.setattr(
    "sys.argv",
    ["evaluate_synthetic_stress.py", "--output", str(output)],
  )

  assert main() == 0
  report = json.loads(output.read_text(encoding="utf-8"))
  assert report["overallStatus"] == "pass"
  assert report["challengeSuite"]["semanticAccuracyClaim"] == "none"


def test_committed_offline_report_matches_current_corpus() -> None:
  current = build_report(
    gold_directory=DEFAULT_GOLD_DIRECTORY,
    challenge_fixture=DEFAULT_CHALLENGE_FIXTURE,
  )
  committed = json.loads(COMMITTED_REPORT.read_text(encoding="utf-8"))
  current.pop("generatedAt")
  committed.pop("generatedAt")

  assert committed == current
