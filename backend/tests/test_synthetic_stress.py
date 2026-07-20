from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from scripts.evaluate_synthetic_stress import (
  DEFAULT_CHALLENGE_FIXTURE,
  DEFAULT_GOLD_DIRECTORY,
  build_report,
  main,
)

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
  assert report["challengeSuite"]["scenarioCount"] >= 10
  assert report["challengeSuite"]["subjectCount"] >= 10
  assert report["challengeSuite"]["personaCount"] == 20
  assert report["challengeSuite"]["uniquePersonaIdCount"] == 20
  assert report["challengeSuite"]["uniqueDisplayNameCount"] == 20
  assert report["challengeSuite"]["missingRequiredCaseTags"] == []
  assert report["challengeSuite"]["providerCalls"] == 0
  assert report["scaleSuite"]["maximumQuestionCount"] == 8
  assert report["scaleSuite"]["maximumParticipantCount"] == 20
  assert report["scaleSuite"]["payloadsOverCompilerLimit"] == 0
  assert report["scaleSuite"]["providerCalls"] == 0


def test_offline_stress_cli_writes_machine_readable_report(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
  output = tmp_path / "stress.json"
  monkeypatch.setattr(
    "sys.argv",
    ["evaluate_synthetic_stress.py", "--output", str(output)],
  )

  assert main() == 0
  report = json.loads(output.read_text(encoding="utf-8"))
  assert report["overallStatus"] == "pass"
  assert report["challengeSuite"]["scoreType"] == "structural-only"


def test_committed_offline_report_matches_current_corpus() -> None:
  current = build_report(
    gold_directory=DEFAULT_GOLD_DIRECTORY,
    challenge_fixture=DEFAULT_CHALLENGE_FIXTURE,
  )
  committed = json.loads(COMMITTED_REPORT.read_text(encoding="utf-8"))
  current.pop("generatedAt")
  committed.pop("generatedAt")

  assert committed == current
