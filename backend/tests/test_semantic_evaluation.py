from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from junto.engine.openrouter_provider import OpenRouterSemanticProvider
from junto.engine.provider import RecordedSemanticProvider
from scripts.evaluate_semantic import (
  MeasuringProvider,
  _evaluate,
  _load_fixture,
  _provider,
  _readiness_claim,
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "semantic"


@dataclass(slots=True)
class _EvaluatorArgs:
  mode: str = "live"
  live_provider: str = "openrouter"
  fixtures: Path = FIXTURE_DIRECTORY
  model: str | None = None
  reasoning_effort: str = "low"
  timeout_seconds: float = 5
  max_fixture_latency_ms: int = 180_000
  max_total_tokens: int = 250_000
  output: Path | None = None


def test_recorded_evaluation_passes_all_contract_gates_without_exposing_text() -> None:
  paths = tuple(sorted(FIXTURE_DIRECTORY.glob("*.json")))
  fixtures = tuple(_load_fixture(path) for path in paths)
  provider = MeasuringProvider(RecordedSemanticProvider.from_fixture_files(paths))

  report = _evaluate(
    fixtures,
    provider,
    mode="recorded",
    request_timeout_seconds=5,
  )

  assert report["overallStatus"] == "pass"
  assert report["schemaVersion"] == "2"
  assert report["provider"] == "recorded"
  assert len(report["gates"]) == 9
  assert all(gate["status"] == "pass" for gate in report["gates"])
  assert report["aggregate"]["tokenUsage"]["total"] == 0
  assert all(not fixture["coverageMismatches"] for fixture in report["fixtures"])
  assert all(not fixture["familyFalsePositivePairs"] for fixture in report["fixtures"])
  assert all(not fixture["familyFalseNegativePairs"] for fixture in report["fixtures"])
  assert all(not fixture["failedRelationshipChecks"] for fixture in report["fixtures"])

  serialized = json.dumps(report)
  for path in paths:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["questionPrompt"] not in serialized
    if payload["referenceMaterial"]:
      assert payload["referenceMaterial"] not in serialized
    for participant in payload["participants"]:
      if participant["answer"]:
        assert participant["answer"] not in serialized
    for unit in payload["coverageUnits"]:
      assert unit["text"] not in serialized


def test_failed_live_gates_never_claim_model_readiness() -> None:
  claim = _readiness_claim("live", gates_passed=False)

  assert "failed" in claim.lower()
  assert "do not make a model-readiness claim" in claim


def test_openrouter_provider_selection_uses_provider_specific_model_without_network(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-never-sent")

  provider = _provider(_EvaluatorArgs(model="test/structured-model"), ())

  assert isinstance(provider, OpenRouterSemanticProvider)
  assert provider.model_name == "test/structured-model"


def test_openrouter_provider_requires_its_own_key(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

  with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
    _provider(_EvaluatorArgs(), ())
