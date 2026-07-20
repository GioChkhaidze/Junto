from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID, uuid5

from pydantic import BaseModel

from junto.domain.limits import MAX_ANSWER_CHARACTERS
from junto.engine.models import (
  QuestionSemanticArtifact,
  ResponseFamily,
  SemanticArtifact,
  SemanticAssignment,
)
from junto.engine.prompts import (
  CoveragePrompt,
  FamilyPrompt,
  PromptAnswer,
  PromptCoverageUnit,
  RepairPrompt,
  coverage_messages,
  family_messages,
)
from junto.engine.provider import (
  CoverageClassificationOutput,
  FamilyClusteringOutput,
  ProviderError,
  ProviderInvalidOutput,
  ProviderPermanentError,
  ProviderRefusalError,
  ProviderRepair,
  ProviderResult,
  ProviderTransientError,
  SemanticProvider,
)

_LOG = logging.getLogger("junto.semantic.compiler")
_FAMILY_NAMESPACE = UUID("6c3f2f63-cacc-5ee1-8267-4b0909c8dc16")
_COVERAGE_BATCH_SIZE = 5
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class CoverageUnitInput:
  id: str
  text: str


@dataclass(frozen=True, slots=True)
class SemanticAnswerInput:
  participant_id: UUID
  text: str


@dataclass(frozen=True, slots=True)
class QuestionCompilationInput:
  question_id: UUID
  prompt: str
  reference_material: str | None
  coverage_units: tuple[CoverageUnitInput, ...]
  participant_ids: tuple[UUID, ...]
  answers: tuple[SemanticAnswerInput, ...]


@dataclass(frozen=True, slots=True)
class CompilerLimits:
  max_questions: int = 8
  max_participants: int = 200
  max_question_characters: int = 4_000
  max_reference_characters: int = 100_000
  max_coverage_units: int = 8
  max_coverage_unit_characters: int = 300
  max_answer_characters: int = MAX_ANSWER_CHARACTERS
  # Applied to UTF-8 bytes, a conservative upper bound on BPE token count.
  max_provider_input_characters: int = 240_000

  def __post_init__(self) -> None:
    values = (
      self.max_questions,
      self.max_participants,
      self.max_question_characters,
      self.max_reference_characters,
      self.max_coverage_units,
      self.max_coverage_unit_characters,
      self.max_answer_characters,
      self.max_provider_input_characters,
    )
    if any(value <= 0 for value in values):
      raise ValueError("all compiler limits must be positive")
    if self.max_participants > 200 or self.max_coverage_units > 8:
      raise ValueError("compiler limits cannot exceed the structured-output schema")


class SemanticCompilerError(RuntimeError):
  """A privacy-safe compiler error suitable for a host-facing failure mapping."""

  def __init__(self, code: str, message: str):
    super().__init__(message)
    self.code = code


@dataclass(slots=True)
class _TransportRetryState:
  retry_used: bool = False


@dataclass(frozen=True, slots=True)
class _ValidatedCoverage:
  by_participant: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _ValidatedFamilies:
  families: tuple[ResponseFamily, ...]
  family_by_participant: dict[str, str | None]


class ProviderRequestLimiter:
  """A cancellation-safe limiter that also works across compile_sync event loops."""

  def __init__(self, capacity: int) -> None:
    if capacity <= 0:
      raise ValueError("request-limiter capacity must be positive")
    self._semaphore = threading.BoundedSemaphore(capacity)

  @asynccontextmanager
  async def slot(self) -> AsyncIterator[None]:
    while not self._semaphore.acquire(blocking=False):
      await asyncio.sleep(0.005)
    try:
      yield
    finally:
      self._semaphore.release()


_SHARED_LIMITERS: dict[int, ProviderRequestLimiter] = {}
_SHARED_LIMITERS_LOCK = threading.Lock()


def _shared_limiter(capacity: int) -> ProviderRequestLimiter:
  with _SHARED_LIMITERS_LOCK:
    return _SHARED_LIMITERS.setdefault(capacity, ProviderRequestLimiter(capacity))


