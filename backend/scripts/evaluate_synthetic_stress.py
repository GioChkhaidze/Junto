"""Run Junto's network-free synthetic classroom challenge and scale checks.

This suite does not call a model and does not score semantic accuracy. It inventories the
separately adjudicated gold fixtures, then checks that diverse adversarial answers and twenty
synthetic identities remain valid in representative offline classroom assemblies.
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
_MAX_ACTIVITY_TITLE_CHARACTERS = 120
_MAX_QUESTION_CHARACTERS = 4_000
_MAX_SOURCE_CONTEXT_CHARACTERS = 8_000
_MAX_COVERAGE_ID_CHARACTERS = 80
_MAX_COVERAGE_TEXT_CHARACTERS = 300
_ANSWER_PREFIXES = ("", "My answer: ", "In short: ", "My reasoning:\n", "My view: ")
_ANSWER_SUFFIXES = (
  "",
  "\nThat is my conclusion.",
  "\nThat is the distinction I would make.",
  "\nThis is how I understand it.",
)
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
class CoverageUnitSpec:
  id: str
  text: str


@dataclass(frozen=True, slots=True)
class ChallengeScenario:
  scenario_id: str
  activity_title: str
  subject: str
  question_type: str
  question_prompt: str
  room_source_context: str | None
  coverage_units: tuple[CoverageUnitSpec, ...]
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
  activities = _activity_report(scenarios)
  challenge = _challenge_report(scenarios, personas, limits)
  scale = _scale_report(scenarios, max_answer_characters=limits.max_answer_characters)
  checks = [
    _check("at-least-ten-subjects", challenge["subjectCount"] >= 10),
    _check(
      "independent-one-question-activities",
      activities["oneQuestionActivityCount"] == len(scenarios),
    ),
    _check("coverage-units-per-activity", activities["coverageUnitCountViolations"] == 0),
    _check(
      "unique-bounded-activity-fields",
      activities["fieldViolations"] == []
      and activities["uniqueActivityTitleCount"] == len(scenarios)
      and activities["uniqueQuestionPromptCount"] == len(scenarios)
      and activities["uniqueCoverageUnitIdCount"] == activities["coverageUnitCount"]
      and activities["uniqueCoverageUnitTextCount"] == activities["coverageUnitCount"],
    ),
    _check("twenty-distinct-personas", challenge["personaCount"] == 20),
    _check("required-adversarial-cases", not challenge["missingRequiredCaseTags"]),
    _check("answer-character-limit", challenge["answersOverLimit"] == 0),
    _check("verbatim-source-text-preserved", scale["sourceTextPreservationViolations"] == 0),
    _check("source-tags-preserved", scale["tagPreservationViolations"] == 0),
    _check(
      "assembled-payload-sizes-recorded",
      scale["caseCount"] == len(_SCALE_CASES) and scale["maximumAssembledPayloadUtf8Bytes"] > 0,
    ),
    _check("eight-question-scale-case-included", scale["maximumQuestionCount"] == 8),
  ]
  passed = all(item["status"] == "pass" for item in checks)
  return {
    "schemaVersion": "1",
    "generatedAt": datetime.now(UTC).isoformat(),
    "mode": "offline",
    "suiteId": "synthetic-classroom-stress-v1",
    "goldSuite": gold,
    "activitySuite": activities,
    "challengeSuite": challenge,
    "scaleSuite": scale,
    "checks": checks,
    "overallStatus": "pass" if passed else "fail",
    "semanticAccuracyClaim": "none",
    "interpretation": (
      "A pass establishes fixture diversity and assembly invariants at the tested sizes. "
      "It does not establish compiler or provider capacity, model classification accuracy, or learning impact."
    ),
  }


def _load_scenarios(path: Path) -> tuple[ChallengeScenario, ...]:
  payload = json.loads(path.read_text(encoding="utf-8"))
  if payload.get("schemaVersion") != 1 or not isinstance(payload.get("scenarios"), list):
    raise ValueError("Challenge fixture must use schemaVersion 1 and contain scenarios.")
  if payload.get("semanticAccuracyClaim") != "none":
    raise ValueError("Challenge fixture must declare semanticAccuracyClaim as none.")
  scenarios: list[ChallengeScenario] = []
  seen_scenario_ids: set[str] = set()
  seen_activity_titles: set[str] = set()
  seen_question_prompts: set[str] = set()
  seen_unit_ids: set[str] = set()
  seen_unit_texts: set[str] = set()
  for raw_scenario in payload["scenarios"]:
    scenario_id = _required_text(raw_scenario, "scenarioId")
    if scenario_id in seen_scenario_ids:
      raise ValueError(f"Duplicate challenge scenario ID: {scenario_id}")
    seen_scenario_ids.add(scenario_id)
    activity_title = _bounded_text(raw_scenario, "activityTitle", _MAX_ACTIVITY_TITLE_CHARACTERS)
    question_prompt = _bounded_text(raw_scenario, "questionPrompt", _MAX_QUESTION_CHARACTERS)
    _require_unique(activity_title, seen_activity_titles, "activity title")
    _require_unique(question_prompt, seen_question_prompts, "question prompt")
    room_source_context = _optional_bounded_text(
      raw_scenario,
      "roomSourceContext",
      _MAX_SOURCE_CONTEXT_CHARACTERS,
    )
    raw_units = raw_scenario.get("coverageUnits")
    if not isinstance(raw_units, list) or not 3 <= len(raw_units) <= 6:
      raise ValueError(f"Challenge scenario {scenario_id} must have 3 to 6 coverage units.")
    coverage_units: list[CoverageUnitSpec] = []
    for raw_unit in raw_units:
      if not isinstance(raw_unit, dict):
        raise ValueError(f"Coverage units in {scenario_id} must be objects.")
      unit_id = _bounded_text(raw_unit, "id", _MAX_COVERAGE_ID_CHARACTERS)
      unit_text = _bounded_text(raw_unit, "text", _MAX_COVERAGE_TEXT_CHARACTERS)
      _require_unique(unit_id, seen_unit_ids, "coverage unit ID")
      _require_unique(unit_text, seen_unit_texts, "coverage unit text")
      coverage_units.append(CoverageUnitSpec(id=unit_id, text=unit_text))
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
        activity_title=activity_title,
        subject=_required_text(raw_scenario, "subject"),
        question_type=_required_text(raw_scenario, "questionType"),
        question_prompt=question_prompt,
        room_source_context=room_source_context,
        coverage_units=tuple(coverage_units),
        variants=tuple(variants),
      )
    )
  if not scenarios:
    raise ValueError("Challenge fixture has no scenarios.")
  return tuple(scenarios)


def activity_payloads(challenge_fixture: Path = DEFAULT_CHALLENGE_FIXTURE) -> tuple[dict[str, Any], ...]:
  return tuple(_activity_payload(scenario) for scenario in _load_scenarios(challenge_fixture))


def _activity_payload(scenario: ChallengeScenario) -> dict[str, Any]:
  return {
    "scenarioId": scenario.scenario_id,
    "subject": scenario.subject,
    "questionType": scenario.question_type,
    "roomSourceContext": scenario.room_source_context,
    "room": {
      "title": scenario.activity_title,
      "policy": "teach",
      "groupSize": {"minimum": 3, "preferred": 4, "maximum": 5},
      "durationMinutes": 20,
    },
    "questions": [
      {
        "prompt": scenario.question_prompt,
        "coverageUnits": [{"text": unit.text} for unit in scenario.coverage_units],
      }
    ],
  }


def _activity_report(scenarios: tuple[ChallengeScenario, ...]) -> dict[str, Any]:
  payloads = tuple(_activity_payload(scenario) for scenario in scenarios)
  unit_counts = [len(scenario.coverage_units) for scenario in scenarios]
  coverage_units = [unit for scenario in scenarios for unit in scenario.coverage_units]
  field_violations = _activity_field_violations(scenarios)
  return {
    "activityCount": len(payloads),
    "oneQuestionActivityCount": sum(len(payload["questions"]) == 1 for payload in payloads),
    "uniqueActivityTitleCount": len({scenario.activity_title for scenario in scenarios}),
    "uniqueQuestionPromptCount": len({scenario.question_prompt for scenario in scenarios}),
    "coverageUnitCount": len(coverage_units),
    "minimumCoverageUnitsPerActivity": min(unit_counts, default=0),
    "maximumCoverageUnitsPerActivity": max(unit_counts, default=0),
    "coverageUnitCountViolations": sum(not 3 <= count <= 6 for count in unit_counts),
    "uniqueCoverageUnitIdCount": len({unit.id for unit in coverage_units}),
    "uniqueCoverageUnitTextCount": len({unit.text for unit in coverage_units}),
    "roomSourceContextCount": sum(scenario.room_source_context is not None for scenario in scenarios),
    "fieldViolations": field_violations,
    "semanticAccuracyClaim": "none",
  }


def _activity_field_violations(scenarios: tuple[ChallengeScenario, ...]) -> list[str]:
  violations: list[str] = []
  for scenario in scenarios:
    fields = (
      ("activityTitle", scenario.activity_title, _MAX_ACTIVITY_TITLE_CHARACTERS),
      ("questionPrompt", scenario.question_prompt, _MAX_QUESTION_CHARACTERS),
      ("roomSourceContext", scenario.room_source_context or "", _MAX_SOURCE_CONTEXT_CHARACTERS),
    )
    for field_name, value, maximum in fields:
      if len(value) > maximum:
        violations.append(f"{scenario.scenario_id}/{field_name}")
    for unit in scenario.coverage_units:
      if len(unit.id) > _MAX_COVERAGE_ID_CHARACTERS:
        violations.append(f"{scenario.scenario_id}/{unit.id}/id")
      if len(unit.text) > _MAX_COVERAGE_TEXT_CHARACTERS:
        violations.append(f"{scenario.scenario_id}/{unit.id}/text")
  return violations


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
  for scenario_index, scenario in enumerate(scenarios):
    for persona_index, _persona in enumerate(personas):
      variant = scenario.variants[(persona_index + scenario_index) % len(scenario.variants)]
      rendered = _render_answer(
        variant.text,
        persona_index,
        scenario_index,
        limits.max_answer_characters,
      )
      tag_counts.update(variant.tags)
      answer_count += 1
      nonempty_answer_count += int(bool(rendered.strip()))
      answer_lengths.append(len(rendered))
  present_tags = set(tag_counts)
  knowledge_counts = Counter(persona.knowledge_level for persona in personas)
  error_counts = Counter(persona.error_tendency for persona in personas)
  participation_counts = Counter(persona.participation for persona in personas)
  source_template_count = sum(len(scenario.variants) for scenario in scenarios)
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
    "sourceAnswerTemplateCount": source_template_count,
    "sourceAnswerDuplicationRatio": round(1 - source_template_count / answer_count, 4),
    "diversityMeasure": "source answer templates; deterministic persona wrappers are excluded",
    "maximumAnswerCharacters": max(answer_lengths, default=0),
    "answersOverLimit": sum(length > limits.max_answer_characters for length in answer_lengths),
    "caseTagCounts": dict(sorted(tag_counts.items())),
    "missingRequiredCaseTags": sorted(_REQUIRED_CASE_TAGS - present_tags),
    "semanticAccuracyClaim": "none",
  }


def _scale_report(
  scenarios: tuple[ChallengeScenario, ...],
  *,
  max_answer_characters: int,
) -> dict[str, Any]:
  cases: list[dict[str, Any]] = []
  total_answer_slots = 0
  source_text_violations = 0
  tag_violations = 0
  for case_id, participant_count, question_count, seed in _SCALE_CASES:
    personas = synthetic_personas(participant_count, seed=seed)
    selected_scenarios = scenarios[:question_count]
    payload = _assembled_stress_payload(
      selected_scenarios,
      personas,
      max_answer_characters=max_answer_characters,
    )
    case_source_violations, case_tag_violations = _preservation_violations(payload, selected_scenarios)
    source_text_violations += case_source_violations
    tag_violations += case_tag_violations
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
        "assembledPayloadUtf8Bytes": input_bytes,
        "uniqueParticipantIds": len({item["participantId"] for item in payload["participants"]}),
        "sourceTextPreservationViolations": case_source_violations,
        "tagPreservationViolations": case_tag_violations,
      }
    )
  return {
    "caseCount": len(cases),
    "cases": cases,
    "totalAnswerSlots": total_answer_slots,
    "maximumParticipantCount": max(item["participantCount"] for item in cases),
    "maximumQuestionCount": max(item["questionCount"] for item in cases),
    "maximumAssembledPayloadUtf8Bytes": max(item["assembledPayloadUtf8Bytes"] for item in cases),
    "measurementScope": "offline assembled stress payload; not a compiler or provider request",
    "sourceTextPreservationViolations": source_text_violations,
    "tagPreservationViolations": tag_violations,
    "semanticAccuracyClaim": "none",
  }


def _assembled_stress_payload(
  scenarios: tuple[ChallengeScenario, ...],
  personas: tuple[SyntheticPersona, ...],
  *,
  max_answer_characters: int,
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
      answers.append(
        {
          "participantId": participant["participantId"],
          "caseId": variant.case_id,
          "tags": list(variant.tags),
          "text": _render_answer(
            variant.text,
            persona_index,
            scenario_index,
            max_answer_characters,
          ),
        }
      )
    questions.append(
      {
        "scenarioId": scenario.scenario_id,
        "prompt": scenario.question_prompt,
        "answers": answers,
      }
    )
  return {"participants": participants, "questions": questions}


def _render_answer(
  source_text: str,
  persona_index: int,
  scenario_index: int,
  max_answer_characters: int,
) -> str:
  if not source_text:
    return ""
  wrapper_index = (persona_index + scenario_index) % (len(_ANSWER_PREFIXES) * len(_ANSWER_SUFFIXES))
  prefix = _ANSWER_PREFIXES[wrapper_index % len(_ANSWER_PREFIXES)]
  suffix = _ANSWER_SUFFIXES[wrapper_index // len(_ANSWER_PREFIXES)]
  if len(prefix) + len(source_text) + len(suffix) > max_answer_characters:
    suffix = ""
  if len(prefix) + len(source_text) > max_answer_characters:
    prefix = ""
  return f"{prefix}{source_text}{suffix}"


def _preservation_violations(
  payload: dict[str, Any],
  scenarios: tuple[ChallengeScenario, ...],
) -> tuple[int, int]:
  variants = {
    (scenario.scenario_id, variant.case_id): variant for scenario in scenarios for variant in scenario.variants
  }
  source_text_violations = 0
  tag_violations = 0
  for question in payload["questions"]:
    for answer in question["answers"]:
      variant = variants[(question["scenarioId"], answer["caseId"])]
      source_text_violations += int(variant.text not in answer["text"] if variant.text else answer["text"] != "")
      tag_violations += int(answer["tags"] != list(variant.tags))
  return source_text_violations, tag_violations


def _required_text(payload: dict[str, Any], key: str) -> str:
  return _required_text_value(payload.get(key), key)


def _bounded_text(payload: dict[str, Any], key: str, maximum: int) -> str:
  value = _required_text(payload, key)
  if len(value) > maximum:
    raise ValueError(f"{key} must contain at most {maximum} characters.")
  return value


def _optional_bounded_text(payload: dict[str, Any], key: str, maximum: int) -> str | None:
  value = payload.get(key)
  if value is None:
    return None
  normalized = _required_text_value(value, key)
  if len(normalized) > maximum:
    raise ValueError(f"{key} must contain at most {maximum} characters.")
  return normalized


def _require_unique(value: str, seen: set[str], label: str) -> None:
  normalized = value.casefold()
  if normalized in seen:
    raise ValueError(f"Duplicate {label}: {value}")
  seen.add(normalized)


def _required_text_value(value: object, label: str) -> str:
  if not isinstance(value, str) or not value.strip():
    raise ValueError(f"{label} must be a non-empty string.")
  return value.strip()


def _check(check_id: str, passed: bool) -> dict[str, str]:
  return {"id": check_id, "status": "pass" if passed else "fail"}


if __name__ == "__main__":
  raise SystemExit(main())
