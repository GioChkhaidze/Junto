from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "semantic"
SCIENCE_FIXTURES = {
  "statistics": FIXTURE_DIRECTORY / "statistics_randomized_tutoring.json",
  "biology": FIXTURE_DIRECTORY / "biology_antibiotic_resistance.json",
}


def _fixture(subject: str) -> dict[str, Any]:
  value = json.loads(SCIENCE_FIXTURES[subject].read_text(encoding="utf-8"))
  assert isinstance(value, dict)
  return value


def test_science_fixtures_break_the_six_participant_template() -> None:
  statistics = _fixture("statistics")
  biology = _fixture("biology")

  assert len(statistics["participants"]) == 5
  assert len(biology["participants"]) == 7
  assert len(statistics["expectedFamilies"]["families"]) == 2
  assert len(biology["expectedFamilies"]["families"]) == 4
  assert statistics["participants"][2]["answer"] == ""
  assert biology["participants"][4]["answer"] == ""


def test_science_fixture_evidence_is_literal_and_adversarial_answers_stay_uncovered() -> None:
  for fixture in map(_fixture, SCIENCE_FIXTURES):
    answers = {item["participantId"]: item["answer"] for item in fixture["participants"]}
    assignments = fixture["expectedCoverage"]["assignments"]
    for assignment in assignments:
      answer = answers[assignment["participantId"]]
      assert all(quote in answer for evidence in assignment["evidence"] for quote in evidence["quotes"])

  statistics = _fixture("statistics")
  statistics_assignments = {item["participantId"]: item for item in statistics["expectedCoverage"]["assignments"]}
  statistics_families = {item["participantId"]: item for item in statistics["expectedFamilies"]["assignments"]}
  assert statistics["participants"][1]["answer"] == statistics["participants"][3]["answer"]
  assert statistics_assignments["77777777-7777-4777-8777-777777777205"]["coveredUnitIds"] == []
  assert statistics_families["77777777-7777-4777-8777-777777777205"]["familyIndex"] is not None

  biology = _fixture("biology")
  biology_assignments = {item["participantId"]: item for item in biology["expectedCoverage"]["assignments"]}
  biology_families = {item["participantId"]: item for item in biology["expectedFamilies"]["assignments"]}
  assert biology_assignments["88888888-8888-4888-8888-888888888205"]["coveredUnitIds"] == []
  assert biology_families["88888888-8888-4888-8888-888888888205"]["familyIndex"] is not None
