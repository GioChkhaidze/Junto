from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Generic, Literal, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from junto.engine.prompts import (
  CoveragePrompt,
  FamilyPrompt,
  PromptAnswer,
  PromptCoverageUnit,
  RepairPrompt,
  coverage_messages,
  family_messages,
)

_LOG = logging.getLogger("junto.semantic.provider")

ParticipantId = Annotated[str, Field(min_length=1, max_length=64)]
UnitId = Annotated[str, Field(min_length=1, max_length=80)]
EvidenceQuote = Annotated[str, Field(min_length=1, max_length=240)]
FamilyLabel = Annotated[str, Field(min_length=1, max_length=120)]


class _StrictOutput(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=False)


class CoverageEvidenceOutput(_StrictOutput):
  unit_id: UnitId = Field(alias="unitId")
  quotes: list[EvidenceQuote] = Field(min_length=1, max_length=2)


class CoverageAssignmentOutput(_StrictOutput):
  participant_id: ParticipantId = Field(alias="participantId")
  covered_unit_ids: list[UnitId] = Field(alias="coveredUnitIds", max_length=8)
  evidence: list[CoverageEvidenceOutput] = Field(max_length=8)


class CoverageClassificationOutput(_StrictOutput):
  assignments: list[CoverageAssignmentOutput] = Field(max_length=200)


class FamilyOutput(_StrictOutput):
  label: FamilyLabel


class FamilyAssignmentOutput(_StrictOutput):
  participant_id: ParticipantId = Field(alias="participantId")
  family_index: int | None = Field(alias="familyIndex")


class FamilyClusteringOutput(_StrictOutput):
  families: list[FamilyOutput] = Field(max_length=200)
  assignments: list[FamilyAssignmentOutput] = Field(max_length=200)


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ProviderTelemetry:
  request_id: str | None
  elapsed_milliseconds: int
  input_tokens: int = 0
  output_tokens: int = 0
  reasoning_tokens: int = 0
  total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderResult(Generic[T]):
  value: T
  telemetry: ProviderTelemetry


@dataclass(frozen=True, slots=True)
class ProviderRepair:
  invalid_result: object
  validation_errors: tuple[str, ...]


class ProviderError(RuntimeError):
  """A caller-safe provider failure that never contains room text."""

  code = "PROVIDER_ERROR"

  def __init__(self, message: str = "The semantic provider could not complete the request."):
    super().__init__(message)


class ProviderTransientError(ProviderError):
  code = "PROVIDER_TRANSIENT"


class ProviderPermanentError(ProviderError):
  code = "PROVIDER_PERMANENT"


class ProviderRefusalError(ProviderError):
  code = "PROVIDER_REFUSAL"


class ProviderInvalidOutput(ProviderError):
  code = "PROVIDER_INVALID_OUTPUT"

  def __init__(self, invalid_result: object, validation_errors: tuple[str, ...]):
    super().__init__("The semantic provider returned an invalid structured result.")
    self.invalid_result = invalid_result
    self.validation_errors = validation_errors


