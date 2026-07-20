from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import ceil, floor, lcm
from time import monotonic
from typing import Literal, cast
from uuid import UUID

from ortools.sat.python import cp_model

from junto.domain.entities import GroupingPolicy, GroupSize
from junto.engine.models import (
  CompleteCoverageStatus,
  EngineGroup,
  GroupingArtifact,
  ObjectiveOutcome,
  QuestionSemanticArtifact,
  SemanticArtifact,
  SolverStatus,
)


class OptimizerInputError(ValueError):
  """The frozen cohort and semantic artifact cannot form an optimizer input."""


class OptimizerInvariantError(RuntimeError):
  """A model known to contain a capacity-valid partition became inconsistent."""


@dataclass(frozen=True, slots=True)
class OptimizerConfig:
  timeout_seconds: float = 10.0
  random_seed: int = 17


@dataclass(frozen=True, slots=True)
class _Objective:
  name: str
  expression: cp_model.LinearExpr
  maximize: bool = True


@dataclass(slots=True)
class _ModelBundle:
  model: cp_model.CpModel
  participant_ids: tuple[UUID, ...]
  questions: tuple[QuestionSemanticArtifact, ...]
  capacities: tuple[int, ...]
  assignment: dict[tuple[int, int], cp_model.IntVar]
  covered: dict[tuple[int, int, str], cp_model.IntVar]
  full: dict[tuple[int, int], cp_model.IntVar]
  family_present: dict[tuple[int, int, str], cp_model.IntVar]
  normalized_coverage: dict[tuple[int, int], cp_model.IntVar]
  normalization_lcm: int
  coverage_objectives: tuple[_Objective, ...]


