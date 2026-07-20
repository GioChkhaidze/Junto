from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from junto.engine.compiler import SemanticAnswerInput
from junto.engine.openrouter_provider import OpenRouterSemanticProvider
from junto.engine.prompts import CoveragePrompt, FamilyPrompt
from junto.engine.provider import (
  CoverageClassificationOutput,
  FamilyClusteringOutput,
  ProviderRepair,
  ProviderResult,
  ProviderTelemetry,
  RecordedSemanticProvider,
)
from scripts.evaluate_semantic import (
  MeasuringProvider,
  _blind_live_fixture,
  _evaluate,
  _fixture_paths,
  _live_model,
  _load_fixture,
  _parser,
  _prepare_evaluation_fixtures,
  _provider,
  _readiness_claim,
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "semantic"


@dataclass(slots=True)
class _EvaluatorArgs:
  mode: str = "live"
  live_provider: str = "openrouter"
  fixtures: Path = FIXTURE_DIRECTORY
  fixture: list[Path] | None = None
  model: str | None = None
  reasoning_effort: str = "high"
  timeout_seconds: float = 5
  max_fixture_latency_ms: int = 180_000
  max_output_tokens: int = 20_000
  max_total_tokens: int = 250_000
  seed: int = 41
  output: Path | None = None


class _MeteredRecordedProvider:
  def __init__(self, delegate: RecordedSemanticProvider) -> None:
    self.delegate = delegate

  @property
  def model_name(self) -> str:
    return "metered-recorded-live-test"

  async def classify_coverage(
    self,
    prompt: CoveragePrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[CoverageClassificationOutput]:
    result = await self.delegate.classify_coverage(prompt, repair=repair)
    return ProviderResult(value=result.value, telemetry=_test_telemetry())

  async def cluster_families(
    self,
    prompt: FamilyPrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[FamilyClusteringOutput]:
    result = await self.delegate.cluster_families(prompt, repair=repair)
    return ProviderResult(value=result.value, telemetry=_test_telemetry())


def _test_telemetry() -> ProviderTelemetry:
  return ProviderTelemetry(
    request_id="offline-live-test",
    elapsed_milliseconds=1,
    input_tokens=3,
    output_tokens=2,
    total_tokens=5,
  )


def _value_map_by_text(
  source: tuple[SemanticAnswerInput, ...],
  blinded: tuple[SemanticAnswerInput, ...],
) -> dict[UUID, UUID]:
  blinded_by_text = {item.text: item for item in blinded}
  return {item.participant_id: blinded_by_text[item.text].participant_id for item in source}


def test_exact_fixture_selection_is_deduplicated_and_sorted(tmp_path: Path) -> None:
  first = tmp_path / "a.json"
  second = tmp_path / "b.json"
  args = _parser().parse_args(["--fixture", str(second), "--fixture", str(first), "--fixture", str(second)])

  assert _fixture_paths(args) == (first, second)


def test_openai_live_defaults_use_luna_with_high_reasoning() -> None:
  args = _parser().parse_args(["--mode", "live"])

  assert _live_model(args) == "gpt-5.6-luna"
  assert args.reasoning_effort == "high"
  assert args.seed == 41


def test_openrouter_live_default_uses_full_flash() -> None:
  args = _parser().parse_args(["--mode", "live", "--live-provider", "openrouter"])

  assert _live_model(args) == "google/gemini-2.5-flash"


def test_explicit_fixture_directory_selects_json_files_in_sorted_order(tmp_path: Path) -> None:
  first = tmp_path / "a.json"
  second = tmp_path / "b.json"
  first.touch()
  second.touch()
  (tmp_path / "notes.txt").touch()
  args = _parser().parse_args(["--fixtures", str(tmp_path)])

  assert _fixture_paths(args) == (first, second)


def test_fixture_file_and_directory_options_are_mutually_exclusive(tmp_path: Path) -> None:
  with pytest.raises(SystemExit, match="2"):
    _parser().parse_args(["--fixtures", str(tmp_path), "--fixture", str(tmp_path / "one.json")])


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
  assert "blindSeed" not in report
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


def test_live_blinding_is_deterministic_and_seed_sensitive() -> None:
  source = _load_fixture(FIXTURE_DIRECTORY / "programming_dynamic_programming.json")

  first = _blind_live_fixture(source, seed=41)
  repeated = _blind_live_fixture(source, seed=41)
  changed = _blind_live_fixture(source, seed=97)

  assert first == repeated
  assert first != changed
  assert first.question.question_id != source.question.question_id
  assert changed.question.question_id != first.question.question_id
  assert [answer.text for answer in first.question.answers] != [answer.text for answer in source.question.answers]
  assert [answer.text for answer in changed.question.answers] != [answer.text for answer in first.question.answers]
  assert set(first.question.participant_ids).isdisjoint(source.question.participant_ids)
  assert {unit.id for unit in first.question.coverage_units}.isdisjoint(
    unit.id for unit in source.question.coverage_units
  )


def test_live_blinding_remaps_gold_labels_relationships_and_answer_index() -> None:
  source = _load_fixture(FIXTURE_DIRECTORY / "programming_dynamic_programming.json")
  blinded = _blind_live_fixture(source, seed=41)
  participant_ids = _value_map_by_text(source.question.answers, blinded.question.answers)
  blinded_units_by_text = {unit.text: unit.id for unit in blinded.question.coverage_units}
  unit_ids = {unit.id: blinded_units_by_text[unit.text] for unit in source.question.coverage_units}

  assert blinded.expected_coverage == {
    participant_ids[participant_id]: frozenset(unit_ids[unit_id] for unit_id in covered_unit_ids)
    for participant_id, covered_unit_ids in source.expected_coverage.items()
  }
  assert blinded.expected_family == {
    participant_ids[participant_id]: family_index for participant_id, family_index in source.expected_family.items()
  }
  assert blinded.answer_by_participant == {
    str(answer.participant_id): answer.text for answer in blinded.question.answers
  }
  serialized_relationships = json.dumps(blinded.relationships)
  assert all(str(participant_id) not in serialized_relationships for participant_id in source.question.participant_ids)
  assert all(
    str(participant_ids[participant_id]) in serialized_relationships
    for participant_id in source.question.participant_ids
    if str(participant_id) in json.dumps(source.relationships)
  )


def test_recorded_fixture_preparation_is_an_exact_noop() -> None:
  fixture = _load_fixture(FIXTURE_DIRECTORY / "programming_dynamic_programming.json")
  fixtures = (fixture,)

  prepared = _prepare_evaluation_fixtures(fixtures, mode="recorded", seed=999)

  assert prepared is fixtures
  assert prepared[0] is fixture


def test_blinded_live_scoring_passes_without_identifier_or_text_leakage() -> None:
  path = FIXTURE_DIRECTORY / "biology_antibiotic_resistance.json"
  source = _load_fixture(path)
  blinded = _blind_live_fixture(source, seed=73)
  delegate = RecordedSemanticProvider.from_fixture_files([path])
  provider = MeasuringProvider(_MeteredRecordedProvider(delegate))

  report = _evaluate(
    (source,),
    provider,
    mode="live",
    provider_name="openai",
    request_timeout_seconds=5,
    seed=73,
  )

  assert report["overallStatus"] == "pass"
  assert report["blindSeed"] == 73
  assert report["aggregate"]["coveragePrecision"] == 1
  assert report["aggregate"]["coverageRecall"] == 1
  assert report["aggregate"]["familyPairwiseF1"] == 1
  assert all(call.question_id == str(blinded.question.question_id) for call in delegate.calls)
  assert {participant_id for call in delegate.calls for participant_id in call.participant_ids} == {
    str(answer.participant_id) for answer in blinded.question.answers if answer.text
  }
  assert {unit_id for call in delegate.calls for unit_id in call.unit_ids} == {
    unit.id for unit in blinded.question.coverage_units
  }
  coverage_outputs = provider.coverage_outputs[str(blinded.question.question_id)].values()
  assert len(provider.coverage_outputs[str(blinded.question.question_id)]) == 2
  assert all(
    quote in blinded.answer_by_participant[assignment.participant_id]
    for output in coverage_outputs
    for assignment in output.assignments
    for evidence in assignment.evidence
    for quote in evidence.quotes
  )
  assert report["aggregate"]["tokenUsage"] == {
    "input": 9,
    "output": 6,
    "reasoning": 0,
    "total": 15,
    "maximumAllowed": 250_000,
    "reportedForEveryCall": True,
  }

  serialized = json.dumps(report)
  source_identifiers = [source.question.question_id, *source.question.participant_ids]
  assert all(str(identifier) not in serialized for identifier in source_identifiers)
  assert all(unit.id not in serialized for unit in source.question.coverage_units)
  assert source.question.prompt not in serialized
  assert all(answer.text not in serialized for answer in source.question.answers if answer.text)


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