class SemanticProvider(Protocol):
  @property
  def model_name(self) -> str: ...

  async def classify_coverage(
    self,
    prompt: CoveragePrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[CoverageClassificationOutput]: ...

  async def cluster_families(
    self,
    prompt: FamilyPrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[FamilyClusteringOutput]: ...


class _ResponsesClient(Protocol):
  async def parse(self, **kwargs: Any) -> Any: ...


class _OpenAIClient(Protocol):
  responses: _ResponsesClient

  async def close(self) -> None: ...


class OpenAISemanticProvider:
  """Official Responses API adapter with Pydantic-backed Structured Outputs."""

  def __init__(
    self,
    *,
    client: _OpenAIClient | None = None,
    model: str,
    sdk_timeout_seconds: float = 45.0,
    max_output_tokens: int = 20_000,
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = "low",
    safety_identifier: str | None = None,
    _client_factory: Callable[[], _OpenAIClient] | None = None,
  ) -> None:
    if not model.strip():
      raise ValueError("model must not be empty")
    if sdk_timeout_seconds <= 0:
      raise ValueError("sdk_timeout_seconds must be positive")
    if max_output_tokens <= 0:
      raise ValueError("max_output_tokens must be positive")
    if (client is None) == (_client_factory is None):
      raise ValueError("provide exactly one OpenAI client or client factory")
    self._client = client
    self._client_factory = _client_factory
    self._model = model.strip()
    self._sdk_timeout_seconds = sdk_timeout_seconds
    self._max_output_tokens = max_output_tokens
    self._reasoning_effort = reasoning_effort
    self._safety_identifier = safety_identifier

  @classmethod
  def from_api_key(
    cls,
    *,
    api_key: str,
    model: str,
    sdk_timeout_seconds: float = 45.0,
    max_output_tokens: int = 20_000,
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = "low",
    safety_identifier: str | None = None,
  ) -> OpenAISemanticProvider:
    """Create the adapter lazily so recorded CI does not require SDK initialization."""
    if not api_key.strip():
      raise ValueError("api_key must not be empty")
    openai = import_module("openai")

    # The compiler owns the single explicit transport retry allowance. Disabling the
    # SDK's implicit retries keeps the documented HTTP-request cap enforceable.
    def client_factory() -> _OpenAIClient:
      # Each compiler invocation runs inside a transient event loop owned by
      # its analysis thread. Async HTTP clients cannot be reused after that
      # loop closes, so live requests create and close their client in the
      # loop that performs the request.
      return cast(
        _OpenAIClient,
        openai.AsyncOpenAI(api_key=api_key, max_retries=0),
      )

    return cls(
      _client_factory=client_factory,
      model=model,
      sdk_timeout_seconds=sdk_timeout_seconds,
      max_output_tokens=max_output_tokens,
      reasoning_effort=reasoning_effort,
      safety_identifier=safety_identifier,
    )

  @property
  def model_name(self) -> str:
    return self._model

  async def classify_coverage(
    self,
    prompt: CoveragePrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[CoverageClassificationOutput]:
    repair_prompt = _repair_prompt("coverage", repair, CoverageClassificationOutput)
    return await self._parse(
      branch="coverage",
      input_messages=coverage_messages(prompt, repair=repair_prompt),
      output_type=CoverageClassificationOutput,
      repair=repair is not None,
    )

  async def cluster_families(
    self,
    prompt: FamilyPrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[FamilyClusteringOutput]:
    repair_prompt = _repair_prompt("family", repair, FamilyClusteringOutput)
    return await self._parse(
      branch="family",
      input_messages=family_messages(prompt, repair=repair_prompt),
      output_type=FamilyClusteringOutput,
      repair=repair is not None,
    )

  async def _parse(
    self,
    *,
    branch: Literal["coverage", "family"],
    input_messages: list[dict[str, str]],
    output_type: type[T],
    repair: bool,
  ) -> ProviderResult[T]:
    started = perf_counter()
    kwargs: dict[str, Any] = {
      "model": self._model,
      "input": input_messages,
      "text_format": output_type,
      "store": False,
      "tools": [],
      "max_output_tokens": self._max_output_tokens,
      "timeout": self._sdk_timeout_seconds,
    }
    if self._reasoning_effort is not None:
      kwargs["reasoning"] = {"effort": self._reasoning_effort}
    if self._safety_identifier:
      kwargs["safety_identifier"] = self._safety_identifier
    try:
      response = await self._parse_response(kwargs)
    except ValidationError as error:
      elapsed = _elapsed_ms(started)
      _log_call(branch, repair, "invalid", None, elapsed)
      raise ProviderInvalidOutput(
        {"result": "schema_mismatch"},
        _safe_validation_errors(error),
      ) from None
    except Exception as error:
      elapsed = _elapsed_ms(started)
      request_id = _safe_request_id(error)
      _log_call(branch, repair, "transport_error", request_id, elapsed)
      if type(error).__name__ == "ContentFilterFinishReasonError":
        raise ProviderRefusalError("The semantic provider declined the request.") from None
      if _is_transient(error):
        raise ProviderTransientError() from None
      raise ProviderPermanentError() from None

    elapsed = _elapsed_ms(started)
    request_id = _safe_request_id(response)
    usage = _safe_usage(response)
    if _has_refusal(response):
      _log_call(branch, repair, "refusal", request_id, elapsed, usage)
      raise ProviderRefusalError("The semantic provider declined the request.")
    status = getattr(response, "status", None)
    if status == "incomplete":
      _log_call(branch, repair, "incomplete", request_id, elapsed, usage)
      raise ProviderTransientError("The semantic provider returned an incomplete response.")
    if status != "completed":
      _log_call(branch, repair, "failed", request_id, elapsed, usage)
      raise ProviderPermanentError("The semantic provider did not complete the request.")
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
      _log_call(branch, repair, "invalid", request_id, elapsed, usage)
      raise ProviderInvalidOutput(
        {"result": "unparseable"},
        ("structured result was missing",),
      )
    try:
      value = parsed if isinstance(parsed, output_type) else output_type.model_validate(parsed)
    except ValidationError as error:
      _log_call(branch, repair, "invalid", request_id, elapsed, usage)
      raise ProviderInvalidOutput(
        {"result": "schema_mismatch"},
        _safe_validation_errors(error),
      ) from None
    _log_call(branch, repair, "ok", request_id, elapsed, usage)
    return ProviderResult(
      value=value,
      telemetry=ProviderTelemetry(
        request_id=request_id,
        elapsed_milliseconds=elapsed,
        input_tokens=usage[0],
        output_tokens=usage[1],
        reasoning_tokens=usage[2],
        total_tokens=usage[3],
      ),
    )

  async def _parse_response(self, kwargs: dict[str, Any]) -> Any:
    if self._client_factory is None:
      if self._client is None:  # constructor invariant
        raise RuntimeError("OpenAI client is unavailable")
      return await self._client.responses.parse(**kwargs)

    client = self._client_factory()
    try:
      return await client.responses.parse(**kwargs)
    finally:
      await client.close()


RecordedStep = Mapping[str, object] | BaseException


@dataclass(frozen=True, slots=True)
class RecordedProviderCall:
  branch: Literal["coverage", "family"]
  question_id: str
  repair: bool
  answer_count: int
  participant_ids: tuple[str, ...]
  unit_ids: tuple[str, ...]
  includes_reference: bool


@dataclass(frozen=True, slots=True)
class _RecordedFixtureTemplate:
  question_prompt: str
  coverage_units: tuple[tuple[str, str], ...]
  participants: tuple[tuple[str, str], ...]
  coverage: dict[str, object]
  family: dict[str, object]


class RecordedSemanticProvider:
  """Deterministic, network-free provider used by CI and reviewed evaluations."""

  def __init__(
    self,
    records: Mapping[
      str,
      Mapping[Literal["coverage", "family"], Sequence[RecordedStep] | RecordedStep],
    ],
    *,
    model_name: str = "recorded-semantic-v1",
    _fixture_templates: tuple[_RecordedFixtureTemplate, ...] = (),
  ) -> None:
    self._model_name = model_name
    self._records = {
      question_id: {branch: _steps(branch_records) for branch, branch_records in question_records.items()}
      for question_id, question_records in records.items()
    }
    self._positions: dict[tuple[str, str], int] = {}
    self._fixture_templates = _fixture_templates
    self.calls: list[RecordedProviderCall] = []

  @classmethod
  def from_fixture_files(
    cls,
    paths: Sequence[Path],
    *,
    model_name: str = "recorded-semantic-v1",
  ) -> RecordedSemanticProvider:
    records: dict[str, dict[Literal["coverage", "family"], RecordedStep]] = {}
    templates: list[_RecordedFixtureTemplate] = []
    for path in paths:
      fixture = json.loads(path.read_text(encoding="utf-8"))
      if not isinstance(fixture, dict):
        raise ValueError("a semantic fixture must be a JSON object")
      question_id = fixture.get("questionId")
      coverage = fixture.get("expectedCoverage")
      families = fixture.get("expectedFamilies")
      if not isinstance(question_id, str) or not isinstance(coverage, dict) or not isinstance(families, dict):
        raise ValueError("a semantic fixture is missing recorded provider outputs")
      if question_id in records:
        raise ValueError("semantic fixture question IDs must be unique")
      question_prompt = fixture.get("questionPrompt")
      raw_units = fixture.get("coverageUnits")
      raw_participants = fixture.get("participants")
      if (
        not isinstance(question_prompt, str)
        or not isinstance(raw_units, list)
        or not isinstance(raw_participants, list)
      ):
        raise ValueError("a semantic fixture is missing exact-match inputs")
      try:
        units = tuple((str(item["id"]), str(item["text"])) for item in raw_units)
        participants = tuple((str(item["participantId"]), str(item["answer"])) for item in raw_participants)
      except (KeyError, TypeError):
        raise ValueError("a semantic fixture has malformed exact-match inputs") from None
      CoverageClassificationOutput.model_validate(coverage)
      FamilyClusteringOutput.model_validate(families)
      records[question_id] = {"coverage": coverage, "family": families}
      templates.append(
        _RecordedFixtureTemplate(
          question_prompt=question_prompt,
          coverage_units=units,
          participants=participants,
          coverage=coverage,
          family=families,
        )
      )
    return cls(
      records,
      model_name=model_name,
      _fixture_templates=tuple(templates),
    )

  @property
  def model_name(self) -> str:
    return self._model_name

  async def classify_coverage(
    self,
    prompt: CoveragePrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[CoverageClassificationOutput]:
    self.calls.append(
      RecordedProviderCall(
        branch="coverage",
        question_id=prompt.question_id,
        repair=repair is not None,
        answer_count=len(prompt.answers),
        participant_ids=tuple(answer.participant_id for answer in prompt.answers),
        unit_ids=tuple(unit.id for unit in prompt.coverage_units),
        includes_reference=prompt.reference_material is not None,
      )
    )
    return self._recorded_result(
      prompt.question_id,
      "coverage",
      CoverageClassificationOutput,
      prompt,
    )

  async def cluster_families(
    self,
    prompt: FamilyPrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[FamilyClusteringOutput]:
    self.calls.append(
      RecordedProviderCall(
        branch="family",
        question_id=prompt.question_id,
        repair=repair is not None,
        answer_count=len(prompt.answers),
        participant_ids=tuple(answer.participant_id for answer in prompt.answers),
        unit_ids=(),
        includes_reference=False,
      )
    )
    return self._recorded_result(
      prompt.question_id,
      "family",
      FamilyClusteringOutput,
      prompt,
    )

  def _recorded_result(
    self,
    question_id: str,
    branch: Literal["coverage", "family"],
    output_type: type[T],
    prompt: CoveragePrompt | FamilyPrompt,
  ) -> ProviderResult[T]:
    key = (question_id, branch)
    try:
      steps = self._records[question_id][branch]
    except KeyError:
      remapped = self._exact_fixture_result(branch, prompt)
      if remapped is None:
        raise ProviderPermanentError("No recorded semantic response exists.") from None
      steps = (remapped,)
    position = self._positions.get(key, 0)
    if position >= len(steps):
      raise ProviderPermanentError("The recorded semantic responses are exhausted.")
    self._positions[key] = position + 1
    step = steps[position]
    if isinstance(step, BaseException):
      raise step
    try:
      value = output_type.model_validate(step)
    except ValidationError as error:
      raise ProviderInvalidOutput(dict(step), _safe_validation_errors(error)) from None
    return ProviderResult(
      value=value,
      telemetry=ProviderTelemetry(
        request_id=f"recorded-{branch}-{position + 1}",
        elapsed_milliseconds=0,
      ),
    )

  def _exact_fixture_result(
    self,
    branch: Literal["coverage", "family"],
    prompt: CoveragePrompt | FamilyPrompt,
  ) -> dict[str, object] | None:
    matches: list[dict[str, object]] = []
    for fixture in self._fixture_templates:
      if fixture.question_prompt != prompt.question_prompt:
        continue
      participant_mappings = _match_fixture_participants(fixture, prompt.answers)
      if participant_mappings is None:
        continue
      unit_ids: dict[str, str] = {}
      if branch == "coverage":
        if not isinstance(prompt, CoveragePrompt):
          continue
        mapped_units = _match_fixture_units(fixture, prompt.coverage_units)
        if mapped_units is None:
          continue
        unit_ids = mapped_units
      matches.append(
        _remap_fixture_output(
          fixture,
          branch,
          participant_mappings,
          unit_ids,
        )
      )
    if len(matches) > 1:
      raise ProviderPermanentError("The recorded semantic fixture match is ambiguous.")
    return matches[0] if matches else None


def _repair_prompt(
  branch: Literal["coverage", "family"],
  repair: ProviderRepair | None,
  output_type: type[BaseModel],
) -> RepairPrompt | None:
  if repair is None:
    return None
  return RepairPrompt(
    branch=branch,
    invalid_result=repair.invalid_result,
    validation_errors=repair.validation_errors,
    schema=output_type.model_json_schema(by_alias=True),
  )


def _match_fixture_participants(
  fixture: _RecordedFixtureTemplate,
  answers: tuple[PromptAnswer, ...],
) -> tuple[tuple[str, str], ...] | None:
  fixture_answers = [item for item in fixture.participants if item[1].strip()]
  fixture_by_answer: dict[str, str] = {}
  for fixture_participant_id, text in fixture_answers:
    if text in fixture_by_answer:
      # One exact answer cannot safely select two different adjudicated assignments.
      return None
    fixture_by_answer[text] = fixture_participant_id
  mappings: list[tuple[str, str]] = []
  for answer in answers:
    matched_participant_id = fixture_by_answer.get(answer.text)
    if matched_participant_id is None:
      return None
    mappings.append((answer.participant_id, matched_participant_id))
  if len({runtime_id for runtime_id, _fixture_id in mappings}) != len(mappings):
    return None
  return tuple(mappings)


def _match_fixture_units(
  fixture: _RecordedFixtureTemplate,
  units: tuple[PromptCoverageUnit, ...],
) -> dict[str, str] | None:
  fixture_by_text: dict[str, str] = {}
  for unit_id, text in fixture.coverage_units:
    if text in fixture_by_text:
      return None
    fixture_by_text[text] = unit_id
  current_by_text: dict[str, str] = {}
  for unit in units:
    if unit.text in current_by_text:
      return None
    current_by_text[unit.text] = unit.id
  if set(fixture_by_text) != set(current_by_text):
    return None
  return {fixture_unit_id: current_by_text[text] for text, fixture_unit_id in fixture_by_text.items()}


def _remap_fixture_output(
  fixture: _RecordedFixtureTemplate,
  branch: Literal["coverage", "family"],
  participant_mappings: tuple[tuple[str, str], ...],
  unit_ids: Mapping[str, str],
) -> dict[str, object]:
  result = deepcopy(fixture.coverage if branch == "coverage" else fixture.family)
  assignments = result.get("assignments")
  if not isinstance(assignments, list):
    raise ProviderPermanentError("The recorded semantic fixture is malformed.")
  try:
    source_by_participant = {str(assignment["participantId"]): assignment for assignment in assignments}
    if len(source_by_participant) != len(assignments):
      raise ProviderPermanentError("The recorded semantic fixture is malformed.")
    remapped_assignments: list[dict[str, object]] = []
    for runtime_participant_id, fixture_participant_id in participant_mappings:
      assignment = deepcopy(source_by_participant[fixture_participant_id])
      assignment["participantId"] = runtime_participant_id
      if branch == "coverage":
        assignment["coveredUnitIds"] = [unit_ids[str(unit_id)] for unit_id in assignment["coveredUnitIds"]]
        for evidence in assignment["evidence"]:
          evidence["unitId"] = unit_ids[str(evidence["unitId"])]
      remapped_assignments.append(assignment)
    result["assignments"] = remapped_assignments
    if branch == "family":
      _remove_unused_fixture_families(result, remapped_assignments)
  except (KeyError, TypeError):
    raise ProviderPermanentError("The recorded semantic fixture is malformed.") from None
  return result


def _remove_unused_fixture_families(
  result: dict[str, object],
  assignments: list[dict[str, object]],
) -> None:
  families = result.get("families")
  if not isinstance(families, list):
    raise ProviderPermanentError("The recorded semantic fixture is malformed.")
  used_indices = sorted(
    {
      family_index
      for assignment in assignments
      if isinstance((family_index := assignment.get("familyIndex")), int) and not isinstance(family_index, bool)
    }
  )
  if any(index < 0 or index >= len(families) for index in used_indices):
    raise ProviderPermanentError("The recorded semantic fixture is malformed.")
  new_index = {old_index: index for index, old_index in enumerate(used_indices)}
  result["families"] = [families[index] for index in used_indices]
  for assignment in assignments:
    family_index = assignment.get("familyIndex")
    if isinstance(family_index, int) and not isinstance(family_index, bool):
      assignment["familyIndex"] = new_index[family_index]
    elif family_index is not None:
      raise ProviderPermanentError("The recorded semantic fixture is malformed.")


def _steps(value: Sequence[RecordedStep] | RecordedStep) -> tuple[RecordedStep, ...]:
  if isinstance(value, BaseException | Mapping):
    return (value,)
  return tuple(value)


def _safe_validation_errors(error: ValidationError) -> tuple[str, ...]:
  safe: list[str] = []
  for item in error.errors(include_input=False, include_url=False):
    location = ".".join(str(part) for part in item["loc"])
    safe.append(f"{location or 'result'}: {item['type']}")
  return tuple(safe[:20]) or ("structured result was invalid",)


def _has_refusal(response: object) -> bool:
  for item in getattr(response, "output", ()) or ():
    if getattr(item, "type", None) != "message":
      continue
    for content in getattr(item, "content", ()) or ():
      if getattr(content, "type", None) == "refusal":
        return True
  return False


def _safe_request_id(value: object) -> str | None:
  request_id = getattr(value, "_request_id", None) or getattr(value, "request_id", None)
  return request_id if isinstance(request_id, str) and len(request_id) <= 200 else None


def _safe_usage(response: object) -> tuple[int, int, int, int]:
  usage = getattr(response, "usage", None)
  input_tokens = _nonnegative_int(getattr(usage, "input_tokens", 0))
  output_tokens = _nonnegative_int(getattr(usage, "output_tokens", 0))
  output_details = getattr(usage, "output_tokens_details", None)
  reasoning_tokens = _nonnegative_int(getattr(output_details, "reasoning_tokens", 0))
  total_tokens = _nonnegative_int(getattr(usage, "total_tokens", input_tokens + output_tokens))
  return input_tokens, output_tokens, reasoning_tokens, total_tokens


def _nonnegative_int(value: object) -> int:
  return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _is_transient(error: Exception) -> bool:
  if isinstance(error, TimeoutError):
    return True
  status_code = getattr(error, "status_code", None)
  if isinstance(status_code, int) and (status_code in {408, 409, 429} or status_code >= 500):
    return True
  return type(error).__name__ in {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "LengthFinishReasonError",
    "RateLimitError",
  }


def _elapsed_ms(started: float) -> int:
  return max(0, round((perf_counter() - started) * 1000))


def _log_call(
  branch: str,
  repair: bool,
  outcome: str,
  request_id: str | None,
  elapsed_milliseconds: int,
  usage: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> None:
  _LOG.info(
    "semantic_provider_call",
    extra={
      "junto_branch": branch,
      "junto_repair": repair,
      "junto_outcome": outcome,
      "junto_request_id": request_id,
      "junto_elapsed_milliseconds": elapsed_milliseconds,
      "junto_input_tokens": usage[0],
      "junto_output_tokens": usage[1],
      "junto_reasoning_tokens": usage[2],
      "junto_total_tokens": usage[3],
    },
  )