class CoverageFirstOptimizer:
  """Deterministic coverage-first CP-SAT partitioning.

  The optimizer receives only validated, opaque semantic artifacts. It never
  interprets answer text, and response-family membership never grants a unit.
  """

  def __init__(self, config: OptimizerConfig | None = None) -> None:
    self._config = config or OptimizerConfig()

  def optimize(
    self,
    *,
    participant_ids: Sequence[UUID],
    semantic_artifact: SemanticArtifact,
    group_size: GroupSize,
    policy: GroupingPolicy | Literal["teach", "explore"],
    trigger: Literal["all_submitted", "deadline", "host"],
    timeout_seconds: float | None = None,
  ) -> GroupingArtifact:
    ordered_participants = tuple(participant_ids)
    _validate_inputs(ordered_participants, semantic_artifact, group_size)
    capacities = select_balanced_capacities(len(ordered_participants), group_size)
    fallback_slots = _deterministic_slot_partition(ordered_participants, capacities)

    policy_value = str(policy)
    if policy_value not in {GroupingPolicy.TEACH.value, GroupingPolicy.EXPLORE.value}:
      raise OptimizerInputError(f"Unsupported grouping policy: {policy_value!r}")

    configured_timeout = self._config.timeout_seconds if timeout_seconds is None else timeout_seconds
    solve_window_seconds = max(0.0, float(configured_timeout))
    started_at = monotonic()
    deadline = started_at + solve_window_seconds

    if solve_window_seconds <= 0:
      return _artifact(
        slots=fallback_slots,
        participant_ids=ordered_participants,
        policy=policy_value,
        trigger=trigger,
        solver_status=SolverStatus.FALLBACK,
        complete_status=CompleteCoverageStatus.UNKNOWN,
        timed_out=True,
        started_at=started_at,
        objectives=(),
      )

    complete_status = CompleteCoverageStatus.UNKNOWN
    best_slots: tuple[tuple[UUID, ...], ...] | None = None
    has_solver_assignment = False
    outcomes: list[ObjectiveOutcome] = []
    timed_out = False

    feasibility_bundle = _build_model(
      ordered_participants,
      semantic_artifact.questions,
      capacities,
    )
    for variable in feasibility_bundle.covered.values():
      feasibility_bundle.model.add(variable == 1)
    _add_partition_hint(feasibility_bundle, fallback_slots)

    feasibility_seconds = min(solve_window_seconds / 3.0, _remaining(deadline))
    if feasibility_seconds > 0:
      feasibility_solver, feasibility_result = _solve(
        feasibility_bundle.model,
        feasibility_seconds,
        self._config.random_seed,
      )
      if feasibility_result in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        complete_status = CompleteCoverageStatus.FEASIBLE
        best_slots = _extract_slot_partition(feasibility_bundle, feasibility_solver)
        has_solver_assignment = True
      elif feasibility_result == cp_model.INFEASIBLE:
        complete_status = CompleteCoverageStatus.INFEASIBLE
      else:
        complete_status = CompleteCoverageStatus.UNKNOWN

    optimization_bundle = _build_model(
      ordered_participants,
      semantic_artifact.questions,
      capacities,
    )
    if complete_status == CompleteCoverageStatus.FEASIBLE:
      for variable in optimization_bundle.covered.values():
        optimization_bundle.model.add(variable == 1)
      outcomes.extend(_complete_coverage_outcomes(optimization_bundle))

    _add_partition_hint(optimization_bundle, best_slots or fallback_slots)
    can_continue = True

    if complete_status != CompleteCoverageStatus.FEASIBLE:
      (
        best_slots,
        has_solver_assignment,
        can_continue,
        stage_timed_out,
      ) = self._run_objectives(
        bundle=optimization_bundle,
        objectives=optimization_bundle.coverage_objectives,
        deadline=deadline,
        outcomes=outcomes,
        best_slots=best_slots,
        has_solver_assignment=has_solver_assignment,
      )
      timed_out = timed_out or stage_timed_out
      if best_slots is not None and _has_complete_coverage(
        best_slots,
        semantic_artifact.questions,
      ):
        complete_status = CompleteCoverageStatus.FEASIBLE
      elif complete_status == CompleteCoverageStatus.UNKNOWN:
        worst_outcome = next(
          (outcome for outcome in outcomes if outcome.name == "coverage.worst_normalized"),
          None,
        )
        if (
          worst_outcome is not None
          and worst_outcome.proven_optimal
          and worst_outcome.value < optimization_bundle.normalization_lcm
        ):
          # Proving the best possible worst-pair score is below its
          # maximum is also an exact proof that full coverage is impossible.
          complete_status = CompleteCoverageStatus.INFEASIBLE

    if can_continue:
      policy_objectives = _add_policy_objectives(optimization_bundle, policy_value)
      (
        best_slots,
        has_solver_assignment,
        can_continue,
        stage_timed_out,
      ) = self._run_objectives(
        bundle=optimization_bundle,
        objectives=policy_objectives,
        deadline=deadline,
        outcomes=outcomes,
        best_slots=best_slots,
        has_solver_assignment=has_solver_assignment,
      )
      timed_out = timed_out or stage_timed_out

    if _remaining(deadline) <= 0 and not can_continue:
      timed_out = True

    final_slots = best_slots or fallback_slots
    if has_solver_assignment:
      solver_status = SolverStatus.OPTIMAL if can_continue else SolverStatus.FEASIBLE
    else:
      solver_status = SolverStatus.FALLBACK

    return _artifact(
      slots=final_slots,
      participant_ids=ordered_participants,
      policy=policy_value,
      trigger=trigger,
      solver_status=solver_status,
      complete_status=complete_status,
      timed_out=timed_out,
      started_at=started_at,
      objectives=tuple(outcomes),
    )

  def _run_objectives(
    self,
    *,
    bundle: _ModelBundle,
    objectives: Sequence[_Objective],
    deadline: float,
    outcomes: list[ObjectiveOutcome],
    best_slots: tuple[tuple[UUID, ...], ...] | None,
    has_solver_assignment: bool,
  ) -> tuple[tuple[tuple[UUID, ...], ...] | None, bool, bool, bool]:
    for objective in objectives:
      remaining = _remaining(deadline)
      if remaining <= 0:
        return best_slots, has_solver_assignment, False, True

      if objective.maximize:
        bundle.model.maximize(objective.expression)
      else:
        bundle.model.minimize(objective.expression)
      solver, result = _solve(
        bundle.model,
        remaining,
        self._config.random_seed,
      )
      if result in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        value = int(solver.Value(objective.expression))
        best_slots = _extract_slot_partition(bundle, solver)
        has_solver_assignment = True
        proven = result == cp_model.OPTIMAL
        outcomes.append(
          ObjectiveOutcome(
            name=objective.name,
            value=value,
            proven_optimal=proven,
          )
        )
        if not proven:
          return best_slots, has_solver_assignment, False, True
        bundle.model.add(objective.expression == value)
        continue
      if result == cp_model.UNKNOWN:
        return best_slots, has_solver_assignment, False, True
      if result == cp_model.INFEASIBLE:
        raise OptimizerInvariantError(f"Objective {objective.name!r} made a known-valid model infeasible.")
      raise OptimizerInvariantError(f"Objective {objective.name!r} returned unexpected status {result}.")
    return best_slots, has_solver_assignment, True, False


