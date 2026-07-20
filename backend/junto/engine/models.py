from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


def _utc_now() -> datetime:
  return datetime.now(UTC)


class EngineModel(BaseModel):
  """Strict, immutable artifact model shared by compiler, optimizer, and storage."""

  model_config = ConfigDict(
    alias_generator=to_camel,
    extra="forbid",
    frozen=True,
    populate_by_name=True,
  )


class ResponseFamily(EngineModel):
  id: str = Field(min_length=1, max_length=80)
  label: str = Field(min_length=1, max_length=120)


class SemanticAssignment(EngineModel):
  participant_id: UUID
  family_id: str | None = Field(default=None, max_length=80)
  covered_unit_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=8)

  @field_validator("covered_unit_ids")
  @classmethod
  def unique_covered_units(cls, value: tuple[str, ...]) -> tuple[str, ...]:
    if len(value) != len(set(value)):
      raise ValueError("covered_unit_ids must not contain duplicates")
    return value


class QuestionSemanticArtifact(EngineModel):
  question_id: UUID
  unit_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
  families: tuple[ResponseFamily, ...] = Field(default_factory=tuple)
  assignments: tuple[SemanticAssignment, ...]

  @model_validator(mode="after")
  def validate_question_domain(self) -> Self:
    if len(self.unit_ids) != len(set(self.unit_ids)):
      raise ValueError("unit_ids must be unique")
    family_ids = [family.id for family in self.families]
    if len(family_ids) != len(set(family_ids)):
      raise ValueError("family IDs must be unique")
    if len({family.label.casefold() for family in self.families}) != len(self.families):
      raise ValueError("family labels must be unique")
    participant_ids = [assignment.participant_id for assignment in self.assignments]
    if len(participant_ids) != len(set(participant_ids)):
      raise ValueError("participant assignments must be unique")
    known_units = set(self.unit_ids)
    known_families = set(family_ids)
    for assignment in self.assignments:
      if not set(assignment.covered_unit_ids) <= known_units:
        raise ValueError("assignment contains an unknown coverage unit")
      if assignment.family_id is not None and assignment.family_id not in known_families:
        raise ValueError("assignment contains an unknown family")
    used_families = {assignment.family_id for assignment in self.assignments if assignment.family_id is not None}
    if used_families != known_families:
      raise ValueError("every declared family must be used")
    return self


class SemanticArtifact(EngineModel):
  schema_version: Literal["1"] = "1"
  compiled_at: datetime = Field(default_factory=_utc_now)
  model: str = Field(default="recorded", min_length=1, max_length=120)
  questions: tuple[QuestionSemanticArtifact, ...]

  @model_validator(mode="after")
  def validate_artifact(self) -> Self:
    question_ids = [question.question_id for question in self.questions]
    if len(question_ids) != len(set(question_ids)):
      raise ValueError("question artifacts must be unique")
    if self.questions:
      expected = {item.participant_id for item in self.questions[0].assignments}
      for question in self.questions[1:]:
        if {item.participant_id for item in question.assignments} != expected:
          raise ValueError("every question must contain the frozen participant set")
    return self


class SolverStatus(StrEnum):
  OPTIMAL = "optimal"
  FEASIBLE = "feasible"
  FALLBACK = "fallback"


class CompleteCoverageStatus(StrEnum):
  FEASIBLE = "feasible"
  INFEASIBLE = "infeasible"
  UNKNOWN = "unknown"


class ObjectiveOutcome(EngineModel):
  name: str = Field(min_length=1, max_length=100)
  value: int
  proven_optimal: bool


class EngineGroup(EngineModel):
  id: str = Field(pattern=r"^g[1-9][0-9]*$")
  participant_ids: tuple[UUID, ...] = Field(min_length=1)

  @field_validator("participant_ids")
  @classmethod
  def unique_members(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
    if len(value) != len(set(value)):
      raise ValueError("a group cannot contain duplicate participants")
    return value


class GroupingArtifact(EngineModel):
  schema_version: Literal["1"] = "1"
  generation_mode: Literal["coverage_aware"] = "coverage_aware"
  policy: Literal["teach", "explore"]
  trigger: Literal["all_submitted", "deadline", "host"]
  generated_at: datetime = Field(default_factory=_utc_now)
  groups: tuple[EngineGroup, ...]
  solver_status: SolverStatus
  complete_coverage_status: CompleteCoverageStatus
  timed_out: bool = False
  solve_milliseconds: int = Field(default=0, ge=0)
  objectives: tuple[ObjectiveOutcome, ...] = Field(default_factory=tuple)

  @model_validator(mode="after")
  def validate_partition_shape(self) -> Self:
    if tuple(group.id for group in self.groups) != tuple(f"g{index}" for index in range(1, len(self.groups) + 1)):
      raise ValueError("group IDs must be canonical and ordered")
    all_members = [member for group in self.groups for member in group.participant_ids]
    if len(all_members) != len(set(all_members)):
      raise ValueError("a participant cannot appear in more than one group")
    return self
