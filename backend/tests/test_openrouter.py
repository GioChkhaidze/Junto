from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Literal

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from junto.engine.openrouter import (
  OpenRouterCompletion,
  OpenRouterError,
  OpenRouterStructuredClient,
  OpenRouterUsage,
)
from junto.engine.openrouter_provider import OpenRouterSemanticProvider
from junto.engine.prompts import (
  CoveragePrompt,
  FamilyPrompt,
  PromptAnswer,
  PromptCoverageUnit,
)
from junto.engine.provider import (
  CoverageClassificationOutput,
  FamilyClusteringOutput,
  ProviderInvalidOutput,
  ProviderPermanentError,
  ProviderRefusalError,
  ProviderRepair,
  ProviderTransientError,
)


class _StrictResult(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)

  answer: str


_ShortAnswer = Annotated[str, Field(max_length=5)]
_ExactAnswerRow = Annotated[list[_ShortAnswer], Field(min_length=2, max_length=2)]


class _ExactAnswers(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)

  answers: Annotated[list[_ExactAnswerRow], Field(min_length=2, max_length=2)]


class _PatternResult(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)

  answer: str = Field(pattern="^accepted$")


class _FakeAsyncClient:
  def __init__(
    self,
    response: httpx.Response | None = None,
    error: Exception | None = None,
  ) -> None:
    self._response = response
    self._error = error
    self.timeout: float | None = None
    self.requests: list[dict[str, Any]] = []

  def factory(self, *, timeout: float) -> _FakeAsyncClient:
    self.timeout = timeout
    return self

  async def __aenter__(self) -> _FakeAsyncClient:
    return self

  async def __aexit__(self, *_args: object) -> None:
    return None

  async def post(self, url: str, **kwargs: Any) -> httpx.Response:
    self.requests.append({"url": url, **kwargs})
    if self._error is not None:
      raise self._error
    if self._response is None:
      raise AssertionError("The fake OpenRouter client has no response.")
    return self._response


class _StructuredStub:
  def __init__(self, result: object) -> None:
    self._result = result
    self.calls: list[dict[str, Any]] = []

  async def complete(self, **kwargs: Any) -> Any:
    self.calls.append(kwargs)
    if isinstance(self._result, BaseException):
      raise self._result
    return self._result


def _response(
  content: str,
  *,
  finish_reason: str = "stop",
) -> httpx.Response:
  return httpx.Response(
    200,
    request=httpx.Request("POST", "https://openrouter.test/chat/completions"),
    json={
      "id": "request-1",
      "model": "test/model",
      "choices": [
        {
          "finish_reason": finish_reason,
          "message": {"content": content},
        }
      ],
      "usage": {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
        "completion_tokens_details": {"reasoning_tokens": 2},
      },
    },
  )


def _client() -> OpenRouterStructuredClient:
  return OpenRouterStructuredClient(
    api_key="test-key",
    timeout_seconds=7,
    base_url="https://openrouter.test",
  )


