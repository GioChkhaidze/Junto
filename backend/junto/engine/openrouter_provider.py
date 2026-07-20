from __future__ import annotations

from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

from junto.engine.openrouter import OpenRouterCompletion, OpenRouterError
from junto.engine.prompts import (
  CoveragePrompt,
  FamilyPrompt,
  RepairPrompt,
  coverage_messages,
  family_messages,
)
from junto.engine.provider import (
  CoverageClassificationOutput,
  FamilyClusteringOutput,
  ProviderInvalidOutput,
  ProviderPermanentError,
  ProviderRefusalError,
  ProviderRepair,
  ProviderResult,
  ProviderTelemetry,
  ProviderTransientError,
)

T = TypeVar("T", bound=BaseModel)


class StructuredCompletionClient(Protocol):
  async def complete(
    self,
    *,
    model: str,
    messages: list[dict[str, str]],
    output_type: type[T],
    max_tokens: int,
  ) -> OpenRouterCompletion[T]: ...


class OpenRouterSemanticProvider:
  """Semantic-provider adapter for OpenRouter's strict Chat Completions output."""

  def __init__(
    self,
    *,
    client: StructuredCompletionClient,
    model: str,
    max_output_tokens: int = 12_000,
  ) -> None:
    if not model.strip():
      raise ValueError("model must not be empty")
    if max_output_tokens <= 0:
      raise ValueError("max_output_tokens must be positive")
    self._client = client
    self._model = model.strip()
    self._max_output_tokens = max_output_tokens

  @property
  def model_name(self) -> str:
    return self._model

  async def classify_coverage(
    self,
    prompt: CoveragePrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[CoverageClassificationOutput]:
    return await self._complete(
      branch="coverage",
      messages=coverage_messages(
        prompt,
        repair=_repair_prompt("coverage", repair, CoverageClassificationOutput),
      ),
      output_type=CoverageClassificationOutput,
    )

  async def cluster_families(
    self,
    prompt: FamilyPrompt,
    *,
    repair: ProviderRepair | None = None,
  ) -> ProviderResult[FamilyClusteringOutput]:
    return await self._complete(
      branch="family",
      messages=family_messages(
        prompt,
        repair=_repair_prompt("family", repair, FamilyClusteringOutput),
      ),
      output_type=FamilyClusteringOutput,
    )

  async def _complete(
    self,
    *,
    branch: Literal["coverage", "family"],
    messages: list[dict[str, str]],
    output_type: type[T],
  ) -> ProviderResult[T]:
    try:
      completion = await self._client.complete(
        model=self._model,
        messages=messages,
        output_type=output_type,
        max_tokens=self._max_output_tokens,
      )
    except OpenRouterError as error:
      if error.category == "transient":
        raise ProviderTransientError() from None
      if error.category == "refusal":
        raise ProviderRefusalError("The semantic provider declined the request.") from None
      if error.category == "invalid":
        raise ProviderInvalidOutput(
          {"result": "schema_mismatch"},
          (f"{branch} structured result was invalid",),
        ) from None
      raise ProviderPermanentError() from None

    usage = completion.usage
    return ProviderResult(
      value=completion.value,
      telemetry=ProviderTelemetry(
        request_id=usage.request_id,
        elapsed_milliseconds=usage.elapsed_milliseconds,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        total_tokens=usage.total_tokens,
      ),
    )


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
