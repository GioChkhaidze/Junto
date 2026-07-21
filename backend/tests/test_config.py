from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import junto.config as config
from junto.config import Settings


def test_production_requires_a_strong_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("APP_ENV", "production")
  monkeypatch.delenv("SESSION_SECRET", raising=False)

  with pytest.raises(RuntimeError, match="SESSION_SECRET"):
    Settings.from_environment()


def test_production_enables_secure_cookies_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("APP_ENV", "production")
  monkeypatch.setenv("SESSION_SECRET", "x" * 48)
  monkeypatch.setenv(
    "DATABASE_URL",
    "postgresql+psycopg://junto:secret@database/junto",
  )
  monkeypatch.setenv("ANALYSIS_ENGINE", "openai")
  monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-used")
  monkeypatch.setenv("TRUSTED_ORIGINS", "https://junto.example")

  settings = Settings.from_environment()

  assert settings.secure_cookies is True
  assert settings.database_url is not None
  assert settings.engine_mode == "openai"


@pytest.mark.parametrize(
  ("session_secret", "secure_cookies"),
  [("too-short", True), ("x" * 48, False)],
)
def test_direct_production_settings_enforce_cookie_safety(
  session_secret: str,
  secure_cookies: bool,
) -> None:
  with pytest.raises(RuntimeError):
    Settings(
      environment="production",
      engine_mode="openai",
      session_secret=session_secret,
      secure_cookies=secure_cookies,
    )


def test_openrouter_configuration_requires_a_model() -> None:
  with pytest.raises(RuntimeError):
    Settings(openrouter_model=" ")


def test_default_openrouter_model_is_the_pinned_synthetic_workhorse() -> None:
  settings = Settings.from_environment({"APP_ENV": "test"})

  assert settings.openrouter_model == "google/gemini-2.5-flash"


def test_default_openai_analysis_uses_luna_with_high_reasoning() -> None:
  settings = Settings.from_environment({"APP_ENV": "test"})

  assert settings.openai_model == "gpt-5.6-luna"
  assert settings.openai_reasoning_effort == "high"


def test_semantic_timeout_defaults_leave_room_for_one_slow_request_and_solver() -> None:
  settings = Settings.from_environment({"APP_ENV": "test"})

  assert settings.provider_timeout_seconds == 90
  assert settings.semantic_room_timeout_seconds == 240
  assert settings.analysis_stale_seconds > settings.semantic_room_timeout_seconds + settings.solver_timeout_seconds


@pytest.mark.parametrize(
  "overrides",
  [
    {"provider_timeout_seconds": 0},
    {"semantic_room_timeout_seconds": 0},
    {"provider_timeout_seconds": 91, "semantic_room_timeout_seconds": 90},
    {
      "engine_mode": "openai",
      "semantic_room_timeout_seconds": 240,
      "solver_timeout_seconds": 10,
      "analysis_stale_seconds": 250,
    },
  ],
)
def test_invalid_semantic_timeout_policies_are_rejected(overrides: dict[str, Any]) -> None:
  with pytest.raises(RuntimeError):
    Settings(**overrides)


def test_synthetic_classroom_can_use_openai_analysis() -> None:
  settings = Settings(synthetic_classroom_enabled=True, engine_mode="openai")

  assert settings.synthetic_classroom_enabled is True
  assert settings.engine_mode == "openai"


def test_production_can_enable_bounded_openrouter_synthetic_classrooms() -> None:
  settings = Settings.from_environment(
    {
      "APP_ENV": "production",
      "SESSION_SECRET": "x" * 48,
      "DATABASE_URL": "postgresql+psycopg://junto:secret@database/junto",
      "ANALYSIS_ENGINE": "openai",
      "OPENAI_API_KEY": "test-openai-key",
      "OPENROUTER_API_KEY": "test-openrouter-key",
      "SYNTHETIC_CLASSROOM_ENABLED": "true",
      "SYNTHETIC_MAX_COHORT_SIZE": "12",
      "TRUSTED_ORIGINS": "https://junto.example",
    }
  )

  assert settings.synthetic_classroom_enabled is True
  assert settings.synthetic_max_cohort_size == 12
  assert settings.engine_mode == "openai"


def test_production_synthetic_classroom_requires_openrouter() -> None:
  with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
    Settings.from_environment(
      {
        "APP_ENV": "production",
        "SESSION_SECRET": "x" * 48,
        "DATABASE_URL": "postgresql+psycopg://junto:secret@database/junto",
        "ANALYSIS_ENGINE": "openai",
        "OPENAI_API_KEY": "test-openai-key",
        "SYNTHETIC_CLASSROOM_ENABLED": "true",
        "TRUSTED_ORIGINS": "https://junto.example",
      }
    )


@pytest.mark.parametrize("value", ["", "enabled", "2"])
def test_synthetic_classroom_environment_flag_is_strict(value: str) -> None:
  with pytest.raises(RuntimeError, match="SYNTHETIC_CLASSROOM_ENABLED"):
    Settings.from_environment({"APP_ENV": "test", "SYNTHETIC_CLASSROOM_ENABLED": value})


def test_conventional_environment_names_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("APP_ENV", "test")
  monkeypatch.setenv("ANALYSIS_ENGINE", "recorded")
  monkeypatch.setenv("OPENAI_MODEL", "test-model")
  monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
  monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
  monkeypatch.setenv("TRUSTED_ORIGINS", "http://localhost:4173")

  settings = Settings.from_environment()

  assert settings.environment == "test"
  assert settings.session_cookie_name == "junto_session"
  assert settings.secure_cookies is False
  assert settings.engine_mode == "recorded"
  assert settings.openai_model == "test-model"
  assert settings.openai_reasoning_effort == "high"
  assert settings.openrouter_model == "test/model"
  assert settings.synthetic_classroom_enabled is False
  assert settings.trusted_origins == ("http://localhost:4173",)


def test_development_enables_synthetic_classrooms_from_app_mode(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setenv("APP_ENV", "development")

  settings = Settings.from_environment()

  assert settings.synthetic_classroom_enabled is True


def test_default_development_settings_load_root_dotenv_without_mutating_environment(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  env_file = tmp_path / ".env"
  env_file.write_text(
    "OPENAI_API_KEY=local-file-key\nOPENAI_MODEL=file-model\n",
    encoding="utf-8",
  )
  monkeypatch.setattr(config, "_ROOT_ENV_FILE", env_file)
  monkeypatch.setenv("APP_ENV", "development")
  monkeypatch.setenv("OPENAI_MODEL", "process-model")
  monkeypatch.delenv("OPENAI_API_KEY", raising=False)

  settings = config._default_settings()

  assert settings.openai_api_key == "local-file-key"
  assert settings.openai_model == "process-model"
  assert os.getenv("OPENAI_API_KEY") is None


def test_direct_production_settings_reject_non_openai_engine() -> None:
  with pytest.raises(RuntimeError, match="Production requires"):
    Settings(
      environment="production",
      engine_mode="openrouter",
      session_secret="x" * 48,
      secure_cookies=True,
    )