class SemanticCompiler:
  """Compile frozen room text into a validated, prose-free semantic artifact."""

  def __init__(
    self,
    provider: SemanticProvider,
    *,
    limits: CompilerLimits | None = None,
    max_concurrency: int = 4,
    request_limiter: ProviderRequestLimiter | None = None,
    request_timeout_seconds: float = 90.0,
    room_timeout_seconds: float = 240.0,
    transport_retry_delay_seconds: float = 0.2,
  ) -> None:
    if max_concurrency <= 0:
      raise ValueError("max_concurrency must be positive")
    if request_timeout_seconds <= 0 or room_timeout_seconds <= 0:
      raise ValueError("compiler timeouts must be positive")
    if request_timeout_seconds > room_timeout_seconds:
      raise ValueError("request timeout cannot exceed room timeout")
    if transport_retry_delay_seconds < 0:
      raise ValueError("transport_retry_delay_seconds cannot be negative")
    self._provider = provider
    self._limits = limits or CompilerLimits()
    self._semaphore = request_limiter or _shared_limiter(max_concurrency)
    self._request_timeout_seconds = request_timeout_seconds
    self._room_timeout_seconds = room_timeout_seconds
    self._transport_retry_delay_seconds = transport_retry_delay_seconds

  async def compile(
    self,
    questions: Sequence[QuestionCompilationInput],
  ) -> SemanticArtifact:
    validated = self._validate_inputs(questions)
    try:
      async with asyncio.timeout(self._room_timeout_seconds):
        question_artifacts = await self._compile_questions(validated)
    except TimeoutError:
      raise SemanticCompilerError(
        "SEMANTIC_TIMEOUT",
        "Response analysis did not finish within the configured time limit.",
      ) from None
    artifact = SemanticArtifact(
      model=self._provider.model_name,
      questions=tuple(question_artifacts),
    )
    _LOG.info(
      "semantic_compilation_complete",
      extra={
        "junto_model": self._provider.model_name,
        "junto_question_count": len(artifact.questions),
        "junto_participant_count": (len(artifact.questions[0].assignments) if artifact.questions else 0),
      },
    )
    return artifact

  def compile_sync(
    self,
    questions: Sequence[QuestionCompilationInput],
  ) -> SemanticArtifact:
    try:
      asyncio.get_running_loop()
    except RuntimeError:
      return asyncio.run(self.compile(questions))
    raise RuntimeError("compile_sync cannot run inside an active event loop; await compile instead")

  async def _compile_questions(
    self,
    questions: tuple[QuestionCompilationInput, ...],
  ) -> list[QuestionSemanticArtifact]:
    tasks = [asyncio.create_task(self._compile_question(question)) for question in questions]
    try:
      return list(await asyncio.gather(*tasks))
    except BaseException:
      for task in tasks:
        if not task.done():
          task.cancel()
      await asyncio.gather(*tasks, return_exceptions=True)
      raise

  async def _compile_question(
    self,
    question: QuestionCompilationInput,
  ) -> QuestionSemanticArtifact:
    unit_ids = tuple(unit.id for unit in question.coverage_units)
    answer_by_participant = {answer.participant_id: answer.text for answer in question.answers}
    non_empty = tuple(
      PromptAnswer(
        participant_id=str(participant_id),
        text=answer_by_participant[participant_id],
      )
      for participant_id in question.participant_ids
      if participant_id in answer_by_participant and not _normalized_empty(answer_by_participant[participant_id])
    )
    if not non_empty:
      return QuestionSemanticArtifact(
        question_id=question.question_id,
        unit_ids=unit_ids,
        assignments=tuple(
          SemanticAssignment(participant_id=participant_id) for participant_id in question.participant_ids
        ),
      )

    coverage_prompt = CoveragePrompt(
      question_id=str(question.question_id),
      question_prompt=question.prompt,
      reference_material=question.reference_material,
      coverage_units=tuple(PromptCoverageUnit(id=unit.id, text=unit.text) for unit in question.coverage_units),
      answers=non_empty,
    )
    family_prompt = FamilyPrompt(
      question_id=str(question.question_id),
      question_prompt=question.prompt,
      answers=non_empty,
    )
    coverage_prompts = _coverage_batch_prompts(coverage_prompt)
    self._preflight_prompt_sizes(coverage_prompts, family_prompt)

    coverage_task = asyncio.create_task(self._compile_coverage(coverage_prompts))
    family_task = asyncio.create_task(self._compile_families(family_prompt))
    try:
      coverage, families = await asyncio.gather(coverage_task, family_task)
    except BaseException:
      for task in (coverage_task, family_task):
        if not task.done():
          task.cancel()
      await asyncio.gather(coverage_task, family_task, return_exceptions=True)
      raise

    expected_non_empty = {answer.participant_id for answer in non_empty}
    if set(coverage.by_participant) != expected_non_empty or set(families.family_by_participant) != expected_non_empty:
      raise SemanticCompilerError(
        "SEMANTIC_OUTPUT_INVALID",
        "Response analysis returned inconsistent participant assignments.",
      )

    assignments = tuple(
      SemanticAssignment(
        participant_id=participant_id,
        family_id=families.family_by_participant.get(str(participant_id)),
        covered_unit_ids=coverage.by_participant.get(str(participant_id), ()),
      )
      for participant_id in question.participant_ids
    )
    return QuestionSemanticArtifact(
      question_id=question.question_id,
      unit_ids=unit_ids,
      families=families.families,
      assignments=assignments,
    )

  async def _compile_coverage(
    self,
    prompts: tuple[CoveragePrompt, ...],
  ) -> _ValidatedCoverage:
    tasks = [asyncio.create_task(self._compile_coverage_batch(prompt)) for prompt in prompts]
    try:
      batches = await asyncio.gather(*tasks)
    except BaseException:
      for task in tasks:
        if not task.done():
          task.cancel()
      await asyncio.gather(*tasks, return_exceptions=True)
      raise
    merged: dict[str, tuple[str, ...]] = {}
    for batch in batches:
      if set(merged) & set(batch.by_participant):
        raise _invalid_output_error()
      merged.update(batch.by_participant)
    expected = {answer.participant_id for prompt in prompts for answer in prompt.answers}
    if set(merged) != expected:
      raise _invalid_output_error()
    return _ValidatedCoverage(by_participant=merged)

  async def _compile_coverage_batch(self, prompt: CoveragePrompt) -> _ValidatedCoverage:
    retry_state = _TransportRetryState()
    invalid_result: object
    validation_errors: tuple[str, ...]
    try:
      first = await self._request(
        lambda: self._provider.classify_coverage(prompt),
        retry_state,
      )
    except ProviderInvalidOutput as error:
      invalid_result = error.invalid_result
      validation_errors = error.validation_errors
      _log_validation("coverage", "first_pass_invalid")
    else:
      validation_errors = _coverage_errors(first.value, prompt)
      if not validation_errors:
        _log_validation("coverage", "first_pass_valid")
        return _validated_coverage(first.value, prompt)
      invalid_result = first.value.model_dump(by_alias=True, mode="json")
      _log_validation("coverage", "first_pass_invalid")

    repair = ProviderRepair(
      invalid_result=invalid_result,
      validation_errors=validation_errors,
    )
    self._preflight_repair("coverage", prompt, repair)
    try:
      repaired = await self._request(
        lambda: self._provider.classify_coverage(prompt, repair=repair),
        retry_state,
      )
    except ProviderInvalidOutput:
      _log_validation("coverage", "repair_invalid")
      raise _invalid_output_error() from None
    validation_errors = _coverage_errors(repaired.value, prompt)
    if validation_errors:
      _log_validation("coverage", "repair_invalid")
      raise _invalid_output_error()
    _log_validation("coverage", "repair_valid")
    return _validated_coverage(repaired.value, prompt)

  async def _compile_families(self, prompt: FamilyPrompt) -> _ValidatedFamilies:
    retry_state = _TransportRetryState()
    invalid_result: object
    validation_errors: tuple[str, ...]
    try:
      first = await self._request(
        lambda: self._provider.cluster_families(prompt),
        retry_state,
      )
    except ProviderInvalidOutput as error:
      invalid_result = error.invalid_result
      validation_errors = error.validation_errors
      _log_validation("family", "first_pass_invalid")
    else:
      validation_errors = _family_errors(first.value, prompt)
      if not validation_errors:
        _log_validation("family", "first_pass_valid")
        return _validated_families(first.value, prompt)
      invalid_result = first.value.model_dump(by_alias=True, mode="json")
      _log_validation("family", "first_pass_invalid")

    repair = ProviderRepair(
      invalid_result=invalid_result,
      validation_errors=validation_errors,
    )
    self._preflight_repair("family", prompt, repair)
    try:
      repaired = await self._request(
        lambda: self._provider.cluster_families(prompt, repair=repair),
        retry_state,
      )
    except ProviderInvalidOutput:
      _log_validation("family", "repair_invalid")
      raise _invalid_output_error() from None
    validation_errors = _family_errors(repaired.value, prompt)
    if validation_errors:
      _log_validation("family", "repair_invalid")
      raise _invalid_output_error()
    _log_validation("family", "repair_valid")
    return _validated_families(repaired.value, prompt)

  async def _request(
    self,
    operation: Callable[[], Awaitable[ProviderResult[T]]],
    retry_state: _TransportRetryState,
  ) -> ProviderResult[T]:
    while True:
      try:
        async with self._semaphore.slot():
          async with asyncio.timeout(self._request_timeout_seconds):
            return await operation()
      except TimeoutError:
        transient: ProviderError = ProviderTransientError()
      except ProviderTransientError as error:
        transient = error
      except ProviderRefusalError:
        raise SemanticCompilerError(
          "SEMANTIC_REFUSAL",
          "Response analysis could not process this room's content.",
        ) from None
      except ProviderPermanentError:
        raise SemanticCompilerError(
          "SEMANTIC_PROVIDER_ERROR",
          "The response-analysis service could not complete the request.",
        ) from None
      except ProviderInvalidOutput:
        raise
      except ProviderError:
        raise SemanticCompilerError(
          "SEMANTIC_PROVIDER_ERROR",
          "The response-analysis service could not complete the request.",
        ) from None
      except Exception:
        raise SemanticCompilerError(
          "SEMANTIC_PROVIDER_ERROR",
          "The response-analysis service could not complete the request.",
        ) from None
      if retry_state.retry_used:
        raise SemanticCompilerError(
          "SEMANTIC_PROVIDER_UNAVAILABLE",
          "The response-analysis service remained unavailable after one retry.",
        ) from transient
      retry_state.retry_used = True
      if self._transport_retry_delay_seconds:
        await asyncio.sleep(self._transport_retry_delay_seconds)

  def _validate_inputs(
    self,
    questions: Sequence[QuestionCompilationInput],
  ) -> tuple[QuestionCompilationInput, ...]:
    values = tuple(questions)
    if not 1 <= len(values) <= self._limits.max_questions:
      raise _invalid_input_error()
    question_ids = [question.question_id for question in values]
    if len(question_ids) != len(set(question_ids)):
      raise _invalid_input_error()
    expected_participants = set(values[0].participant_ids)
    for question in values:
      self._validate_question_input(question)
      if set(question.participant_ids) != expected_participants:
        raise _invalid_input_error()
    return values

  def _validate_question_input(self, question: QuestionCompilationInput) -> None:
    if not 1 <= len(question.prompt) <= self._limits.max_question_characters:
      raise _invalid_input_error()
    if question.prompt.strip() != question.prompt:
      raise _invalid_input_error()
    if (
      question.reference_material is not None
      and len(question.reference_material) > self._limits.max_reference_characters
    ):
      raise _invalid_input_error()
    if not 1 <= len(question.coverage_units) <= self._limits.max_coverage_units:
      raise _invalid_input_error()
    unit_ids = [unit.id for unit in question.coverage_units]
    if len(unit_ids) != len(set(unit_ids)) or any(not unit_id or unit_id.strip() != unit_id for unit_id in unit_ids):
      raise _invalid_input_error()
    if any(len(unit_id) > 80 for unit_id in unit_ids):
      raise _invalid_input_error()
    for unit in question.coverage_units:
      if not 1 <= len(unit.text) <= self._limits.max_coverage_unit_characters:
        raise _invalid_input_error()
      if unit.text.strip() != unit.text:
        raise _invalid_input_error()
    if not 1 <= len(question.participant_ids) <= self._limits.max_participants:
      raise _invalid_input_error()
    if len(question.participant_ids) != len(set(question.participant_ids)):
      raise _invalid_input_error()
    participant_set = set(question.participant_ids)
    answer_ids = [answer.participant_id for answer in question.answers]
    if len(answer_ids) != len(set(answer_ids)) or not set(answer_ids) <= participant_set:
      raise _invalid_input_error()
    if any(len(answer.text) > self._limits.max_answer_characters for answer in question.answers):
      raise _invalid_input_error()

  def _preflight_prompt_sizes(
    self,
    coverage_prompts: Sequence[CoveragePrompt],
    family_prompt: FamilyPrompt,
  ) -> None:
    coverage_sizes = (
      _message_bytes(coverage_messages(prompt)) + _schema_bytes(CoverageClassificationOutput)
      for prompt in coverage_prompts
    )
    family_size = _message_bytes(family_messages(family_prompt)) + _schema_bytes(FamilyClusteringOutput)
    if max(*coverage_sizes, family_size) > self._limits.max_provider_input_characters:
      raise SemanticCompilerError(
        "SEMANTIC_INPUT_TOO_LARGE",
        "This question contains too much text for one bounded analysis request.",
      )

  def _preflight_repair(
    self,
    branch: str,
    prompt: CoveragePrompt | FamilyPrompt,
    repair: ProviderRepair,
  ) -> None:
    try:
      if branch == "coverage":
        assert isinstance(prompt, CoveragePrompt)
        messages = coverage_messages(
          prompt,
          repair=RepairPrompt(
            branch="coverage",
            invalid_result=repair.invalid_result,
            validation_errors=repair.validation_errors,
            schema=CoverageClassificationOutput.model_json_schema(by_alias=True),
          ),
        )
      else:
        assert isinstance(prompt, FamilyPrompt)
        messages = family_messages(
          prompt,
          repair=RepairPrompt(
            branch="family",
            invalid_result=repair.invalid_result,
            validation_errors=repair.validation_errors,
            schema=FamilyClusteringOutput.model_json_schema(by_alias=True),
          ),
        )
    except (TypeError, ValueError):
      raise _invalid_output_error() from None
    output_type = CoverageClassificationOutput if branch == "coverage" else FamilyClusteringOutput
    request_bytes = _message_bytes(messages) + _schema_bytes(output_type)
    if request_bytes > self._limits.max_provider_input_characters:
      raise SemanticCompilerError(
        "SEMANTIC_INPUT_TOO_LARGE",
        "A bounded repair request would exceed the configured analysis limit.",
      )


