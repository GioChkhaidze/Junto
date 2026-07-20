"""Run Junto's network-free synthetic classroom challenge and scale checks.

This suite does not call a model and does not score semantic accuracy. It inventories the
separately adjudicated gold fixtures, then checks that diverse adversarial answers and twenty
synthetic identities remain valid across representative classroom payload sizes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID, uuid5

from junto.engine.compiler import CompilerLimits
from junto.services.personas import SyntheticPersona, synthetic_personas

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_GOLD_DIRECTORY = BACKEND_DIRECTORY / "tests" / "fixtures" / "semantic"
DEFAULT_CHALLENGE_FIXTURE = BACKEND_DIRECTORY / "tests" / "fixtures" / "stress" / "synthetic_challenges.json"

_PARTICIPANT_NAMESPACE = UUID("50c42adf-dd52-5e9c-a982-c18428a7cbb0")
_REQUIRED_CASE_TAGS = frozenset(
  {
    "negation",
    "paraphrase",
    "null_family_candidate",
    "coverage_fragment",
    "prompt_injection",
    "multilingual",
    "long_answer",
    "plausible_error",
    "empty_answer",
    "duplicate_answer",
  }
)
_SCALE_CASES = (
  ("small-room", 5, 1, 41),
  ("typical-room", 10, 4, 43),
  ("full-demo-room", 20, 8, 47),
  ("alternate-full-room", 20, 8, 53),
)


@dataclass(frozen=True, slots=True)
class AnswerVariant:
  case_id: str
  tags: tuple[str, ...]
  text: str


@dataclass(frozen=True, slots=True)
class ChallengeScenario:
  scenario_id: str
  subject: str
  question_type: str
  question_prompt: str
  variants: tuple[AnswerVariant, ...]


class _Args(Protocol):
  gold_fixtures: Path
  challenge_fixture: Path
  output: Path | None


def main() -> int:
  args = cast(_Args, _parser().parse_args())
  try:
    report = build_report(
      gold_directory=args.gold_fixtures,
      challenge_fixture=args.challenge_fixture,
    )
  except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
    print(f"Offline stress evaluation could not start: {error}", file=sys.stderr)
    return 2

  serialized = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
  if args.output is not None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
  print(serialized)
  return 0 if report["overallStatus"] == "pass" else 1


def _parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--gold-fixtures", type=Path, default=DEFAULT_GOLD_DIRECTORY)
  parser.add_argument("--challenge-fixture", type=Path, default=DEFAULT_CHALLENGE_FIXTURE)
  parser.add_argument("--output", type=Path)
  return parser


def build_report(*, gold_directory: Path, challenge_fixture: Path) -> dict[str, Any]:
  scenarios = _load_scenarios(challenge_fixture)
  personas = synthetic_personas(20)
  limits = CompilerLimits()
  gold = _gold_inventory(gold_directory)
  challenge = _challenge_report(scenarios, personas, limits)
  scale = _scale_report(scenarios, limits)
  checks = [
    _check("at-least-ten-subjects", challenge["subjectCount"] >= 10),
    _check("twenty-distinct-personas", challenge["personaCount"] == 20),
    _check("required-adversarial-cases", not challenge["missingRequiredCaseTags"]),
    _check("answer-character-limit", challenge["answersOverLimit"] == 0),
    _check("scale-payload-limit", scale["payloadsOverCompilerLimit"] == 0),
    _check("compiler-question-limit-exercised", scale["maximumQuestionCount"] == 8),
    _check("zero-provider-calls", challenge["providerCalls"] == 0),
  ]
  passed = all(item["status"] == "pass" for item in checks)
  return {
    "schemaVersion": "1",
    "generatedAt": datetime.now(UTC).isoformat(),
    "mode": "offline",
    "suiteId": "synthetic-classroom-stress-v1",
    "goldSuite": gold,
    "challengeSuite": challenge,
    "scaleSuite": scale,
    "checks": checks,
    "overallStatus": "pass" if passed else "fail",
    "semanticAccuracyClaim": "none",
    "interpretation": (
      "A pass establishes fixture diversity and structural safety at the tested sizes. "
      "It does not establish model classification accuracy or learning impact."
    ),
  }


def _load_scenarios(path: Path) -> tuple[ChallengeScenario, ...]:
  payload = json.loads(path.read_text(encoding="utf-8"))
  if payload.get("schemaVersion") != 1 or not isinstance(payload.get("scenarios"), list):
    raise ValueError("Challenge fixture must use schemaVersion 1 and contain scenarios.")
  scenarios: list[ChallengeScenario] = []
  seen_scenario_ids: set[str] = set()
  for raw_scenario in payload["scenarios"]:
    scenario_id = _required_text(raw_scenario, "scenarioId")
    if scenario_id in seen_scenario_ids:
      raise ValueError(f"Duplicate challenge scenario ID: {scenario_id}")
    seen_scenario_ids.add(scenario_id)
    variants: list[AnswerVariant] = []
    seen_case_ids: set[str] = set()
    for raw_variant in raw_scenario.get("variants", []):
      case_id = _required_text(raw_variant, "caseId")
      if case_id in seen_case_ids:
        raise ValueError(f"Duplicate case ID in {scenario_id}: {case_id}")
      seen_case_ids.add(case_id)
      tags = tuple(_required_text_value(item, "case tag") for item in raw_variant["tags"])
      text = raw_variant.get("text")
      if not isinstance(text, str):
        raise ValueError(f"Answer text in {scenario_id}/{case_id} must be a string.")
      repeat = raw_variant.get("repeat", 1)
      if not isinstance(repeat, int) or not 1 <= repeat <= 8:
        raise ValueError(f"Repeat in {scenario_id}/{case_id} must be between 1 and 8.")
      variants.append(AnswerVariant(case_id=case_id, tags=tags, text=" ".join([text] * repeat)))
    if not variants:
      raise ValueError(f"Challenge scenario {scenario_id} has no variants.")
    scenarios.append(
      ChallengeScenario(
        scenario_id=scenario_id,
        subject=_required_text(raw_scenario, "subject"),
        question_type=_required_text(raw_scenario, "questionType"),
        question_prompt=_required_text(raw_scenario, "questionPrompt"),
        variants=tuple(variants),
      )
    )
  if not scenarios:
    raise ValueError("Challenge fixture has no scenarios.")
  return tuple(scenarios)


def _gold_inventory(directory: Path) -> dict[str, Any]:
  paths = tuple(sorted(directory.glob("*.json")))
  if not paths:
    raise ValueError("No gold semantic fixtures were found.")
  subjects: set[str] = set()
  participant_count = 0
  nonempty_answer_count = 0
  relationship_counts: Counter[str] = Counter()
  for path in paths:
    payload = json.loads(path.read_text(encoding="utf-8"))
    subjects.add(_required_text(payload, "subject"))
    participants = payload.get("participants")
    if not isinstance(participants, list):
      raise ValueError(f"Gold fixture {path.name} has invalid participants.")
    participant_count += len(participants)
    nonempty_answer_count += sum(bool(item.get("answer", "").strip()) for item in participants)
    relationships = payload.get("expectedRelationships")
    if not isinstance(relationships, dict):
      raise ValueError(f"Gold fixture {path.name} has invalid relationships.")
    for key, value in relationships.items():
      if isinstance(value, list):
        relationship_counts[key] += len(value)
  return {
    "fixtureCount": len(paths),
    "subjects": sorted(subjects),
    "participantCount": participant_count,
    "nonemptyAnswerCount": nonempty_answer_count,
    "relationshipCaseCounts": dict(sorted(relationship_counts.items())),
    "labelSource": "separately reviewed fixture labels",
    "evaluatedByThisSuite": False,
    "note": "Use evaluate_semantic.py for gold accuracy evaluation.",
  }


def _challenge_report(
  scenarios: tuple[ChallengeScenario, ...],
  personas: tuple[SyntheticPersona, ...],
  limits: CompilerLimits,
) -> dict[str, Any]:
  tag_counts: Counter[str] = Counter()
  answer_lengths: list[int] = []
  answer_count = 0
  nonempty_answer_count = 0
  unique_answers: set[str] = set()
  for scenario_index, scenario in enumerate(scenarios):
    for persona_index, _persona in enumerate(personas):
      variant = scenario.variants[(persona_index + scenario_index) % len(scenario.variants)]
      tag_counts.update(variant.tags)
      answer_count += 1
      nonempty_answer_count += int(bool(variant.text.strip()))
      answer_lengths.append(len(variant.text))
      unique_answers.add(variant.text)
  present_tags = set(tag_counts)
  knowledge_counts = Counter(persona.knowledge_level for persona in personas)
  error_counts = Counter(persona.error_tendency for persona in personas)
  participation_counts = Counter(persona.participation for persona in personas)
  return {
    "scenarioCount": len(scenarios),
    "subjectCount": len({scenario.subject for scenario in scenarios}),
    "subjects": sorted({scenario.subject for scenario in scenarios}),
    "questionTypes": sorted({scenario.question_type for scenario in scenarios}),
    "personaCount": len(personas),
    "uniquePersonaIdCount": len({persona.id for persona in personas}),
    "uniqueDisplayNameCount": len({persona.display_name for persona in personas}),
    "knowledgeLevelCounts": dict(sorted(knowledge_counts.items())),
    "errorTendencyCounts": dict(sorted(error_counts.items())),
    "participationStyleCounts": dict(sorted(participation_counts.items())),
    "answerCount": answer_count,
    "nonemptyAnswerCount": nonempty_answer_count,
    "uniqueAnswerTemplateCount": len(unique_answers),
    "maximumAnswerCharacters": max(answer_lengths, default=0),
    "answersOverLimit": sum(length > limits.max_answer_characters for length in answer_lengths),
    "caseTagCounts": dict(sorted(tag_counts.items())),
    "missingRequiredCaseTags": sorted(_REQUIRED_CASE_TAGS - present_tags),
    "providerCalls": 0,
    "scoreType": "structural-only",
  }


def _scale_report(scenarios: tuple[ChallengeScenario, ...], limits: CompilerLimits) -> dict[str, Any]:
  cases: list[dict[str, Any]] = []
  total_answer_slots = 0
  for case_id, participant_count, question_count, seed in _SCALE_CASES:
    personas = synthetic_personas(participant_count, seed=seed)
    selected_scenarios = scenarios[:question_count]
    payload = _classroom_payload(selected_scenarios, personas)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    input_bytes = len(serialized.encode("utf-8"))
    answer_slots = participant_count * question_count
    total_answer_slots += answer_slots
    cases.append(
      {
        "caseId": case_id,
        "participantCount": participant_count,
        "questionCount": question_count,
        "answerSlots": answer_slots,
        "utf8InputBytes": input_bytes,
        "withinCompilerInputLimit": input_bytes <= limits.max_provider_input_characters,
        "uniqueParticipantIds": len({item["participantId"] for item in payload["participants"]}),
      }
    )
  return {
    "caseCount": len(cases),
    "cases": cases,
    "totalAnswerSlots": total_answer_slots,
    "maximumParticipantCount": max(item["participantCount"] for item in cases),
    "maximumQuestionCount": max(item["questionCount"] for item in cases),
    "maximumUtf8InputBytes": max(item["utf8InputBytes"] for item in cases),
    "compilerInputLimitBytes": limits.max_provider_input_characters,
    "payloadsOverCompilerLimit": sum(not item["withinCompilerInputLimit"] for item in cases),
    "providerCalls": 0,
  }


def _classroom_payload(
  scenarios: tuple[ChallengeScenario, ...], personas: tuple[SyntheticPersona, ...]
) -> dict[str, Any]:
  participants = [
    {
      "participantId": str(uuid5(_PARTICIPANT_NAMESPACE, persona.id)),
      "personaId": persona.id,
    }
    for persona in personas
  ]
  questions: list[dict[str, Any]] = []
  for scenario_index, scenario in enumerate(scenarios):
    answers = []
    for persona_index, participant in enumerate(participants):
      variant = scenario.variants[(persona_index + scenario_index) % len(scenario.variants)]
      answers.append({"participantId": participant["participantId"], "text": variant.text})
    questions.append(
      {
        "scenarioId": scenario.scenario_id,
        "prompt": scenario.question_prompt,
        "answers": answers,
      }
    )
  return {"participants": participants, "questions": questions}


def _required_text(payload: dict[str, Any], key: str) -> str:
  return _required_text_value(payload.get(key), key)


def _required_text_value(value: object, label: str) -> str:
  if not isinstance(value, str) or not value.strip():
    raise ValueError(f"{label} must be a non-empty string.")
  return value.strip()


def _check(check_id: str, passed: bool) -> dict[str, str]:
  return {"id": check_id, "status": "pass" if passed else "fail"}


if __name__ == "__main__":
  raise SystemExit(main())