def select_balanced_capacities(
  participant_count: int,
  bounds: GroupSize,
) -> tuple[int, ...]:
  """Choose the specified preferred-size group count and balanced capacities."""

  if participant_count <= 0:
    raise OptimizerInputError("At least one participant is required to form groups.")
  if not (0 < bounds.minimum <= bounds.preferred <= bounds.maximum):
    raise OptimizerInputError("Group-size bounds must be positive and ordered.")

  first_count = ceil(participant_count / bounds.maximum)
  last_count = floor(participant_count / bounds.minimum)
  feasible_counts = tuple(range(first_count, last_count + 1))
  if not feasible_counts:
    raise OptimizerInputError("The participant count cannot satisfy the configured group sizes.")

  group_count = min(
    feasible_counts,
    key=lambda count: (
      Fraction(abs(participant_count - bounds.preferred * count), count),
      -count,
    ),
  )
  smaller, larger_group_count = divmod(participant_count, group_count)
  capacities = tuple([smaller + 1] * larger_group_count + [smaller] * (group_count - larger_group_count))
  if min(capacities) < bounds.minimum or max(capacities) > bounds.maximum:
    raise OptimizerInvariantError("Balanced capacity construction violated its bounds.")
  return capacities


def _validate_inputs(
  participant_ids: tuple[UUID, ...],
  artifact: SemanticArtifact,
  group_size: GroupSize,
) -> None:
  if not participant_ids:
    raise OptimizerInputError("At least one participant is required to form groups.")
  if len(participant_ids) != len(set(participant_ids)):
    raise OptimizerInputError("The frozen participant order contains duplicates.")
  select_balanced_capacities(len(participant_ids), group_size)
  if not artifact.questions:
    raise OptimizerInputError("At least one semantic question is required.")
  expected = set(participant_ids)
  for question in artifact.questions:
    actual = {assignment.participant_id for assignment in question.assignments}
    if actual != expected:
      raise OptimizerInputError("Every semantic question must contain exactly the frozen participant set.")