def _coverage_errors(
  output: CoverageClassificationOutput,
  prompt: CoveragePrompt,
) -> tuple[str, ...]:
  errors: list[str] = []
  expected_participants = {answer.participant_id for answer in prompt.answers}
  assignment_ids = [assignment.participant_id for assignment in output.assignments]
  counts = Counter(assignment_ids)
  if set(assignment_ids) != expected_participants:
    errors.append("assignments must cover exactly the supplied participant IDs")
  if any(count > 1 for count in counts.values()):
    errors.append("participant assignments must not be duplicated")
  known_units = {unit.id for unit in prompt.coverage_units}
  answer_by_participant = {answer.participant_id: answer.text for answer in prompt.answers}
  for index, assignment in enumerate(output.assignments):
    covered = assignment.covered_unit_ids
    if len(covered) != len(set(covered)):
      errors.append(f"assignment[{index}] repeats a covered unit ID")
    if not set(covered) <= known_units:
      errors.append(f"assignment[{index}] contains an unknown unit ID")
    evidence_ids = [evidence.unit_id for evidence in assignment.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
      errors.append(f"assignment[{index}] repeats an evidence unit ID")
    if set(evidence_ids) != set(covered) or len(evidence_ids) != len(covered):
      errors.append(f"assignment[{index}] evidence units must exactly match coveredUnitIds")
    answer = answer_by_participant.get(assignment.participant_id)
    if answer is None:
      continue
    normalized_answer = _normalize_line_endings(answer)
    for evidence in assignment.evidence:
      if evidence.unit_id not in known_units:
        errors.append(f"assignment[{index}] evidence contains an unknown unit ID")
      if any(_normalize_line_endings(quote) not in normalized_answer for quote in evidence.quotes):
        errors.append(f"assignment[{index}] evidence must be a literal substring of its own answer")
  return tuple(errors[:40])


def _coverage_batch_prompts(prompt: CoveragePrompt) -> tuple[CoveragePrompt, ...]:
  return tuple(
    CoveragePrompt(
      question_id=prompt.question_id,
      question_prompt=prompt.question_prompt,
      reference_material=prompt.reference_material,
      coverage_units=prompt.coverage_units,
      answers=prompt.answers[offset : offset + _COVERAGE_BATCH_SIZE],
    )
    for offset in range(0, len(prompt.answers), _COVERAGE_BATCH_SIZE)
  )


def _validated_coverage(
  output: CoverageClassificationOutput,
  prompt: CoveragePrompt,
) -> _ValidatedCoverage:
  unit_order = tuple(unit.id for unit in prompt.coverage_units)
  return _ValidatedCoverage(
    by_participant={
      assignment.participant_id: tuple(unit_id for unit_id in unit_order if unit_id in set(assignment.covered_unit_ids))
      for assignment in output.assignments
    }
  )


def _family_errors(
  output: FamilyClusteringOutput,
  prompt: FamilyPrompt,
) -> tuple[str, ...]:
  errors: list[str] = []
  expected_participants = {answer.participant_id for answer in prompt.answers}
  assignment_ids = [assignment.participant_id for assignment in output.assignments]
  counts = Counter(assignment_ids)
  if set(assignment_ids) != expected_participants:
    errors.append("assignments must cover exactly the supplied participant IDs")
  if any(count > 1 for count in counts.values()):
    errors.append("participant assignments must not be duplicated")
  labels = [family.label for family in output.families]
  if any(not label.strip() or label != label.strip() for label in labels):
    errors.append("family labels must be non-empty and trimmed")
  if len({label.casefold() for label in labels}) != len(labels):
    errors.append("family labels must be unique")
  used_indices: set[int] = set()
  for index, assignment in enumerate(output.assignments):
    family_index = assignment.family_index
    if family_index is None:
      continue
    if family_index < 0 or family_index >= len(labels):
      errors.append(f"assignment[{index}] familyIndex is out of range")
    else:
      used_indices.add(family_index)
  if used_indices != set(range(len(labels))):
    errors.append("every declared family must be used")
  if not used_indices and labels:
    errors.append("families must be empty when every assignment is null")
  return tuple(errors[:40])


def _validated_families(
  output: FamilyClusteringOutput,
  prompt: FamilyPrompt,
) -> _ValidatedFamilies:
  indexed_labels = list(enumerate(family.label for family in output.families))
  indexed_labels.sort(key=lambda item: (item[1].casefold(), item[1]))
  family_id_by_original_index: dict[int, str] = {}
  families: list[ResponseFamily] = []
  for original_index, label in indexed_labels:
    family_id = f"f_{uuid5(_FAMILY_NAMESPACE, f'{prompt.question_id}:{label}').hex}"
    family_id_by_original_index[original_index] = family_id
    families.append(ResponseFamily(id=family_id, label=label))
  return _ValidatedFamilies(
    families=tuple(families),
    family_by_participant={
      assignment.participant_id: (
        None if assignment.family_index is None else family_id_by_original_index[assignment.family_index]
      )
      for assignment in output.assignments
    },
  )


def _normalize_line_endings(value: str) -> str:
  return value.replace("\r\n", "\n").replace("\r", "\n")


def _normalized_empty(value: str) -> bool:
  return not value.strip()


def _message_bytes(messages: Sequence[dict[str, str]]) -> int:
  return sum(len(message["content"].encode("utf-8")) for message in messages)


def _schema_bytes(output_type: type[BaseModel]) -> int:
  schema = json.dumps(
    output_type.model_json_schema(by_alias=True),
    ensure_ascii=False,
    separators=(",", ":"),
  )
  return len(schema.encode("utf-8"))


def _invalid_input_error() -> SemanticCompilerError:
  return SemanticCompilerError(
    "SEMANTIC_INPUT_INVALID",
    "The frozen room input is outside the semantic-analysis contract.",
  )


def _invalid_output_error() -> SemanticCompilerError:
  return SemanticCompilerError(
    "SEMANTIC_OUTPUT_INVALID",
    "Response analysis returned inconsistent structured data after one repair attempt.",
  )


def _log_validation(branch: str, outcome: str) -> None:
  _LOG.info(
    "semantic_validation",
    extra={"junto_branch": branch, "junto_validation_outcome": outcome},
  )
