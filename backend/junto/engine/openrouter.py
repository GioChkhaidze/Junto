from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Generic, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
OpenRouterCategory = Literal["transient", "permanent", "refusal", "invalid"]
OpenRouterReason = Literal[
  "unspecified",
  "transport",
  "http_status",
  "response_json",
  "response_shape",
  "finish_error",
  "finish_length",
  "finish_other",
  "schema",
  "schema_json",
  "schema_answer_count",
  "schema_answer_too_long",
  "schema_shape",
]


class OpenRouterError(RuntimeError):
  """A content-free OpenRouter failure safe to map at an application boundary."""

  def __init__(
    self,
    category: OpenRouterCategory,
    reason: OpenRouterReason = "unspecified",
  ) -> None:
    super().__init__(f"OpenRouter request failed: {category}/{reason}.")
    self.category = category
    self.reason = reason


@dataclass(frozen=True, slots=True)
class OpenRouterUsage:
  request_id: str | None
  model: str
  input_tokens: int
  output_tokens: int
  reasoning_tokens: int
  total_tokens: int
  elapsed_milliseconds: int


@dataclass(frozen=True, slots=True)
class OpenRouterCompletion(Generic[T]):
  value: T
  usage: OpenRouterUsage


class OpenRouterStructuredClient:
  """Small strict-JSON client shared by authoring, semantic analysis, and simulation."""

  def __init__(
    self,
    *,
    api_key: str,
    timeout_seconds: float = 45.0,
    base_url: str = "https://openrouter.ai/api/v1",
  ) -> None:
    if not api_key.strip():
      raise ValueError("OpenRouter API key must not be empty.")
    if timeout_seconds <= 0:
      raise ValueError("OpenRouter timeout must be positive.")
    self._api_key = api_key
    self._timeout_seconds = timeout_seconds
    self._base_url = base_url.rstrip("/")

  async def complete(
    self,
    *,
    model: str,
    messages: list[dict[str, str]],
    output_type: type[T],
    max_tokens: int,
    temperature: float = 0,
    reasoning_max_tokens: int | None = None,
    exclude_reasoning: bool = False,
  ) -> OpenRouterCompletion[T]:
    if not model.strip() or not _is_positive_int(max_tokens):
      raise ValueError("OpenRouter model and max_tokens are required.")
    if not 0 <= temperature <= 2:
      raise ValueError("OpenRouter temperature must be between 0 and 2.")
    if reasoning_max_tokens is not None:
      if not _is_positive_int(reasoning_max_tokens):
        raise ValueError("OpenRouter reasoning_max_tokens must be positive.")
      if reasoning_max_tokens >= max_tokens:
        raise ValueError("OpenRouter max_tokens must exceed reasoning_max_tokens.")
    body = self._body(
      model=model,
      messages=messages,
      output_type=output_type,
      max_tokens=max_tokens,
      temperature=temperature,
      reasoning_max_tokens=reasoning_max_tokens,
      exclude_reasoning=exclude_reasoning,
    )
    started = perf_counter()
    try:
      async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
        response = await client.post(
          f"{self._base_url}/chat/completions",
          headers={
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://junto.local",
            "X-OpenRouter-Title": "Junto",
          },
          json=body,
        )
    except (httpx.TimeoutException, httpx.TransportError):
      raise OpenRouterError("transient", "transport") from None

    elapsed = max(0, round((perf_counter() - started) * 1_000))
    if response.status_code >= 400:
      category: Literal["transient", "permanent"] = (
        "transient" if response.status_code in {408, 409, 429} or response.status_code >= 500 else "permanent"
      )
      raise OpenRouterError(category, "http_status")
    try:
      payload = response.json()
    except ValueError:
      raise OpenRouterError("invalid", "response_json") from None
    usage = _usage(payload, elapsed=elapsed)
    try:
      choice = payload["choices"][0]
      finish_reason = choice["finish_reason"]
      content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
      raise OpenRouterError("invalid", "response_shape") from None
    if finish_reason == "content_filter":
      raise OpenRouterError("refusal", "finish_other")
    if finish_reason == "error":
      raise OpenRouterError("transient", "finish_error")
    if finish_reason == "length":
      raise OpenRouterError("permanent", "finish_length")
    if finish_reason != "stop" or not isinstance(content, str):
      raise OpenRouterError("permanent", "finish_other")
    try:
      value = output_type.model_validate_json(content)
    except ValidationError as error:
      raise OpenRouterError("invalid", _schema_reason(error)) from None
    return OpenRouterCompletion(value=value, usage=usage)

  def _body(
    self,
    *,
    model: str,
    messages: list[dict[str, str]],
    output_type: type[BaseModel],
    max_tokens: int,
    temperature: float,
    reasoning_max_tokens: int | None,
    exclude_reasoning: bool,
  ) -> dict[str, object]:
    normalized_messages = [
      {
        "role": "system" if message["role"] == "developer" else message["role"],
        "content": message["content"],
      }
      for message in messages
    ]
    body: dict[str, object] = {
      "model": model,
      "messages": normalized_messages,
      "temperature": temperature,
      "max_tokens": max_tokens,
      "response_format": {
        "type": "json_schema",
        "json_schema": {
          "name": output_type.__name__.lower(),
          "strict": True,
          "schema": _provider_schema(output_type.model_json_schema(by_alias=True)),
        },
      },
      "provider": {
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
      },
    }
    if reasoning_max_tokens is not None or exclude_reasoning:
      reasoning: dict[str, object] = {}
      if reasoning_max_tokens is not None:
        reasoning["max_tokens"] = reasoning_max_tokens
      if exclude_reasoning:
        reasoning["exclude"] = True
      body["reasoning"] = reasoning
    return body


