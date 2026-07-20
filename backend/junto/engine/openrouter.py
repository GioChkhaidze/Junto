from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Generic, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class OpenRouterError(RuntimeError):
  """A content-free OpenRouter failure safe to map at an application boundary."""

  def __init__(
    self,
    category: Literal["transient", "permanent", "refusal", "invalid"],
  ) -> None:
    super().__init__(f"OpenRouter request failed: {category}.")
    self.category = category


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
  """Small strict-JSON client shared by semantic evaluation and synthetic students."""

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
  ) -> OpenRouterCompletion[T]:
    if not model.strip() or max_tokens <= 0:
      raise ValueError("OpenRouter model and max_tokens are required.")
    body = self._body(
      model=model,
      messages=messages,
      output_type=output_type,
      max_tokens=max_tokens,
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
            "X-OpenRouter-Title": "Junto development evaluation",
          },
          json=body,
        )
    except (httpx.TimeoutException, httpx.TransportError):
      raise OpenRouterError("transient") from None

    elapsed = max(0, round((perf_counter() - started) * 1_000))
    if response.status_code >= 400:
      category: Literal["transient", "permanent"] = (
        "transient" if response.status_code in {408, 409, 429} or response.status_code >= 500 else "permanent"
      )
      raise OpenRouterError(category)
    try:
      payload = response.json()
    except ValueError:
      raise OpenRouterError("invalid") from None
    usage = _usage(payload, elapsed=elapsed)
    try:
      choice = payload["choices"][0]
      finish_reason = choice["finish_reason"]
      content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
      raise OpenRouterError("invalid") from None
    if finish_reason == "content_filter":
      raise OpenRouterError("refusal")
    if finish_reason == "length":
      raise OpenRouterError("transient")
    if finish_reason != "stop" or not isinstance(content, str):
      raise OpenRouterError("permanent")
    try:
      value = output_type.model_validate_json(content)
    except ValidationError:
      raise OpenRouterError("invalid") from None
    return OpenRouterCompletion(value=value, usage=usage)

  def _body(
    self,
    *,
    model: str,
    messages: list[dict[str, str]],
    output_type: type[BaseModel],
    max_tokens: int,
  ) -> dict[str, object]:
    normalized_messages = [
      {
        "role": "system" if message["role"] == "developer" else message["role"],
        "content": message["content"],
      }
      for message in messages
    ]
    return {
      "model": model,
      "messages": normalized_messages,
      "temperature": 0,
      "max_tokens": max_tokens,
      "response_format": {
        "type": "json_schema",
        "json_schema": {
          "name": output_type.__name__.lower(),
          "strict": True,
          "schema": output_type.model_json_schema(by_alias=True),
        },
      },
      "provider": {
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
      },
    }


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


def _bounded_string(value: object, maximum: int) -> str | None:
  return value if isinstance(value, str) and 0 < len(value) <= maximum else None
