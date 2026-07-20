from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from junto.config import Settings
from junto.engine.openrouter import OpenRouterCompletion, OpenRouterError, OpenRouterUsage
from junto.engine.provider import (
  ProviderInvalidOutput,
  ProviderPermanentError,
  ProviderRefusalError,
  ProviderTransientError,
)
from junto.main import _build_authoring_service, create_app
from junto.services.authoring import (
  AuthoringQuestion,
  AuthoringRequest,
  AuthoringSuggestion,
  OpenAIAuthoringService,
  OpenRouterAuthoringService,
  _authoring_messages,
  _AuthoringSuggestionOutput,
  _validated_suggestion,
)


@dataclass(slots=True)
class RecordingAuthoringService:
  calls: list[AuthoringRequest] = field(default_factory=list)

  async def suggest(self, request: AuthoringRequest) -> AuthoringSuggestion:
    self.calls.append(request)
    return AuthoringSuggestion(
      question_prompt="How do the two arguments define responsibility differently?",
      coverage_units=(
        "Compares both definitions of responsibility",
        "Uses evidence from both arguments",
      ),
    )


def _csrf(client: TestClient) -> str:
  response = client.get("/api/session")
  assert response.status_code == 200
  return str(response.json()["csrfToken"])


def test_authoring_suggestion_extracts_file_and_forwards_the_full_draft(tmp_path: Path) -> None:
  authoring = RecordingAuthoringService()
  app = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    authoring_service=authoring,
    frontend_dist=tmp_path / "no-frontend-build",
  )
  payload = {
    "activityTitle": "Responsibility seminar",
    "target": "question",
    "targetQuestionIndex": 0,
    "questions": [
      {"prompt": "", "coverageUnits": [""]},
      {
        "prompt": "Which argument is stronger?",
        "coverageUnits": ["Defends a conclusion with textual evidence"],
      },
    ],
  }

  with TestClient(app) as client:
    response = client.post(
      "/api/authoring/suggestions",
      headers={"X-CSRF-Token": _csrf(client)},
      data={"payload": json.dumps(payload)},
      files={"file": ("reading.txt", b"Argument A\nArgument B", "text/plain")},
    )

  assert response.status_code == 200, response.text
  assert response.json() == {
    "questionPrompt": "How do the two arguments define responsibility differently?",
    "coverageUnits": [
      "Compares both definitions of responsibility",
      "Uses evidence from both arguments",
    ],
  }
  assert authoring.calls == [
    AuthoringRequest(
      activity_title="Responsibility seminar",
      target="question",
      target_question_index=0,
      questions=(
        AuthoringQuestion(prompt="", coverage_units=("",)),
        AuthoringQuestion(
          prompt="Which argument is stronger?",
          coverage_units=("Defends a conclusion with textual evidence",),
        ),
      ),
      reference_text="Argument A\nArgument B",
    )
  ]


def test_authoring_suggestion_requires_csrf_reference_and_configured_service(
  tmp_path: Path,
) -> None:
  configured = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    authoring_service=RecordingAuthoringService(),
    frontend_dist=tmp_path / "configured-no-frontend",
  )
  payload = {
    "target": "coverage",
    "targetQuestionIndex": 0,
    "questions": [{"prompt": "A complete question?", "coverageUnits": [""]}],
  }
  with TestClient(configured) as client:
    missing_csrf = client.post(
      "/api/authoring/suggestions",
      data={"payload": json.dumps(payload)},
    )
    no_reference = client.post(
      "/api/authoring/suggestions",
      headers={"X-CSRF-Token": _csrf(client)},
      data={"payload": json.dumps(payload)},
    )

  unavailable = create_app(
    app_settings=Settings(session_secret="test-session-secret"),
    frontend_dist=tmp_path / "unavailable-no-frontend",
  )
  with TestClient(unavailable) as client:
    no_provider = client.post(
      "/api/authoring/suggestions",
      headers={"X-CSRF-Token": _csrf(client)},
      data={"payload": json.dumps({**payload, "referenceText": "A short reference passage."})},
    )

  assert missing_csrf.status_code == 403
  assert no_reference.status_code == 422
  assert no_reference.json()["error"]["code"] == "AUTHORING_REFERENCE_REQUIRED"
  assert no_provider.status_code == 503
  assert no_provider.json()["error"]["code"] == "AUTHORING_ASSIST_UNAVAILABLE"


