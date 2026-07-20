from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import combinations
from math import lcm
from random import Random
from uuid import UUID

import pytest

from junto.domain.entities import GroupingPolicy, GroupSize
from junto.engine.models import (
  CompleteCoverageStatus,
  GroupingArtifact,
  QuestionSemanticArtifact,
  ResponseFamily,
  SemanticArtifact,
  SemanticAssignment,
  SolverStatus,
)
from junto.engine.optimizer import (
  CoverageFirstOptimizer,
  OptimizerInputError,
  select_balanced_capacities,
)


def _participants(count: int) -> tuple[UUID, ...]:
  return tuple(UUID(int=index) for index in range(1, count + 1))


def _question(
  *,
  number: int,
  participant_ids: Sequence[UUID],
  unit_ids: Sequence[str],
  coverage: Sequence[Iterable[str]],
  family_numbers: Sequence[int | None] | None = None,
) -> QuestionSemanticArtifact:
  family_numbers = family_numbers or [None] * len(participant_ids)
  used_family_numbers = sorted({value for value in family_numbers if value is not None})
  return QuestionSemanticArtifact(
    question_id=UUID(int=10_000 + number),
    unit_ids=tuple(unit_ids),
    families=tuple(ResponseFamily(id=f"f{value}", label=f"Approach {value}") for value in used_family_numbers),
    assignments=tuple(
      SemanticAssignment(
        participant_id=participant_id,
        family_id=None if family_number is None else f"f{family_number}",
        covered_unit_ids=tuple(covered_units),
      )
      for participant_id, covered_units, family_number in zip(
        participant_ids,
        coverage,
        family_numbers,
        strict=True,
      )
    ),
  )


def _semantic(*questions: QuestionSemanticArtifact) -> SemanticArtifact:
  return SemanticArtifact(model="reviewed-fixture", questions=questions)


def _optimize(
  participant_ids: Sequence[UUID],
  semantic_artifact: SemanticArtifact,
  *,
  policy: GroupingPolicy = GroupingPolicy.TEACH,
  bounds: GroupSize | None = None,
  timeout_seconds: float = 3.0,
) -> GroupingArtifact:
  return CoverageFirstOptimizer().optimize(
    participant_ids=participant_ids,
    semantic_artifact=semantic_artifact,
    group_size=bounds or GroupSize(minimum=3, preferred=3, maximum=3),
    policy=policy,
    trigger="host",
    timeout_seconds=timeout_seconds,
  )


def _groups(result: GroupingArtifact) -> tuple[tuple[UUID, ...], ...]:
  return tuple(group.participant_ids for group in result.groups)


def _group_of(result: GroupingArtifact, participant_id: UUID) -> str:
  return next(group.id for group in result.groups if participant_id in group.participant_ids)


def _coverage_score(
  groups: Sequence[Sequence[UUID]],
  artifact: SemanticArtifact,
) -> tuple[int, int, int, int]:
  normalization = lcm(*(len(question.unit_ids) for question in artifact.questions))
  normalized_scores: list[int] = []
  full_by_group: list[int] = []
  for group in groups:
    members = set(group)
    group_full = 0
    for question in artifact.questions:
      assignments = [assignment for assignment in question.assignments if assignment.participant_id in members]
      covered_count = sum(
        any(unit_id in assignment.covered_unit_ids for assignment in assignments) for unit_id in question.unit_ids
      )
      normalized_scores.append(normalization // len(question.unit_ids) * covered_count)
      group_full += int(covered_count == len(question.unit_ids))
    full_by_group.append(group_full)
  return (
    min(normalized_scores),
    min(full_by_group),
    sum(full_by_group),
    sum(normalized_scores),
  )


def _two_equal_group_partitions(
  participant_ids: tuple[UUID, ...],
) -> tuple[tuple[tuple[UUID, ...], tuple[UUID, ...]], ...]:
  group_size = len(participant_ids) // 2
  partitions = []
  for remainder in combinations(participant_ids[1:], group_size - 1):
    first = (participant_ids[0], *remainder)
    first_set = set(first)
    second = tuple(item for item in participant_ids if item not in first_set)
    partitions.append((first, second))
  return tuple(partitions)


def _missing_units(
  result: GroupingArtifact,
  artifact: SemanticArtifact,
) -> set[tuple[str, UUID, str]]:
  missing: set[tuple[str, UUID, str]] = set()
  for group in result.groups:
    members = set(group.participant_ids)
    for question in artifact.questions:
      assignments = [item for item in question.assignments if item.participant_id in members]
      for unit_id in question.unit_ids:
        if not any(unit_id in item.covered_unit_ids for item in assignments):
          missing.add((group.id, question.question_id, unit_id))
  return missing


def test_capacity_selection_matches_preferred_average_and_larger_count_tie_break() -> None:
  assert select_balanced_capacities(
    10,
    GroupSize(minimum=3, preferred=4, maximum=5),
  ) == (4, 3, 3)
  assert select_balanced_capacities(
    12,
    GroupSize(minimum=4, preferred=5, maximum=6),
  ) == (4, 4, 4)

  with pytest.raises(OptimizerInputError):
    select_balanced_capacities(
      5,
      GroupSize(minimum=3, preferred=3, maximum=4),
    )


def test_known_feasible_fixture_has_complete_coverage_and_proven_objectives() -> None:
  participant_ids = _participants(4)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("u1",),
      coverage=(("u1",), (), ("u1",), ()),
      family_numbers=(0, 0, 0, 0),
    )
  )

  result = _optimize(
    participant_ids,
    artifact,
    bounds=GroupSize(minimum=2, preferred=2, maximum=2),
  )

  assert result.complete_coverage_status == CompleteCoverageStatus.FEASIBLE
  assert result.solver_status == SolverStatus.OPTIMAL
  assert not result.timed_out
  assert not _missing_units(result, artifact)
  assert all(outcome.proven_optimal for outcome in result.objectives)