def _usage(payload: object, *, elapsed: int) -> OpenRouterUsage:
  if not isinstance(payload, dict):
    return OpenRouterUsage(None, "unknown", 0, 0, 0, 0, elapsed)
  usage = payload.get("usage")
  usage = usage if isinstance(usage, dict) else {}
  details = usage.get("completion_tokens_details")
  details = details if isinstance(details, dict) else {}
  return OpenRouterUsage(
    request_id=_bounded_string(payload.get("id"), 200),
    model=_bounded_string(payload.get("model"), 200) or "unknown",
    input_tokens=_nonnegative_int(usage.get("prompt_tokens")),
    output_tokens=_nonnegative_int(usage.get("completion_tokens")),
    reasoning_tokens=_nonnegative_int(details.get("reasoning_tokens")),
    total_tokens=_nonnegative_int(usage.get("total_tokens")),
    elapsed_milliseconds=elapsed,
  )


def _nonnegative_int(value: object) -> int:
  return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _schema_reason(error: ValidationError) -> OpenRouterReason:
  failures = tuple(
    (detail["type"], detail["loc"])
    for detail in error.errors(include_url=False, include_context=False, include_input=False)
  )
  if any(error_type == "json_invalid" for error_type, _location in failures):
    return "schema_json"
  if any(
    error_type == "string_too_long" and location and location[0] == "answers" for error_type, location in failures
  ):
    return "schema_answer_too_long"
  if any(
    error_type in {"too_short", "too_long"} and location and location[0] == "answers"
    for error_type, location in failures
  ):
    return "schema_answer_count"
  shape_errors = {"missing", "extra_forbidden", "list_type", "string_type", "model_type", "dict_type"}
  if any(error_type in shape_errors for error_type, _location in failures):
    return "schema_shape"
  return "schema"


def _is_positive_int(value: object) -> bool:
  return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _bounded_string(value: object, maximum: int) -> str | None:
  return value if isinstance(value, str) and 0 < len(value) <= maximum else None


def _provider_schema(value: object) -> object:
  if isinstance(value, dict):
    return {key: _provider_schema(child) for key, child in value.items() if key != "maxItems"}
  if isinstance(value, list):
    return [_provider_schema(child) for child in value]
  return value
