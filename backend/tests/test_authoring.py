from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from junto.config import Settings
from junto.main import _build_authoring_service, create_app
from junto.services.authoring import (
  AuthoringQuestion,
  AuthoringRequest,
  AuthoringSuggestion,
  OpenAIAuthoringService,
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


def test_authoring_provider_is_independent_from_the_analysis_engine() -> None:
  service = _build_authoring_service(
    Settings(
      session_secret="test-session-secret",
      engine_mode="placeholder",
      openai_api_key="test-key-never-used",
    )
  )

  assert isinstance(service, OpenAIAuthoringService)


def test_authoring_provider_remains_optional_without_an_openai_key() -> None:
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