def test_proven_infeasible_is_distinct_from_unknown_and_reports_exact_missing_unit() -> None:
  participant_ids = _participants(4)
  question = _question(
    number=1,
    participant_ids=participant_ids,
    unit_ids=("scarce",),
    coverage=(("scarce",), (), (), ()),
  )
  artifact = _semantic(question)

  result = _optimize(
    participant_ids,
    artifact,
    bounds=GroupSize(minimum=2, preferred=2, maximum=2),
  )

  assert result.complete_coverage_status == CompleteCoverageStatus.INFEASIBLE
  _assert_not_unknown(result.complete_coverage_status)
  assert len(_missing_units(result, artifact)) == 1
  missing = next(iter(_missing_units(result, artifact)))
  assert missing[1:] == (question.question_id, "scarce")


def _assert_not_unknown(status: CompleteCoverageStatus) -> None:
  assert status != CompleteCoverageStatus.UNKNOWN


def test_zero_timeout_returns_honest_capacity_fallback_without_infeasibility_claim() -> None:
  participant_ids = _participants(4)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("u1",),
      coverage=(("u1",), (), (), ()),
    )
  )

  result = _optimize(
    participant_ids,
    artifact,
    bounds=GroupSize(minimum=2, preferred=2, maximum=2),
    timeout_seconds=0,
  )

  assert result.solver_status == SolverStatus.FALLBACK
  assert result.complete_coverage_status == CompleteCoverageStatus.UNKNOWN
  assert result.timed_out
  assert result.objectives == ()
  assert _groups(result) == (
    (participant_ids[0], participant_ids[1]),
    (participant_ids[2], participant_ids[3]),
  )


def test_small_infeasible_fixture_matches_brute_force_coverage_oracle() -> None:
  participant_ids = _participants(6)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("a", "b"),
      coverage=(("a",), ("b",), ("b",), ("b",), (), ()),
      family_numbers=(0, 0, 1, 1, None, None),
    ),
    _question(
      number=2,
      participant_ids=participant_ids,
      unit_ids=("x", "y", "z"),
      coverage=(
        ("x",),
        ("y",),
        ("z",),
        (),
        ("x", "y"),
        ("z",),
      ),
      family_numbers=(0, 1, 2, None, 1, 2),
    ),
  )
  oracle = max(_coverage_score(partition, artifact) for partition in _two_equal_group_partitions(participant_ids))

  result = _optimize(participant_ids, artifact)

  assert result.complete_coverage_status == CompleteCoverageStatus.INFEASIBLE
  assert _coverage_score(_groups(result), artifact) == oracle
  assert tuple(outcome.value for outcome in result.objectives[:4]) == oracle
  assert all(outcome.proven_optimal for outcome in result.objectives[:4])