def _build_model(
  participant_ids: tuple[UUID, ...],
  questions: tuple[QuestionSemanticArtifact, ...],
  capacities: tuple[int, ...],
) -> _ModelBundle:
  model = cp_model.CpModel()
  participant_index = {participant_id: index for index, participant_id in enumerate(participant_ids)}
  assignment: dict[tuple[int, int], cp_model.IntVar] = {}
  for participant in range(len(participant_ids)):
    for group in range(len(capacities)):
      assignment[(participant, group)] = model.new_bool_var(f"x_s{participant}_g{group}")
    model.add(sum(assignment[(participant, group)] for group in range(len(capacities))) == 1)
  for group, capacity in enumerate(capacities):
    model.add(sum(assignment[(participant, group)] for participant in range(len(participant_ids))) == capacity)

  # Equal-capacity slots are interchangeable. Ordering their member-index sums
  # removes a safe portion of that symmetry without constraining the partition.
  for group in range(len(capacities) - 1):
    if capacities[group] != capacities[group + 1]:
      continue
    left = sum((participant + 1) * assignment[(participant, group)] for participant in range(len(participant_ids)))
    right = sum((participant + 1) * assignment[(participant, group + 1)] for participant in range(len(participant_ids)))
    model.add(left <= right)

  covered: dict[tuple[int, int, str], cp_model.IntVar] = {}
  full: dict[tuple[int, int], cp_model.IntVar] = {}
  family_present: dict[tuple[int, int, str], cp_model.IntVar] = {}
  normalized_coverage: dict[tuple[int, int], cp_model.IntVar] = {}
  normalization_lcm = lcm(*(len(question.unit_ids) for question in questions))

  for question_number, question in enumerate(questions):
    for group in range(len(capacities)):
      question_covered: list[cp_model.IntVar] = []
      for unit_id in question.unit_ids:
        variable = model.new_bool_var(f"covered_g{group}_q{question_number}_u{unit_id}")
        covered[(group, question_number, unit_id)] = variable
        carriers = [
          assignment[(participant_index[item.participant_id], group)]
          for item in question.assignments
          if unit_id in item.covered_unit_ids
        ]
        if carriers:
          model.add_max_equality(variable, carriers)
        else:
          model.add(variable == 0)
        question_covered.append(variable)

      full_variable = model.new_bool_var(f"full_g{group}_q{question_number}")
      full[(group, question_number)] = full_variable
      model.add(sum(question_covered) == len(question_covered)).only_enforce_if(full_variable)
      model.add(sum(question_covered) <= len(question_covered) - 1).only_enforce_if(full_variable.Not())

      normalized = model.new_int_var(
        0,
        normalization_lcm,
        f"normalized_g{group}_q{question_number}",
      )
      factor = normalization_lcm // len(question.unit_ids)
      model.add(normalized == factor * sum(question_covered))
      normalized_coverage[(group, question_number)] = normalized

      for family in question.families:
        variable = model.new_bool_var(f"family_g{group}_q{question_number}_f{family.id}")
        family_present[(group, question_number, family.id)] = variable
        members = [
          assignment[(participant_index[item.participant_id], group)]
          for item in question.assignments
          if item.family_id == family.id
        ]
        if members:
          model.add_max_equality(variable, members)
        else:
          model.add(variable == 0)

  worst_normalized = model.new_int_var(0, normalization_lcm, "worst_normalized")
  model.add_min_equality(worst_normalized, tuple(normalized_coverage.values()))

  full_by_group: list[cp_model.IntVar] = []
  for group in range(len(capacities)):
    value = model.new_int_var(0, len(questions), f"full_questions_g{group}")
    model.add(value == sum(full[(group, question_number)] for question_number in range(len(questions))))
    full_by_group.append(value)
  minimum_full = model.new_int_var(0, len(questions), "minimum_full_questions")
  model.add_min_equality(minimum_full, full_by_group)

  total_full = cp_model.LinearExpr.sum(list(full.values()))
  total_normalized = cp_model.LinearExpr.sum(list(normalized_coverage.values()))
  coverage_objectives = (
    _Objective("coverage.worst_normalized", worst_normalized),
    _Objective("coverage.minimum_full_questions", minimum_full),
    _Objective("coverage.total_full_pairs", total_full),
    _Objective("coverage.total_normalized", total_normalized),
  )

  model.add_decision_strategy(
    [
      assignment[(participant, group)]
      for participant in range(len(participant_ids))
      for group in range(len(capacities))
    ],
    cp_model.CHOOSE_FIRST,
    cp_model.SELECT_MAX_VALUE,
  )
  return _ModelBundle(
    model=model,
    participant_ids=participant_ids,
    questions=questions,
    capacities=capacities,
    assignment=assignment,
    covered=covered,
    full=full,
    family_present=family_present,
    normalized_coverage=normalized_coverage,
    normalization_lcm=normalization_lcm,
    coverage_objectives=coverage_objectives,
  )