def test_strict_request_enforces_privacy_routing_and_schema_contract(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  transport = _FakeAsyncClient(_response('{"answer":"bounded"}'))
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  result = asyncio.run(
    _client().complete(
      model="test/model",
      messages=[
        {"role": "developer", "content": "Return one answer."},
        {"role": "user", "content": "Untrusted room question."},
      ],
      output_type=_StrictResult,
      max_tokens=200,
    )
  )

  assert result.value.answer == "bounded"
  assert result.usage.input_tokens == 12
  assert result.usage.output_tokens == 5
  assert result.usage.reasoning_tokens == 2
  assert transport.timeout == 7
  assert len(transport.requests) == 1
  request = transport.requests[0]
  assert request["url"] == "https://openrouter.test/chat/completions"
  assert request["headers"]["Authorization"] == "Bearer test-key"
  body = request["json"]
  assert body["messages"][0]["role"] == "system"
  assert body["temperature"] == 0
  assert body["max_tokens"] == 200
  assert "reasoning" not in body
  assert body["response_format"]["type"] == "json_schema"
  assert body["response_format"]["json_schema"]["strict"] is True
  schema = body["response_format"]["json_schema"]["schema"]
  assert schema["additionalProperties"] is False
  assert "maxItems" not in json.dumps(schema)
  assert body["provider"] == {
    "require_parameters": True,
    "data_collection": "deny",
    "zdr": True,
  }


def test_generation_temperature_can_vary_without_changing_semantic_default(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  transport = _FakeAsyncClient(_response('{"answer":"varied"}'))
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  asyncio.run(
    _client().complete(
      model="test/model",
      messages=[{"role": "user", "content": "Question"}],
      output_type=_StrictResult,
      max_tokens=100,
      temperature=0.65,
    )
  )

  assert transport.requests[0]["json"]["temperature"] == 0.65


def test_explicit_reasoning_limit_and_exclusion_are_sent(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  transport = _FakeAsyncClient(_response('{"answer":"bounded"}'))
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  asyncio.run(
    _client().complete(
      model="test/model",
      messages=[{"role": "user", "content": "Question"}],
      output_type=_StrictResult,
      max_tokens=3_000,
      reasoning_max_tokens=1_024,
      exclude_reasoning=True,
    )
  )

  assert transport.requests[0]["json"]["reasoning"] == {"max_tokens": 1_024, "exclude": True}


@pytest.mark.parametrize("reasoning_max_tokens", [True, 0, -1, 3_000])
def test_invalid_reasoning_limits_are_rejected(reasoning_max_tokens: int) -> None:
  with pytest.raises(ValueError):
    asyncio.run(
      _client().complete(
        model="test/model",
        messages=[{"role": "user", "content": "Question"}],
        output_type=_StrictResult,
        max_tokens=3_000,
        reasoning_max_tokens=reasoning_max_tokens,
      )
    )


@pytest.mark.parametrize(
  ("response", "category", "reason"),
  [
    (_response('{"answer":7}'), "invalid", "schema_shape"),
    (_response('{"answer":"no"}', finish_reason="content_filter"), "refusal", "finish_other"),
    (_response('{"answer":"partial"}', finish_reason="error"), "transient", "finish_error"),
    (_response('{"answer":"partial"}', finish_reason="length"), "permanent", "finish_length"),
    (_response('{"answer":"partial"}', finish_reason="tool_calls"), "permanent", "finish_other"),
  ],
)
def test_invalid_or_refused_results_are_safely_classified(
  monkeypatch: pytest.MonkeyPatch,
  response: httpx.Response,
  category: str,
  reason: str,
) -> None:
  transport = _FakeAsyncClient(response)
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  with pytest.raises(OpenRouterError) as captured:
    asyncio.run(
      _client().complete(
        model="test/model",
        messages=[{"role": "user", "content": "Question"}],
        output_type=_StrictResult,
        max_tokens=100,
      )
    )

  assert captured.value.category == category
  assert captured.value.reason == reason


@pytest.mark.parametrize(
  ("response", "category", "reason"),
  [
    (
      httpx.Response(
        429,
        request=httpx.Request("POST", "https://openrouter.test/chat/completions"),
        json={"error": {"message": "private status body"}},
      ),
      "transient",
      "http_status",
    ),
    (
      httpx.Response(
        200,
        request=httpx.Request("POST", "https://openrouter.test/chat/completions"),
        content=b"not-json",
      ),
      "invalid",
      "response_json",
    ),
    (
      httpx.Response(
        200,
        request=httpx.Request("POST", "https://openrouter.test/chat/completions"),
        json={"choices": []},
      ),
      "invalid",
      "response_shape",
    ),
  ],
)
def test_response_failures_have_content_free_diagnostic_reasons(
  monkeypatch: pytest.MonkeyPatch,
  response: httpx.Response,
  category: str,
  reason: str,
) -> None:
  transport = _FakeAsyncClient(response)
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  with pytest.raises(OpenRouterError) as captured:
    asyncio.run(
      _client().complete(
        model="test/model",
        messages=[{"role": "user", "content": "Private prompt"}],
        output_type=_StrictResult,
        max_tokens=100,
      )
    )

  assert captured.value.category == category
  assert captured.value.reason == reason
  assert "private" not in str(captured.value).lower()


def test_openrouter_error_existing_constructor_defaults_to_unspecified_reason() -> None:
  error = OpenRouterError("invalid")

  assert error.category == "invalid"
  assert error.reason == "unspecified"


@pytest.mark.parametrize(
  ("content", "output_type", "reason"),
  [
    ("not-json", _ExactAnswers, "schema_json"),
    ('{"wrong":[]}', _ExactAnswers, "schema_shape"),
    ('{"answers":"wrong"}', _ExactAnswers, "schema_shape"),
    ('{"answers":[["a","b"],["c","d"]],"extra":true}', _ExactAnswers, "schema_shape"),
    ('{"answers":[["abcdef","b"],["c","d"]]}', _ExactAnswers, "schema_answer_too_long"),
    ('{"answers":[["a","b"]]}', _ExactAnswers, "schema_answer_count"),
    ('{"answers":[["a"],["c","d"]]}', _ExactAnswers, "schema_answer_count"),
    ('{"answers":[["a","b","c"],["d","e"]]}', _ExactAnswers, "schema_answer_count"),
    ('{"answer":"rejected"}', _PatternResult, "schema"),
  ],
)
def test_schema_failures_expose_only_bounded_reason(
  monkeypatch: pytest.MonkeyPatch,
  content: str,
  output_type: type[BaseModel],
  reason: str,
) -> None:
  transport = _FakeAsyncClient(_response(content))
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  with pytest.raises(OpenRouterError) as captured:
    asyncio.run(
      _client().complete(
        model="test/model",
        messages=[{"role": "user", "content": "SOURCE_TEXT_SENTINEL"}],
        output_type=output_type,
        max_tokens=100,
      )
    )

  assert captured.value.category == "invalid"
  assert captured.value.reason == reason
  assert "SOURCE_TEXT_SENTINEL" not in str(captured.value)
  assert content not in str(captured.value)


def test_exact_answer_dimensions_pass_schema_validation(monkeypatch: pytest.MonkeyPatch) -> None:
  content = '{"answers":[["a","b"],["c","d"]]}'
  transport = _FakeAsyncClient(_response(content))
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  result = asyncio.run(
    _client().complete(
      model="test/model",
      messages=[{"role": "user", "content": "Source"}],
      output_type=_ExactAnswers,
      max_tokens=100,
    )
  )

  assert result.value.answers == [["a", "b"], ["c", "d"]]


def test_transport_failure_is_transient(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  transport = _FakeAsyncClient(error=httpx.ConnectError("offline", request=httpx.Request("POST", "https://x")))
  monkeypatch.setattr("junto.engine.openrouter.httpx.AsyncClient", transport.factory)

  with pytest.raises(OpenRouterError) as captured:
    asyncio.run(
      _client().complete(
        model="test/model",
        messages=[{"role": "user", "content": "Question"}],
        output_type=_StrictResult,
        max_tokens=100,
      )
    )

  assert captured.value.category == "transient"
  assert captured.value.reason == "transport"


def test_semantic_adapter_propagates_strict_type_and_usage() -> None:
  value = CoverageClassificationOutput.model_validate(
    {
      "assignments": [
        {
          "participantId": "participant-1",
          "coveredUnitIds": ["unit-1"],
          "evidence": [{"unitId": "unit-1", "quotes": ["literal quote"]}],
        }
      ]
    }
  )
  stub = _StructuredStub(
    OpenRouterCompletion(
      value=value,
      usage=OpenRouterUsage(
        request_id="request-7",
        model="test/model",
        input_tokens=120,
        output_tokens=40,
        reasoning_tokens=5,
        total_tokens=160,
        elapsed_milliseconds=19,
      ),
    )
  )
  provider = OpenRouterSemanticProvider(
    client=stub,
    model="test/model",
    max_output_tokens=700,
  )
  prompt = CoveragePrompt(
    question_id="question-1",
    question_prompt="Explain it.",
    reference_material="Reference for coverage only.",
    coverage_units=(PromptCoverageUnit(id="unit-1", text="Required idea"),),
    answers=(PromptAnswer(participant_id="participant-1", text="literal quote"),),
  )

  result = asyncio.run(provider.classify_coverage(prompt))

  assert result.value == value
  assert result.telemetry.request_id == "request-7"
  assert result.telemetry.elapsed_milliseconds == 19
  assert result.telemetry.input_tokens == 120
  assert result.telemetry.output_tokens == 40
  assert result.telemetry.reasoning_tokens == 5
  assert result.telemetry.total_tokens == 160
  assert stub.calls[0]["model"] == "test/model"
  assert stub.calls[0]["output_type"] is CoverageClassificationOutput
  assert stub.calls[0]["max_tokens"] == 700


def test_family_adapter_never_adds_coverage_or_reference_context() -> None:
  value = FamilyClusteringOutput.model_validate(
    {
      "families": [{"label": "Method"}],
      "assignments": [{"participantId": "participant-1", "familyIndex": 0}],
    }
  )
  stub = _StructuredStub(
    OpenRouterCompletion(
      value=value,
      usage=OpenRouterUsage(None, "test/model", 0, 0, 0, 0, 0),
    )
  )
  provider = OpenRouterSemanticProvider(client=stub, model="test/model")
  prompt = FamilyPrompt(
    question_id="question-1",
    question_prompt="Choose a method.",
    answers=(PromptAnswer(participant_id="participant-1", text="Use method A."),),
  )

  asyncio.run(provider.cluster_families(prompt))

  messages = stub.calls[0]["messages"]
  rendered = json.dumps(messages)
  assert "coverageUnits" not in rendered
  assert "referenceMaterial" not in rendered
  assert stub.calls[0]["output_type"] is FamilyClusteringOutput


def test_semantic_adapter_includes_bounded_repair_contract() -> None:
  value = FamilyClusteringOutput.model_validate(
    {
      "families": [],
      "assignments": [{"participantId": "participant-1", "familyIndex": None}],
    }
  )
  stub = _StructuredStub(
    OpenRouterCompletion(
      value=value,
      usage=OpenRouterUsage(None, "test/model", 0, 0, 0, 0, 0),
    )
  )
  provider = OpenRouterSemanticProvider(client=stub, model="test/model")
  prompt = FamilyPrompt(
    question_id="question-1",
    question_prompt="Choose.",
    answers=(PromptAnswer(participant_id="participant-1", text="Unclear."),),
  )

  asyncio.run(
    provider.cluster_families(
      prompt,
      repair=ProviderRepair(
        invalid_result={"families": "wrong-shape"},
        validation_errors=("families: list_type",),
      ),
    )
  )

  messages = stub.calls[0]["messages"]
  assert "single repair attempt" in messages[0]["content"]
  assert "<invalid_result_json>" in messages[1]["content"]
  assert "families: list_type" in messages[1]["content"]
  assert "<required_schema_json>" in messages[1]["content"]


@pytest.mark.parametrize(
  ("category", "expected_error"),
  [
    ("transient", ProviderTransientError),
    ("refusal", ProviderRefusalError),
    ("invalid", ProviderInvalidOutput),
    ("permanent", ProviderPermanentError),
  ],
)
def test_semantic_adapter_maps_content_free_openrouter_errors(
  category: Any,
  expected_error: type[Exception],
) -> None:
  provider = OpenRouterSemanticProvider(
    client=_StructuredStub(OpenRouterError(category)),
    model="test/model",
  )
  prompt = FamilyPrompt(
    question_id="question-1",
    question_prompt="Choose.",
    answers=(PromptAnswer(participant_id="participant-1", text="Answer."),),
  )

  with pytest.raises(expected_error) as captured:
    asyncio.run(provider.cluster_families(prompt))

  assert "Answer." not in str(captured.value)


@pytest.mark.parametrize("branch", ["coverage", "family"])
@pytest.mark.parametrize(
  ("category", "reason", "expected_error"),
  [
    ("transient", "transport", ProviderTransientError),
    ("refusal", "finish_other", ProviderRefusalError),
    ("invalid", "schema_shape", ProviderInvalidOutput),
    ("permanent", "http_status", ProviderPermanentError),
  ],
)
def test_semantic_adapter_logs_only_safe_failure_fields(
  caplog: pytest.LogCaptureFixture,
  branch: Literal["coverage", "family"],
  category: Any,
  reason: Any,
  expected_error: type[Exception],
) -> None:
  provider = OpenRouterSemanticProvider(
    client=_StructuredStub(OpenRouterError(category, reason)),
    model="test/model",
  )
  repair = ProviderRepair(
    invalid_result={"private": "SECRET_VALIDATION_PAYLOAD"},
    validation_errors=("SECRET_VALIDATION_ERROR",),
  )
  if branch == "coverage":
    prompt: CoveragePrompt | FamilyPrompt = CoveragePrompt(
      question_id="SECRET_QUESTION_ID",
      question_prompt="SECRET_PROMPT",
      reference_material="SECRET_SOURCE",
      coverage_units=(PromptCoverageUnit(id="SECRET_UNIT_ID", text="SECRET_UNIT_TEXT"),),
      answers=(PromptAnswer(participant_id="SECRET_PARTICIPANT_ID", text="SECRET_ANSWER"),),
    )
  else:
    prompt = FamilyPrompt(
      question_id="SECRET_QUESTION_ID",
      question_prompt="SECRET_PROMPT_WITH_SECRET_SOURCE",
      answers=(PromptAnswer(participant_id="SECRET_PARTICIPANT_ID", text="SECRET_ANSWER"),),
    )

  with caplog.at_level(logging.WARNING, logger="junto.semantic.openrouter"), pytest.raises(expected_error) as captured:
    if branch == "coverage":
      asyncio.run(provider.classify_coverage(prompt, repair=repair))  # type: ignore[arg-type]
    else:
      asyncio.run(provider.cluster_families(prompt, repair=repair))  # type: ignore[arg-type]

  records = [record for record in caplog.records if record.name == "junto.semantic.openrouter"]
  assert [record.getMessage() for record in records] == [
    f"OpenRouter semantic failure branch={branch} category={category} reason={reason}"
  ]
  exposed = caplog.text + str(captured.value)
  for secret in (
    "SECRET_QUESTION_ID",
    "SECRET_PROMPT",
    "SECRET_SOURCE",
    "SECRET_UNIT_ID",
    "SECRET_UNIT_TEXT",
    "SECRET_PARTICIPANT_ID",
    "SECRET_ANSWER",
    "SECRET_VALIDATION_PAYLOAD",
    "SECRET_VALIDATION_ERROR",
  ):
    assert secret not in exposed