def test_openai_authoring_fallback_is_independent_from_the_analysis_engine() -> None:
  service = _build_authoring_service(
    Settings(
      session_secret="test-session-secret",
      engine_mode="placeholder",
      openai_api_key="test-key-never-used",
    )
  )

  assert isinstance(service, OpenAIAuthoringService)


def test_openrouter_is_preferred_for_authoring_when_both_credentials_exist() -> None:
  openrouter = _FakeOpenRouterClient()
  service = _build_authoring_service(
    Settings(
      session_secret="test-session-secret",
      engine_mode="openai",
      openai_api_key="openai-key-never-used",
      openrouter_api_key="openrouter-key-never-used",
    ),
    openrouter_client=openrouter,  # type: ignore[arg-type]
  )

  assert isinstance(service, OpenRouterAuthoringService)


def test_authoring_provider_remains_optional_without_a_provider_key() -> None:
  service = _build_authoring_service(Settings(session_secret="test-session-secret", engine_mode="placeholder"))

  assert service is None


class _FakeResponses:
  def __init__(self) -> None:
    self.kwargs: dict[str, object] = {}

  async def parse(self, **kwargs: object) -> object:
    self.kwargs = kwargs
    return SimpleNamespace(
      status="completed",
      output=(),
      output_parsed={
        "questionPrompt": "What tradeoff follows from the author’s proposal?",
        "coverageUnits": [
          "Identifies the proposal’s main benefit",
          "Explains a material cost or limitation",
        ],
      },
    )


class _FakeOpenAIClient:
  def __init__(self) -> None:
    self.responses = _FakeResponses()

  async def close(self) -> None:
    return None


class _FakeOpenRouterClient:
  def __init__(self, error: OpenRouterError | None = None) -> None:
    self.error = error
    self.calls: list[dict[str, Any]] = []

  async def complete(self, **kwargs: Any) -> OpenRouterCompletion[Any]:
    self.calls.append(kwargs)
    if self.error is not None:
      raise self.error
    output_type = kwargs["output_type"]
    value = output_type.model_validate(
      {
        "questionPrompt": "What tradeoff follows from the author’s proposal?",
        "coverageUnits": [
          "Identifies the proposal’s main benefit",
          "Explains a material cost or limitation",
        ],
      }
    )
    return OpenRouterCompletion(
      value=value,
      usage=OpenRouterUsage(
        request_id="request-1",
        model="test/model",
        input_tokens=100,
        output_tokens=50,
        reasoning_tokens=10,
        total_tokens=150,
        elapsed_milliseconds=25,
      ),
    )


def test_openai_authoring_uses_structured_nonstored_output_with_all_context() -> None:
  client = _FakeOpenAIClient()
  service = OpenAIAuthoringService(
    client=client,
    model="test-model",
    reasoning_effort="low",
  )
  request = AuthoringRequest(
    activity_title="Policy workshop",
    target="coverage",
    target_question_index=1,
    questions=(
      AuthoringQuestion("What problem is being solved?", ("Names the problem",)),
      AuthoringQuestion("Which policy is preferable?", ("",)),
    ),
    reference_text="The proposal reduces delay but increases operating cost.",
  )

  suggestion = asyncio.run(service.suggest(request))

  assert suggestion.coverage_units == (
    "Identifies the proposal’s main benefit",
    "Explains a material cost or limitation",
  )
  assert client.responses.kwargs["model"] == "test-model"
  assert client.responses.kwargs["store"] is False
  assert client.responses.kwargs["tools"] == []
  assert client.responses.kwargs["reasoning"] == {"effort": "low"}
  messages = client.responses.kwargs["input"]
  assert isinstance(messages, list)
  serialized_input = str(messages)
  assert "What problem is being solved?" in serialized_input
  assert "Which policy is preferable?" in serialized_input
  assert "reduces delay but increases operating cost" in serialized_input