def _add_policy_objectives(
  bundle: _ModelBundle,
  policy: str,
) -> tuple[_Objective, ...]:
  if policy == GroupingPolicy.TEACH.value:
    return _add_teach_objectives(bundle)
  return _add_explore_objectives(bundle)


def _add_teach_objectives(bundle: _ModelBundle) -> tuple[_Objective, ...]:
  contributions: dict[tuple[int, int], list[cp_model.IntVar]] = {
    (participant, group): []
    for participant in range(len(bundle.participant_ids))
    for group in range(len(bundle.capacities))
  }
  participant_index = {participant_id: index for index, participant_id in enumerate(bundle.participant_ids)}

  for question_number, question in enumerate(bundle.questions):
    for group in range(len(bundle.capacities)):
      for unit_id in question.unit_ids:
        representatives: list[cp_model.IntVar] = []
        for semantic_assignment in question.assignments:
          if unit_id not in semantic_assignment.covered_unit_ids:
            continue
          participant = participant_index[semantic_assignment.participant_id]
          variable = bundle.model.new_bool_var(f"rep_s{participant}_g{group}_q{question_number}_u{unit_id}")
          bundle.model.add(variable <= bundle.assignment[(participant, group)])
          representatives.append(variable)
          contributions[(participant, group)].append(variable)
        bundle.model.add(sum(representatives) == bundle.covered[(group, question_number, unit_id)])

  active: dict[tuple[int, int], cp_model.IntVar] = {}
  load: dict[tuple[int, int], cp_model.IntVar] = {}
  maximum_possible_load = sum(len(question.unit_ids) for question in bundle.questions)
  for participant in range(len(bundle.participant_ids)):
    for group in range(len(bundle.capacities)):
      contribution_variables = contributions[(participant, group)]
      active_variable = bundle.model.new_bool_var(f"active_s{participant}_g{group}")
      load_variable = bundle.model.new_int_var(
        0,
        maximum_possible_load,
        f"load_s{participant}_g{group}",
      )
      if contribution_variables:
        bundle.model.add_max_equality(active_variable, contribution_variables)
        bundle.model.add(load_variable == sum(contribution_variables))
      else:
        bundle.model.add(active_variable == 0)
        bundle.model.add(load_variable == 0)
      active[(participant, group)] = active_variable
      load[(participant, group)] = load_variable

  active_by_group: list[cp_model.IntVar] = []
  for group, capacity in enumerate(bundle.capacities):
    value = bundle.model.new_int_var(0, capacity, f"active_count_g{group}")
    bundle.model.add(value == sum(active[(participant, group)] for participant in range(len(bundle.participant_ids))))
    active_by_group.append(value)
  minimum_active = bundle.model.new_int_var(
    0,
    max(bundle.capacities),
    "minimum_active_contributors",
  )
  bundle.model.add_min_equality(minimum_active, active_by_group)

  maximum_load = bundle.model.new_int_var(0, maximum_possible_load, "maximum_rep_load")
  bundle.model.add_max_equality(maximum_load, tuple(load.values()))

  return (
    _Objective("teach.minimum_active_contributors", minimum_active),
    _Objective("teach.maximum_representative_load", maximum_load, maximize=False),
    _Objective(
      "teach.total_active_contributors",
      cp_model.LinearExpr.sum(list(active.values())),
    ),
    _Objective(
      "teach.total_family_variety",
      cp_model.LinearExpr.sum(list(bundle.family_present.values())),
    ),
  )


