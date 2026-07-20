from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast

from junto.domain.entities import Question, Room
from junto.engine.compiler import (
  CoverageUnitInput,
  QuestionCompilationInput,
  SemanticAnswerInput,
  SemanticCompiler,
)
from junto.engine.models import GroupingArtifact, SemanticArtifact
from junto.engine.optimizer import CoverageFirstOptimizer


class AnalysisPipeline(Protocol):
  def compile(self, room: Room) -> SemanticArtifact: ...

  def optimize(
    self,
    room: Room,
    semantic_artifact: SemanticArtifact,
    *,
    trigger: str,
  ) -> GroupingArtifact: ...


@dataclass(frozen=True, slots=True)
class CoverageAnalysisPipeline:
  compiler: SemanticCompiler
  optimizer: CoverageFirstOptimizer
  solver_timeout_seconds: float

  def compile(self, room: Room) -> SemanticArtifact:
    return self.compiler.compile_sync(tuple(self._question_input(room, question) for question in room.questions))

  def optimize(
    self,
    room: Room,
    semantic_artifact: SemanticArtifact,
    *,
    trigger: str,
  ) -> GroupingArtifact:
    known_trigger = cast(
      Literal["all_submitted", "deadline", "host"],
      trigger,
    )
    return self.optimizer.optimize(
      participant_ids=room.cohort_ids,
      semantic_artifact=semantic_artifact,
      group_size=room.group_size,
      policy=room.policy,
      trigger=known_trigger,
      timeout_seconds=self.solver_timeout_seconds,
    )

  @staticmethod
  def _question_input(room: Room, question: Question) -> QuestionCompilationInput:
    reference_material = build_reference_material(room, question)
    answers = tuple(
      SemanticAnswerInput(
        participant_id=participant_id,
        text=room.responses[(participant_id, question.id)].text,
      )
      for participant_id in room.cohort_ids
      if (participant_id, question.id) in room.responses
    )
    return QuestionCompilationInput(
      question_id=question.id,
      prompt=question.prompt,
      reference_material=reference_material,
      coverage_units=tuple(CoverageUnitInput(id=unit.id, text=unit.text) for unit in question.coverage_units),
      participant_ids=room.cohort_ids,
      answers=answers,
    )


def build_reference_material(room: Room, question: Question) -> str | None:
  reference_sections: list[str] = []
  if question.reference_material:
    reference_sections.append("Question-specific host reference:\n" + question.reference_material)
  for attachment in sorted(
    room.reference_attachments.values(),
    key=lambda item: (item.uploaded_at, str(item.id)),
  ):
    reference_sections.append(f"Room reference file {attachment.file_name}:\n{attachment.extracted_text}")
  return "\n\n".join(reference_sections) or None