def test_openrouter_authoring_uses_the_shared_strict_client_with_all_context() -> None:
  client = _FakeOpenRouterClient()
  service = OpenRouterAuthoringService(client=client, model="test/model")  # type: ignore[arg-type]
  request = AuthoringRequest(
    activity_title="Policy workshop",
    target="coverage",
    target_question_index=1,
    questions=(
      AuthoringQuestion("What problem is being solved?", ("Names the problem",)),
      AuthoringQuestion("Which policy is preferable?", ("",)),
    ),
    reference_text="The proposal reduces delay but increases operating cost.",
  )

  suggestion = asyncio.run(service.suggest(request))

  assert suggestion.coverage_units == (
    "Identifies the proposal’s main benefit",
    "Explains a material cost or limitation",
  )
  assert len(client.calls) == 1
  call = client.calls[0]
  assert call["model"] == "test/model"
  assert call["max_tokens"] == 4_000
  serialized_input = str(call["messages"])
  assert "What problem is being solved?" in serialized_input
  assert "Which policy is preferable?" in serialized_input
  assert "reduces delay but increases operating cost" in serialized_input


@pytest.mark.parametrize(
  ("category", "expected"),
  [
    ("transient", ProviderTransientError),
    ("refusal", ProviderRefusalError),
    ("invalid", ProviderInvalidOutput),
    ("permanent", ProviderPermanentError),
  ],
)
def test_openrouter_authoring_maps_content_free_provider_failures(
  category: str,
  expected: type[Exception],
) -> None:
  client = _FakeOpenRouterClient(OpenRouterError(category))  # type: ignore[arg-type]
  service = OpenRouterAuthoringService(client=client, model="test/model")  # type: ignore[arg-type]
  request = AuthoringRequest(
    activity_title="Policy workshop",
    target="question",
    target_question_index=0,
    questions=(AuthoringQuestion("", ("",)),),
    reference_text="Reference material",
  )

  with pytest.raises(expected):
    asyncio.run(service.suggest(request))


def test_authoring_prompt_requires_one_focused_question_and_atomic_units() -> None:
  request = AuthoringRequest(
    activity_title="Policy workshop",
    target="question",
    target_question_index=0,
    questions=(AuthoringQuestion("", ("",)),),
    reference_text="A compact policy reference.",
  )

  instructions = _authoring_messages(request)[0]["content"]

  assert "one central intellectual task" in instructions
  assert "32 words and 280 characters" in instructions
  assert "at most 10 words and 80" in instructions
  assert "never return more than 5" in instructions


@pytest.mark.parametrize(
  "question",
  [
    "What caused the result, and how should the policy respond?",
    "Which explanation is strongest; what evidence supports it?",
    "Explain the result and evaluate the proposed response.",
    "Why did this happen? What should happen next?",
  ],
)
def test_authoring_validation_rejects_compound_questions(question: str) -> None:
  output = _AuthoringSuggestionOutput.model_validate(
    {"questionPrompt": question, "coverageUnits": ["Primary causal explanation"]}
  )

  with pytest.raises(ProviderInvalidOutput):
    _validated_suggestion(output)


@pytest.mark.parametrize(
  "unit",
  [
    "One two three four five six seven eight nine ten eleven",
    "Evidence from the experiment; limitations of the sample",
    "Which evidence supports the conclusion?",
  ],
)
def test_authoring_validation_rejects_non_atomic_coverage_units(unit: str) -> None:
  output = _AuthoringSuggestionOutput.model_validate(
    {"questionPrompt": "Which explanation best fits the evidence?", "coverageUnits": [unit]}
  )

  with pytest.raises(ProviderInvalidOutput):
    _validated_suggestion(output)


def test_authoring_schema_bounds_generated_text_and_unit_count() -> None:
  with pytest.raises(ValidationError):
    _AuthoringSuggestionOutput.model_validate({"questionPrompt": "Q" * 281, "coverageUnits": ["Short unit"]})
  with pytest.raises(ValidationError):
    _AuthoringSuggestionOutput.model_validate(
      {"questionPrompt": "Which explanation is strongest?", "coverageUnits": ["U" * 81]}
    )
  with pytest.raises(ValidationError):
    _AuthoringSuggestionOutput.model_validate(
      {
        "questionPrompt": "Which explanation is strongest?",
        "coverageUnits": ["Unit one", "Unit two", "Unit three", "Unit four", "Unit five", "Unit six"],
      }
    )
