from __future__ import annotations

import json
from argparse import Namespace
from collections import Counter
from pathlib import Path

import pytest

from scripts import load_demo, release, start

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


def test_runtime_command_is_one_process_and_privacy_safe(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("PORT", "8080")
  monkeypatch.setenv("LOG_LEVEL", "warning")

  command = start.build_command()

  assert command[command.index("--workers") + 1] == "1"
  assert command[command.index("--port") + 1] == "8080"
  assert "--no-access-log" in command
  assert "--no-server-header" in command


def test_release_command_is_an_explicit_upgrade_to_head() -> None:
  command = release.build_command()

  assert command[-2:] == ["upgrade", "head"]
  assert command[command.index("-c") + 1].endswith("alembic.ini")
  assert str(release.BACKEND_DIRECTORY) in release.child_environment()["PYTHONPATH"]


def test_runtime_dependency_closure_is_pinned_without_test_tools() -> None:
  lines = [
    line.split(";", 1)[0].strip()
    for line in (BACKEND_DIRECTORY / "requirements.runtime.lock").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
  ]
  assert all("==" in line for line in lines)
  names = {line.split("==", 1)[0].lower() for line in lines}
  assert {"fastapi", "openai", "ortools", "psycopg", "sqlalchemy", "uvicorn"} <= names
  assert names.isdisjoint({"hypothesis", "mypy", "pytest", "ruff"})


def test_demo_loader_rejects_non_loopback_target() -> None:
  with pytest.raises(ValueError, match="loopback"):
    load_demo.BrowserClient("https://example.com")


def test_reviewed_questions_are_loaded_exactly_from_canonical_json() -> None:
  questions = load_demo.load_reviewed_questions()

  assert len(questions) == len(load_demo.DEFAULT_FIXTURE_PATHS) == 2
  for position, (path, question) in enumerate(zip(load_demo.DEFAULT_FIXTURE_PATHS, questions, strict=True)):
    raw = json.loads(path.read_text(encoding="utf-8"))
    payload = question.payload(position)
    assert question.fixture_id == raw["fixtureId"]
    assert question.subject == raw["subject"]
    assert question.prompt == raw["questionPrompt"]
    assert question.reference_material == raw["referenceMaterial"]
    assert question.coverage_units == tuple((unit["id"], unit["text"]) for unit in raw["coverageUnits"])
    assert question.answers == tuple(participant["answer"] for participant in raw["participants"])
    unit_ids = [unit_id for unit_id, _text in question.coverage_units]
    assert unit_ids
    assert len(unit_ids) == len(set(unit_ids))
    assert all(set(unit) == {"text"} for unit in payload["coverageUnits"])
    assert payload["referenceMaterial"] == raw["referenceMaterial"]


@pytest.mark.parametrize("participant_count", [3, 60])
def test_reviewed_answers_cycle_exact_fixture_content(participant_count: int) -> None:
  for question in load_demo.load_reviewed_questions():
    cycled = [question.answer_for(index) for index in range(participant_count)]
    assert cycled == [question.answers[index % len(question.answers)] for index in range(participant_count)]
    assert set(cycled) <= set(question.answers)
    if participant_count == 60:
      assert Counter(cycled) == Counter(
        {answer: participant_count // len(question.answers) for answer in question.answers}
      )


def test_loader_validates_supported_classroom_envelope_before_http() -> None:
  arguments = Namespace(
    participants=61,
    join_code=None,
    base_url="http://127.0.0.1:8000",
    duration_minutes=20,
    wait_seconds=1.0,
    poll_rounds=0,
    fixture_paths=None,
  )

  with pytest.raises(ValueError, match="between 3 and 60"):
    load_demo.load_fixture(arguments)