def _add_explore_objectives(bundle: _ModelBundle) -> tuple[_Objective, ...]:
  family_counts: dict[tuple[int, int], cp_model.IntVar] = {}
  diverse: dict[tuple[int, int], cp_model.IntVar] = {}
  any_family: dict[tuple[int, int], cp_model.IntVar] = {}
  denominators: list[int] = []

  for group, capacity in enumerate(bundle.capacities):
    for question_number, question in enumerate(bundle.questions):
      present = [bundle.family_present[(group, question_number, family.id)] for family in question.families]
      family_count = bundle.model.new_int_var(
        0,
        min(capacity, len(question.families)),
        f"family_count_g{group}_q{question_number}",
      )
      bundle.model.add(family_count == sum(present))
      family_counts[(group, question_number)] = family_count

      diverse_variable = bundle.model.new_bool_var(f"diverse_g{group}_q{question_number}")
      bundle.model.add(family_count >= 2).only_enforce_if(diverse_variable)
      bundle.model.add(family_count <= 1).only_enforce_if(diverse_variable.Not())
      diverse[(group, question_number)] = diverse_variable

      any_variable = bundle.model.new_bool_var(f"any_family_g{group}_q{question_number}")
      if present:
        bundle.model.add_max_equality(any_variable, present)
      else:
        bundle.model.add(any_variable == 0)
      any_family[(group, question_number)] = any_variable

      maximum_families = min(capacity, len(question.families))
      if maximum_families >= 2:
        denominators.append(maximum_families - 1)

  diversity_lcm = lcm(*denominators) if denominators else 1
  additional_scores: list[cp_model.IntVar] = []
  for group, capacity in enumerate(bundle.capacities):
    for question_number, question in enumerate(bundle.questions):
      maximum_families = min(capacity, len(question.families))
      score = bundle.model.new_int_var(
        0,
        diversity_lcm,
        f"additional_family_score_g{group}_q{question_number}",
      )
      if maximum_families < 2:
        bundle.model.add(score == 0)
      else:
        factor = diversity_lcm // (maximum_families - 1)
        bundle.model.add(
          score == factor * (family_counts[(group, question_number)] - any_family[(group, question_number)])
        )
      additional_scores.append(score)

  diverse_by_group: list[cp_model.IntVar] = []
  for group in range(len(bundle.capacities)):
    value = bundle.model.new_int_var(
      0,
      len(bundle.questions),
      f"diverse_questions_g{group}",
    )
    bundle.model.add(
      value == sum(diverse[(group, question_number)] for question_number in range(len(bundle.questions)))
    )
    diverse_by_group.append(value)
  minimum_diverse = bundle.model.new_int_var(
    0,
    len(bundle.questions),
    "minimum_diverse_questions",
  )
  bundle.model.add_min_equality(minimum_diverse, diverse_by_group)

  return (
    _Objective("explore.minimum_diverse_questions", minimum_diverse),
    _Objective(
      "explore.total_diverse_pairs",
      cp_model.LinearExpr.sum(list(diverse.values())),
    ),
    _Objective(
      "explore.additional_family_coverage",
      cp_model.LinearExpr.sum(additional_scores),
    ),
  )


def _complete_coverage_outcomes(bundle: _ModelBundle) -> tuple[ObjectiveOutcome, ...]:
  group_count = len(bundle.capacities)
  question_count = len(bundle.questions)
  return (
    ObjectiveOutcome(
      name="coverage.worst_normalized",
      value=bundle.normalization_lcm,
      proven_optimal=True,
    ),
    ObjectiveOutcome(
      name="coverage.minimum_full_questions",
      value=question_count,
      proven_optimal=True,
    ),
    ObjectiveOutcome(
      name="coverage.total_full_pairs",
      value=group_count * question_count,
      proven_optimal=True,
    ),
    ObjectiveOutcome(
      name="coverage.total_normalized",
      value=group_count * question_count * bundle.normalization_lcm,
      proven_optimal=True,
    ),
  )


