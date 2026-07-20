"""Evaluate Junto's semantic compiler against adjudicated, privacy-safe fixtures.

Recorded mode verifies the evaluator and compiler contract without network access. Live mode
uses the configured OpenAI or OpenRouter model against the same adjudicated labels.
The report contains IDs, counts, metrics, timings, and token usage only; it never emits question,
reference, answer, evidence-quote, or coverage-unit text.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from junto.engine.compiler import (
  CoverageUnitInput,
  QuestionCompilationInput,
  SemanticAnswerInput,
  SemanticCompiler,
  SemanticCompilerError,
)
from junto.engine.models import QuestionSemanticArtifact
from junto.engine.openrouter import OpenRouterStructuredClient
from junto.engine.openrouter_provider import OpenRouterSemanticProvider
from junto.engine.prompts import CoveragePrompt, FamilyPrompt
from junto.engine.provider import (
  CoverageClassificationOutput,
  FamilyClusteringOutput,
  OpenAISemanticProvider,
  ProviderRepair,
  ProviderResult,
  ProviderTelemetry,
  RecordedSemanticProvider,
  SemanticProvider,
)

DEFAULT_FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "semantic"
QUALITY_GATES = {
  "schemaDomainSuccessRate": 1.0,
  "assignmentCompletenessRate": 1.0,
  "evidenceLiteralIntegrityRate": 1.0,
  "familyUnitMatrixIntegrityRate": 1.0,
  "coveragePrecision": 0.90,
  "coverageRecall": 0.80,
  "familyPairwiseF1": 0.80,
  "latencyWithinLimitRate": 1.0,
  "tokenUsageWithinLimit": 1.0,
}


@dataclass(frozen=True, slots=True)
class EvaluationFixture:
  fixture_id: str
  subject: str
  question: QuestionCompilationInput
  expected_coverage: dict[UUID, frozenset[str]]
  expected_family: dict[UUID, int | None]
  relationships: dict[str, Any]
  answer_by_participant: dict[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProviderCall:
  question_id: str
  branch: Literal["coverage", "family"]
  repair: bool
  outcome: str
  telemetry: ProviderTelemetry | None


class MeasuringProvider:
  """Collect safe provider metadata and final structured results for evaluation."""

  def __init__(self, delegate: SemanticProvider) -> None:
    self._delegate = delegate
    self.calls: list[ProviderCall] = []
    self.coverage_outputs: dict[str, CoverageClassificationOutput] = {}
    self.family_outputs: dict[str, FamilyClusteringOutput] = {}

  @property
  def model_name(self) -> str:
    return self._delegate.model_name

  async def classify_coverage(
    self,
    prompt: CoveragePrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[CoverageClassificationOutput]:
    try:
      result = await self._delegate.classify_coverage(prompt, repair=repair)
    except Exception as error:
      self.calls.append(
        ProviderCall(
          question_id=prompt.question_id,
          branch="coverage",
          repair=repair is not None,
          outcome=type(error).__name__,
          telemetry=None,
        )
      )
      raise
    self.calls.append(
      ProviderCall(
        question_id=prompt.question_id,
        branch="coverage",
        repair=repair is not None,
        outcome="valid_schema",
        telemetry=result.telemetry,
      )
    )
    self.coverage_outputs[prompt.question_id] = result.value
    return result

  async def cluster_families(
    self,
    prompt: FamilyPrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[FamilyClusteringOutput]:
    try:
      result = await self._delegate.cluster_families(prompt, repair=repair)
    except Exception as error:
      self.calls.append(
        ProviderCall(
          question_id=prompt.question_id,
          branch="family",
          repair=repair is not None,
          outcome=type(error).__name__,
          telemetry=None,
        )
      )
      raise
    self.calls.append(
      ProviderCall(
        question_id=prompt.question_id,
        branch="family",
        repair=repair is not None,
        outcome="valid_schema",
        telemetry=result.telemetry,
      )
    )
    self.family_outputs[prompt.question_id] = result.value
    return result


class _Args(Protocol):
  mode: str
  live_provider: str
  fixtures: Path
  model: str | None
  reasoning_effort: str
  timeout_seconds: float
  max_fixture_latency_ms: int
  max_total_tokens: int
  output: Path | None


def main() -> int:
  args = cast(_Args, _parser().parse_args())
  fixture_paths = tuple(sorted(args.fixtures.glob("*.json")))
  if not fixture_paths:
    print("No semantic fixtures were found.", file=sys.stderr)
    return 2
  try:
    fixtures = tuple(_load_fixture(path) for path in fixture_paths)
    delegate = _provider(args, fixture_paths)
    provider = MeasuringProvider(delegate)
    report = _evaluate(
      fixtures,
      provider,
      mode=cast(Literal["recorded", "live"], args.mode),
      provider_name=_provider_name(args),
      request_timeout_seconds=args.timeout_seconds,
      max_fixture_latency_ms=args.max_fixture_latency_ms,
      max_total_tokens=args.max_total_tokens,
    )
  except (OSError, ValueError, SemanticCompilerError) as error:
    # These messages are authored by this evaluator/compiler and never include source text.
    print(f"Semantic evaluation could not start: {error}", file=sys.stderr)
    return 2

  serialized = json.dumps(report, indent=2, sort_keys=True)
  if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
  print(serialized)
  return 0 if report["overallStatus"] == "pass" else 1


def _parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--mode", choices=("recorded", "live"), default="recorded")
  parser.add_argument(
    "--live-provider",
    choices=("openai", "openrouter"),
    default="openai",
    help="Provider used only in live mode; recorded mode never contacts either provider.",
  )
  parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_DIRECTORY)
  parser.add_argument(
    "--model",
    default=None,
    help="Explicit live model ID. Defaults to the selected provider's environment setting.",
  )
  parser.add_argument(
    "--reasoning-effort",
    choices=("none", "low", "medium", "high", "xhigh", "max"),
    default="low",
    help="Reasoning effort used by the OpenAI live provider.",
  )
  parser.add_argument(
    "--timeout-seconds",
    type=float,
    default=45.0,
  )
  parser.add_argument("--max-fixture-latency-ms", type=int, default=180_000)
  parser.add_argument("--max-total-tokens", type=int, default=250_000)
  parser.add_argument("--output", type=Path)
  return parser


def _provider(args: _Args, paths: tuple[Path, ...]) -> SemanticProvider:
  if args.mode == "recorded":
    return RecordedSemanticProvider.from_fixture_files(paths)
  model = _live_model(args)
  if not model.strip():
    raise ValueError("--model must not be empty")
  if args.timeout_seconds <= 0:
    raise ValueError("--timeout-seconds must be positive")
  if args.live_provider == "openrouter":
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key is None or not api_key.strip():
      raise ValueError("OPENROUTER_API_KEY is required for --mode live --live-provider openrouter")
    client = OpenRouterStructuredClient(
      api_key=api_key,
      timeout_seconds=args.timeout_seconds,
    )
    return OpenRouterSemanticProvider(client=client, model=model)
  if args.live_provider != "openai":
    raise ValueError("--live-provider must be openai or openrouter")
  api_key = os.getenv("OPENAI_API_KEY")
  if api_key is None or not api_key.strip():
    raise ValueError("OPENAI_API_KEY is required for --mode live --live-provider openai")
  effort = cast(
    Literal["none", "low", "medium", "high", "xhigh", "max"],
    args.reasoning_effort,
  )
  return OpenAISemanticProvider.from_api_key(
    api_key=api_key,
    model=model,
    sdk_timeout_seconds=args.timeout_seconds,
    reasoning_effort=effort,
    safety_identifier="junto-reviewed-semantic-evaluation",
  )


def _provider_name(args: _Args) -> Literal["recorded", "openai", "openrouter"]:
  if args.mode == "recorded":
    return "recorded"
  return cast(Literal["openai", "openrouter"], args.live_provider)


def _live_model(args: _Args) -> str:
  if args.model is not None:
    return args.model
  if args.live_provider == "openrouter":
    return "google/gemini-2.5-flash-lite"
  return "gpt-5.6-sol"


def _load_fixture(path: Path) -> EvaluationFixture:
  payload = json.loads(path.read_text(encoding="utf-8"))
  if not isinstance(payload, dict):
    raise ValueError("Each fixture must be a JSON object.")
  participants = tuple(UUID(item["participantId"]) for item in payload["participants"])
  answers = tuple(
    SemanticAnswerInput(
      participant_id=UUID(item["participantId"]),
      text=item["answer"],
    )
    for item in payload["participants"]
  )
  expected_coverage: dict[UUID, frozenset[str]] = {participant_id: frozenset() for participant_id in participants}
  for assignment in payload["expectedCoverage"]["assignments"]:
    expected_coverage[UUID(assignment["participantId"])] = frozenset(assignment["coveredUnitIds"])
  expected_family: dict[UUID, int | None] = {participant_id: None for participant_id in participants}
  for assignment in payload["expectedFamilies"]["assignments"]:
    expected_family[UUID(assignment["participantId"])] = assignment["familyIndex"]
  question = QuestionCompilationInput(
    question_id=UUID(payload["questionId"]),
    prompt=payload["questionPrompt"],
    reference_material=payload.get("referenceMaterial"),
    coverage_units=tuple(CoverageUnitInput(id=item["id"], text=item["text"]) for item in payload["coverageUnits"]),
    participant_ids=participants,
    answers=answers,
  )
  return EvaluationFixture(
    fixture_id=str(payload["fixtureId"]),
    subject=str(payload["subject"]),
    question=question,
    expected_coverage=expected_coverage,
    expected_family=expected_family,
    relationships=payload["expectedRelationships"],
    answer_by_participant={str(answer.participant_id): answer.text for answer in answers},
  )


def _evaluate(
  fixtures: tuple[EvaluationFixture, ...],
  provider: MeasuringProvider,
  *,
  mode: Literal["recorded", "live"],
  provider_name: Literal["recorded", "openai", "openrouter"] = "recorded",
  request_timeout_seconds: float,
  max_fixture_latency_ms: int = 180_000,
  max_total_tokens: int = 250_000,
) -> dict[str, Any]:
  if max_fixture_latency_ms <= 0 or max_total_tokens < 0:
    raise ValueError("Evaluation latency and token limits are invalid.")
  compiler = SemanticCompiler(
    provider,
    request_timeout_seconds=request_timeout_seconds,
    room_timeout_seconds=max(request_timeout_seconds * 6, request_timeout_seconds),
    transport_retry_delay_seconds=0 if mode == "recorded" else 0.2,
  )
  totals = _Totals()
  fixture_reports: list[dict[str, Any]] = []
  for fixture in fixtures:
    started = perf_counter()
    error_code: str | None = None
    compiled: QuestionSemanticArtifact | None = None
    try:
      artifact = compiler.compile_sync([fixture.question])
      compiled = artifact.questions[0]
    except SemanticCompilerError as error:
      error_code = error.code
    elapsed_ms = max(0, round((perf_counter() - started) * 1000))
    fixture_report = _score_fixture(
      fixture,
      compiled,
      provider,
      elapsed_ms,
      error_code,
      max_fixture_latency_ms,
    )
    fixture_reports.append(fixture_report)
    totals.add(fixture_report)

  aggregate = totals.report(
    provider.calls,
    mode=mode,
    max_total_tokens=max_total_tokens,
  )
  gates = _gate_report(aggregate)
  gates_passed = all(item["status"] == "pass" for item in gates)
  return {
    "schemaVersion": "2",
    "generatedAt": datetime.now(UTC).isoformat(),
    "mode": mode,
    "provider": provider_name,
    "model": provider.model_name,
    "fixtureCount": len(fixtures),
    "fixtures": fixture_reports,
    "aggregate": aggregate,
    "gates": gates,
    "overallStatus": "pass" if gates_passed else "fail",
    "readinessClaim": _readiness_claim(mode, gates_passed=gates_passed),
  }


def _score_fixture(
  fixture: EvaluationFixture,
  compiled: QuestionSemanticArtifact | None,
  provider: MeasuringProvider,
  elapsed_ms: int,
  error_code: str | None,
  max_fixture_latency_ms: int,
) -> dict[str, Any]:
  question_id = str(fixture.question.question_id)
  if compiled is None:
    return {
      "fixtureId": fixture.fixture_id,
      "subject": fixture.subject,
      "status": "fail",
      "errorCode": error_code or "SEMANTIC_EVALUATION_FAILED",
      "schemaDomainValid": False,
      "assignmentComplete": False,
      "evidenceValid": False,
      "matrixChecksPassed": 0,
      "matrixChecksTotal": 1,
      "coverageTp": 0,
      "coverageFp": 0,
      "coverageFn": sum(len(value) for value in fixture.expected_coverage.values()),
      "familyTp": 0,
      "familyFp": 0,
      "familyFn": _expected_family_positive_pairs(fixture.expected_family),
      "coverageMismatches": [],
      "familyFalsePositivePairs": [],
      "familyFalseNegativePairs": [],
      "failedRelationshipChecks": [{"kind": "semanticCompilation", "participantIds": []}],
      "latencyMilliseconds": elapsed_ms,
      "latencyWithinLimit": elapsed_ms <= max_fixture_latency_ms,
    }

  assignments = {assignment.participant_id: assignment for assignment in compiled.assignments}
  assignment_complete = set(assignments) == set(fixture.question.participant_ids)
  coverage_tp = coverage_fp = coverage_fn = 0
  coverage_mismatches: list[dict[str, object]] = []
  for participant_id in fixture.question.participant_ids:
    expected = fixture.expected_coverage[participant_id]
    predicted = set(assignments[participant_id].covered_unit_ids)
    false_positive_ids = sorted(predicted - expected)
    false_negative_ids = sorted(expected - predicted)
    coverage_tp += len(expected & predicted)
    coverage_fp += len(false_positive_ids)
    coverage_fn += len(false_negative_ids)
    if false_positive_ids or false_negative_ids:
      coverage_mismatches.append(
        {
          "participantId": str(participant_id),
          "falsePositiveUnitIds": false_positive_ids,
          "falseNegativeUnitIds": false_negative_ids,
        }
      )
  predicted_families = {participant_id: assignments[participant_id].family_id for participant_id in assignments}
  family_tp, family_fp, family_fn = _family_pair_counts(
    fixture.expected_family,
    predicted_families,
  )
  false_positive_pairs, false_negative_pairs = _family_pair_mismatches(
    fixture.expected_family,
    predicted_families,
  )
  matrix_passed, matrix_total, failed_relationship_checks = _matrix_checks(fixture, assignments)
  evidence_valid = _evidence_is_valid(
    provider.coverage_outputs.get(question_id),
    fixture.answer_by_participant,
  )
  passed = assignment_complete and evidence_valid and matrix_passed == matrix_total
  return {
    "fixtureId": fixture.fixture_id,
    "subject": fixture.subject,
    "status": "pass" if passed else "fail",
    "errorCode": None,
    "schemaDomainValid": True,
    "assignmentComplete": assignment_complete,
    "evidenceValid": evidence_valid,
    "matrixChecksPassed": matrix_passed,
    "matrixChecksTotal": matrix_total,
    "coverageTp": coverage_tp,
    "coverageFp": coverage_fp,
    "coverageFn": coverage_fn,
    "familyTp": family_tp,
    "familyFp": family_fp,
    "familyFn": family_fn,
    "coverageMismatches": coverage_mismatches,
    "familyFalsePositivePairs": false_positive_pairs,
    "familyFalseNegativePairs": false_negative_pairs,
    "failedRelationshipChecks": failed_relationship_checks,
    "latencyMilliseconds": elapsed_ms,
    "latencyWithinLimit": elapsed_ms <= max_fixture_latency_ms,
  }


@dataclass(slots=True)
class _Totals:
  fixtures: int = 0
  schema_valid: int = 0
  assignments_complete: int = 0
  evidence_valid: int = 0
  matrix_passed: int = 0
  matrix_total: int = 0
  coverage_tp: int = 0
  coverage_fp: int = 0
  coverage_fn: int = 0
  family_tp: int = 0
  family_fp: int = 0
  family_fn: int = 0
  latency_within_limit: int = 0
  latencies: list[int] = field(default_factory=list)

  def add(self, report: dict[str, Any]) -> None:
    self.fixtures += 1
    self.schema_valid += int(bool(report["schemaDomainValid"]))
    self.assignments_complete += int(bool(report["assignmentComplete"]))
    self.evidence_valid += int(bool(report["evidenceValid"]))
    self.matrix_passed += int(report["matrixChecksPassed"])
    self.matrix_total += int(report["matrixChecksTotal"])
    self.coverage_tp += int(report["coverageTp"])
    self.coverage_fp += int(report["coverageFp"])
    self.coverage_fn += int(report["coverageFn"])
    self.family_tp += int(report["familyTp"])
    self.family_fp += int(report["familyFp"])
    self.family_fn += int(report["familyFn"])
    self.latency_within_limit += int(bool(report["latencyWithinLimit"]))
    self.latencies.append(int(report["latencyMilliseconds"]))

  def report(
    self,
    calls: list[ProviderCall],
    *,
    mode: Literal["recorded", "live"],
    max_total_tokens: int,
  ) -> dict[str, Any]:
    telemetry = [call.telemetry for call in calls if call.telemetry is not None]
    repair_calls = sum(call.repair for call in calls)
    first_pass_branches = {
      (call.question_id, call.branch) for call in calls if not call.repair and call.outcome == "valid_schema"
    }
    repaired_branches = {(call.question_id, call.branch) for call in calls if call.repair}
    total_tokens = sum(item.total_tokens for item in telemetry)
    token_usage_reported = len(telemetry) == len(calls) and (
      mode == "recorded" or all(item.total_tokens > 0 for item in telemetry)
    )
    return {
      "schemaDomainSuccessRate": _ratio(self.schema_valid, self.fixtures),
      "assignmentCompletenessRate": _ratio(self.assignments_complete, self.fixtures),
      "evidenceLiteralIntegrityRate": _ratio(self.evidence_valid, self.fixtures),
      "familyUnitMatrixIntegrityRate": _ratio(self.matrix_passed, self.matrix_total),
      "coveragePrecision": _ratio(self.coverage_tp, self.coverage_tp + self.coverage_fp),
      "coverageRecall": _ratio(self.coverage_tp, self.coverage_tp + self.coverage_fn),
      "familyPairwiseF1": _f1(self.family_tp, self.family_fp, self.family_fn),
      "latencyWithinLimitRate": _ratio(self.latency_within_limit, self.fixtures),
      "tokenUsageWithinLimit": float(token_usage_reported and total_tokens <= max_total_tokens),
      "firstPassValidBranchRate": _ratio(len(first_pass_branches - repaired_branches), self.fixtures * 2),
      "repairCallCount": repair_calls,
      "latencyMilliseconds": {
        "p50": _percentile(self.latencies, 0.50),
        "p95": _percentile(self.latencies, 0.95),
        "maximum": max(self.latencies, default=0),
        "total": sum(self.latencies),
      },
      "tokenUsage": {
        "input": sum(item.input_tokens for item in telemetry),
        "output": sum(item.output_tokens for item in telemetry),
        "reasoning": sum(item.reasoning_tokens for item in telemetry),
        "total": total_tokens,
        "maximumAllowed": max_total_tokens,
        "reportedForEveryCall": token_usage_reported,
      },
    }


def _matrix_checks(
  fixture: EvaluationFixture,
  assignments: dict[UUID, Any],
) -> tuple[int, int, list[dict[str, object]]]:
  checks: list[tuple[str, tuple[UUID, ...], bool]] = []
  for relationship in fixture.relationships.get("sameFamily", []):
    ids = tuple(UUID(value) for value in relationship["participantIds"])
    family_ids = {assignments[value].family_id for value in ids}
    checks.append(("sameFamily", ids, None not in family_ids and len(family_ids) == 1))
  for relationship in fixture.relationships.get("differentFamily", []):
    ids = tuple(UUID(value) for value in relationship["participantIds"])
    family_ids = {assignments[value].family_id for value in ids}
    checks.append(("differentFamily", ids, None not in family_ids and len(family_ids) == len(ids)))
  for value in fixture.relationships.get("nullFamilyWithCoverage", []):
    participant_id = UUID(value)
    assignment = assignments[participant_id]
    checks.append(
      (
        "nullFamilyWithCoverage",
        (participant_id,),
        assignment.family_id is None and bool(assignment.covered_unit_ids),
      )
    )
  for value in fixture.relationships.get("emptyAnswerParticipantIds", []):
    participant_id = UUID(value)
    assignment = assignments[participant_id]
    checks.append(
      (
        "emptyAnswer",
        (participant_id,),
        assignment.family_id is None and not assignment.covered_unit_ids,
      )
    )
  for relationship in fixture.relationships.get("validDisagreement", []):
    ids = tuple(UUID(value) for value in relationship["participantIds"])
    family_ids = {assignments[value].family_id for value in ids}
    checks.append(("validDisagreement", ids, None not in family_ids and len(family_ids) > 1))
  if not checks:
    return 1, 1, []
  failed: list[dict[str, object]] = [
    {"kind": kind, "participantIds": [str(value) for value in participant_ids]}
    for kind, participant_ids, passed in checks
    if not passed
  ]
  return sum(passed for _kind, _ids, passed in checks), len(checks), failed


def _evidence_is_valid(
  output: CoverageClassificationOutput | None,
  answer_by_participant: dict[str, str],
) -> bool:
  if output is None:
    return False
  for assignment in output.assignments:
    answer = answer_by_participant.get(assignment.participant_id)
    if answer is None:
      return False
    evidence_ids = [item.unit_id for item in assignment.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
      return False
    if set(evidence_ids) != set(assignment.covered_unit_ids):
      return False
    normalized_answer = _normalize_line_endings(answer)
    for evidence in assignment.evidence:
      if not 1 <= len(evidence.quotes) <= 2:
        return False
      if any(_normalize_line_endings(quote) not in normalized_answer for quote in evidence.quotes):
        return False
  return True


def _family_pair_counts(
  expected: dict[UUID, int | None],
  predicted: dict[UUID, str | None],
) -> tuple[int, int, int]:
  participants = sorted(expected, key=str)
  true_positive = false_positive = false_negative = 0
  for left_index, left in enumerate(participants):
    for right in participants[left_index + 1 :]:
      expected_same = expected[left] is not None and expected[left] == expected[right]
      predicted_same = predicted[left] is not None and predicted[left] == predicted[right]
      true_positive += int(expected_same and predicted_same)
      false_positive += int(not expected_same and predicted_same)
      false_negative += int(expected_same and not predicted_same)
  return true_positive, false_positive, false_negative


def _family_pair_mismatches(
  expected: dict[UUID, int | None],
  predicted: dict[UUID, str | None],
) -> tuple[list[list[str]], list[list[str]]]:
  false_positive_pairs: list[list[str]] = []
  false_negative_pairs: list[list[str]] = []
  participants = sorted(expected, key=str)
  for left_index, left in enumerate(participants):
    for right in participants[left_index + 1 :]:
      expected_same = expected[left] is not None and expected[left] == expected[right]
      predicted_same = predicted[left] is not None and predicted[left] == predicted[right]
      pair = [str(left), str(right)]
      if not expected_same and predicted_same:
        false_positive_pairs.append(pair)
      elif expected_same and not predicted_same:
        false_negative_pairs.append(pair)
  return false_positive_pairs, false_negative_pairs


def _expected_family_positive_pairs(expected: dict[UUID, int | None]) -> int:
  # With an all-null prediction, expected positives appear as false negatives.
  _tp, _fp, false_negative = _family_pair_counts(
    expected,
    {participant_id: None for participant_id in expected},
  )
  return false_negative


def _gate_report(aggregate: dict[str, Any]) -> list[dict[str, Any]]:
  return [
    {
      "name": name,
      "minimum": minimum,
      "value": aggregate[name],
      "status": "pass" if aggregate[name] >= minimum else "fail",
    }
    for name, minimum in QUALITY_GATES.items()
  ]


def _readiness_claim(mode: Literal["recorded", "live"], *, gates_passed: bool) -> str:
  if mode == "recorded":
    return (
      "Recorded mode validates deterministic contracts only; run live mode and adjudicate "
      "evidence support before making a model-readiness claim."
    )
  if gates_passed:
    return "Automated fixture gates passed; human evidence-support adjudication remains required."
  return (
    "Automated fixture gates failed; do not make a model-readiness claim until the failures "
    "are corrected and the live evaluation passes."
  )


def _ratio(numerator: int, denominator: int) -> float:
  return 1.0 if denominator == 0 else round(numerator / denominator, 6)


def _f1(true_positive: int, false_positive: int, false_negative: int) -> float:
  denominator = 2 * true_positive + false_positive + false_negative
  return 1.0 if denominator == 0 else round((2 * true_positive) / denominator, 6)


def _percentile(values: list[int], percentile: float) -> int:
  if not values:
    return 0
  ordered = sorted(values)
  index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
  return ordered[index]


def _normalize_line_endings(value: str) -> str:
  return value.replace("\r\n", "\n").replace("\r", "\n")


if __name__ == "__main__":
  raise SystemExit(main())
