from __future__ import annotations

import pytest

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


def test_openrouter_configuration_requires_models() -> None:
  with pytest.raises(RuntimeError):
    Settings(openrouter_models=())


def test_synthetic_classroom_can_use_openai_analysis() -> None:
  settings = Settings(synthetic_classroom_enabled=True, engine_mode="openai")

  assert settings.synthetic_classroom_enabled is True
  assert settings.engine_mode == "openai"


def test_conventional_environment_names_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("APP_ENV", "test")
  monkeypatch.setenv("ANALYSIS_ENGINE", "recorded")
  monkeypatch.setenv("OPENAI_MODEL", "test-model")
  monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
  monkeypatch.setenv("OPENROUTER_MODELS", "test/model-a,test/model-b")
  monkeypatch.setenv("TRUSTED_ORIGINS", "http://localhost:4173")

  settings = Settings.from_environment()

  assert settings.environment == "test"
  assert settings.session_cookie_name == "junto_session"
  assert settings.secure_cookies is False
  assert settings.engine_mode == "recorded"
  assert settings.openai_model == "test-model"
  assert settings.openai_reasoning_effort == "high"
  assert settings.openrouter_models == ("test/model-a", "test/model-b")
  assert settings.synthetic_classroom_enabled is False
  assert settings.synthetic_batch_size == 5
  assert settings.trusted_origins == ("http://localhost:4173",)


def test_development_enables_synthetic_classrooms_from_app_mode(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setenv("APP_ENV", "development")

  settings = Settings.from_environment()

  assert settings.synthetic_classroom_enabled is True


def test_direct_production_settings_reject_non_openai_engine() -> None:
  with pytest.raises(RuntimeError, match="Production requires"):
    Settings(
      environment="production",
      engine_mode="openrouter",
      session_secret="x" * 48,
      secure_cookies=True,
    )