def test_explore_cannot_trade_coverage_for_a_more_diverse_but_incomplete_partition() -> None:
  participant_ids = _participants(4)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("u",),
      coverage=(("u",), ("u",), (), ()),
      family_numbers=(0, 1, None, None),
    )
  )

  result = _optimize(
    participant_ids,
    artifact,
    policy=GroupingPolicy.EXPLORE,
    bounds=GroupSize(minimum=2, preferred=2, maximum=2),
  )

  # Putting p1 and p2 together creates the only diverse group but leaves the
  # other group uncovered. Coverage priority must keep the carriers apart.
  assert _group_of(result, participant_ids[0]) != _group_of(result, participant_ids[1])
  assert result.complete_coverage_status == CompleteCoverageStatus.FEASIBLE
  assert not _missing_units(result, artifact)


def test_teach_and_explore_can_select_different_complete_partitions() -> None:
  participant_ids = _participants(6)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("u0", "u1", "u2"),
      coverage=(
        (),
        ("u0", "u1", "u2"),
        ("u0",),
        ("u0",),
        ("u1",),
        ("u1", "u2"),
      ),
      family_numbers=(2, 1, 0, None, None, 2),
    ),
    _question(
      number=2,
      participant_ids=participant_ids,
      unit_ids=("v0", "v1", "v2"),
      coverage=(
        ("v0", "v2"),
        ("v1", "v2"),
        ("v1", "v2"),
        ("v1",),
        ("v0", "v1", "v2"),
        ("v0", "v1", "v2"),
      ),
      family_numbers=(2, 2, 2, 1, 0, 0),
    ),
  )

  teach = _optimize(participant_ids, artifact, policy=GroupingPolicy.TEACH)
  explore = _optimize(participant_ids, artifact, policy=GroupingPolicy.EXPLORE)

  assert teach.complete_coverage_status == CompleteCoverageStatus.FEASIBLE
  assert explore.complete_coverage_status == CompleteCoverageStatus.FEASIBLE
  assert not _missing_units(teach, artifact)
  assert not _missing_units(explore, artifact)
  assert {frozenset(group) for group in _groups(teach)} != {frozenset(group) for group in _groups(explore)}


def test_null_family_and_missing_answer_do_not_imply_coverage() -> None:
  participant_ids = _participants(4)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("idea",),
      coverage=(("idea",), (), ("idea",), ()),
      family_numbers=(None, 0, 0, None),
    )
  )

  result = _optimize(
    participant_ids,
    artifact,
    policy=GroupingPolicy.EXPLORE,
    bounds=GroupSize(minimum=2, preferred=2, maximum=2),
  )

  assert _group_of(result, participant_ids[0]) != _group_of(result, participant_ids[2])
  assert not _missing_units(result, artifact)


def test_repeated_runs_serialize_the_same_partition_and_objectives() -> None:
  participant_ids = _participants(6)
  artifact = _semantic(
    _question(
      number=1,
      participant_ids=participant_ids,
      unit_ids=("u1", "u2"),
      coverage=(
        ("u1",),
        ("u2",),
        ("u1", "u2"),
        ("u1",),
        ("u2",),
        (),
      ),
      family_numbers=(0, 1, 0, 1, 0, None),
    )
  )

  first = _optimize(participant_ids, artifact, policy=GroupingPolicy.EXPLORE)
  second = _optimize(participant_ids, artifact, policy=GroupingPolicy.EXPLORE)

  assert [group.model_dump(mode="json") for group in first.groups] == [
    group.model_dump(mode="json") for group in second.groups
  ]
  assert first.objectives == second.objectives
  assert first.solver_status == second.solver_status
  assert first.complete_coverage_status == second.complete_coverage_status


def test_randomized_supported_sizes_preserve_exactly_once_and_capacity_invariants() -> None:
  random = Random(20260719)
  for participant_count in range(4, 13):
    participant_ids = _participants(participant_count)
    coverage = []
    family_numbers = []
    for _ in participant_ids:
      covered = tuple(unit_id for unit_id in ("u1", "u2", "u3") if random.random() < 0.5)
      coverage.append(covered)
      family_numbers.append(random.choice((None, 0, 1)))
    artifact = _semantic(
      _question(
        number=participant_count,
        participant_ids=participant_ids,
        unit_ids=("u1", "u2", "u3"),
        coverage=coverage,
        family_numbers=family_numbers,
      )
    )
    bounds = GroupSize(minimum=2, preferred=3, maximum=4)

    result = _optimize(
      participant_ids,
      artifact,
      bounds=bounds,
      timeout_seconds=0.3,
    )

    flattened = [member for group in result.groups for member in group.participant_ids]
    assert len(flattened) == len(set(flattened)) == participant_count
    assert set(flattened) == set(participant_ids)
    expected_capacities = sorted(select_balanced_capacities(participant_count, bounds))
    assert sorted(len(group.participant_ids) for group in result.groups) == expected_capacities