def _solve(
  model: cp_model.CpModel,
  timeout_seconds: float,
  random_seed: int,
) -> tuple[cp_model.CpSolver, cp_model.CpSolverStatus]:
  solver = cp_model.CpSolver()
  solver.parameters.max_time_in_seconds = max(0.000001, timeout_seconds)
  solver.parameters.num_search_workers = 1
  solver.parameters.random_seed = random_seed
  solver.parameters.log_search_progress = False
  result = solver.Solve(model)
  return solver, result


def _add_partition_hint(
  bundle: _ModelBundle,
  slots: tuple[tuple[UUID, ...], ...],
) -> None:
  if len(slots) != len(bundle.capacities):
    raise OptimizerInvariantError("Partition hint has the wrong number of groups.")
  membership = {participant_id: group for group, members in enumerate(slots) for participant_id in members}
  for participant, participant_id in enumerate(bundle.participant_ids):
    for group in range(len(bundle.capacities)):
      bundle.model.add_hint(
        bundle.assignment[(participant, group)],
        int(membership[participant_id] == group),
      )


def _extract_slot_partition(
  bundle: _ModelBundle,
  solver: cp_model.CpSolver,
) -> tuple[tuple[UUID, ...], ...]:
  slots: list[tuple[UUID, ...]] = []
  for group in range(len(bundle.capacities)):
    members = tuple(
      participant_id
      for participant, participant_id in enumerate(bundle.participant_ids)
      if solver.BooleanValue(bundle.assignment[(participant, group)])
    )
    if len(members) != bundle.capacities[group]:
      raise OptimizerInvariantError("Solver returned a capacity-invalid partition.")
    slots.append(members)
  return tuple(slots)


def _deterministic_slot_partition(
  participant_ids: tuple[UUID, ...],
  capacities: tuple[int, ...],
) -> tuple[tuple[UUID, ...], ...]:
  slots: list[tuple[UUID, ...]] = []
  offset = 0
  for capacity in capacities:
    slots.append(participant_ids[offset : offset + capacity])
    offset += capacity
  return tuple(slots)


def _canonical_groups(
  slots: tuple[tuple[UUID, ...], ...],
  participant_ids: tuple[UUID, ...],
) -> tuple[EngineGroup, ...]:
  order = {participant_id: index for index, participant_id in enumerate(participant_ids)}
  ordered_slots = [tuple(sorted(slot, key=order.__getitem__)) for slot in slots]
  ordered_slots.sort(key=lambda slot: tuple(order[participant] for participant in slot))
  return tuple(
    EngineGroup(id=f"g{index}", participant_ids=members) for index, members in enumerate(ordered_slots, start=1)
  )


def _has_complete_coverage(
  slots: tuple[tuple[UUID, ...], ...],
  questions: tuple[QuestionSemanticArtifact, ...],
) -> bool:
  for members in slots:
    member_set = set(members)
    for question in questions:
      assignments = [assignment for assignment in question.assignments if assignment.participant_id in member_set]
      for unit_id in question.unit_ids:
        if not any(unit_id in assignment.covered_unit_ids for assignment in assignments):
          return False
  return True


def _artifact(
  *,
  slots: tuple[tuple[UUID, ...], ...],
  participant_ids: tuple[UUID, ...],
  policy: str,
  trigger: str,
  solver_status: SolverStatus,
  complete_status: CompleteCoverageStatus,
  timed_out: bool,
  started_at: float,
  objectives: tuple[ObjectiveOutcome, ...],
) -> GroupingArtifact:
  return GroupingArtifact(
    policy=cast(Literal["teach", "explore"], policy),
    trigger=cast(Literal["all_submitted", "deadline", "host"], trigger),
    groups=_canonical_groups(slots, participant_ids),
    solver_status=solver_status,
    complete_coverage_status=complete_status,
    timed_out=timed_out,
    solve_milliseconds=max(0, round((monotonic() - started_at) * 1000)),
    objectives=objectives,
  )


def _remaining(deadline: float) -> float:
  return max(0.0, deadline - monotonic())
