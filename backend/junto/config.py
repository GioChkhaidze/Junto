from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from junto.domain.limits import MAX_ANSWER_CHARACTERS

ENGINE_MODES = {"placeholder", "recorded", "openai", "openrouter"}
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}


_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _environment_origins(environment: Mapping[str, str]) -> tuple[str, ...]:
  value = environment.get("TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
  origins = tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())
  if not origins:
    raise RuntimeError("TRUSTED_ORIGINS must contain at least one origin.")
  return origins


@dataclass(frozen=True, slots=True)
class Settings:
  environment: str = "development"
  session_secret: str = field(
    default_factory=lambda: secrets.token_urlsafe(48),
    repr=False,
  )
  session_cookie_name: str = "junto_session"
  secure_cookies: bool = False
  database_url: str | None = None
  engine_mode: str = "placeholder"
  openai_api_key: str | None = field(default=None, repr=False)
  openai_model: str = "gpt-5.6-luna"
  openai_reasoning_effort: str = "high"
  provider_timeout_seconds: float = 90.0
  semantic_room_timeout_seconds: float = 240.0
  semantic_max_concurrency: int = 4
  openrouter_api_key: str | None = field(default=None, repr=False)
  openrouter_model: str = "google/gemini-2.5-flash"
  synthetic_classroom_enabled: bool = False
  synthetic_max_cohort_size: int = 20
  synthetic_generation_timeout_seconds: float = 120.0
  solver_timeout_seconds: float = 10.0
  solver_random_seed: int = 41
  analysis_max_attempts: int = 2
  analysis_stale_seconds: int = 300
  trusted_origins: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
  )
  join_rate_limit_per_minute: int = 30
  room_create_rate_limit_per_minute: int = 12
  authoring_rate_limit_per_minute: int = 12
  analysis_rate_limit_per_minute: int = 6
  answer_rate_limit_per_minute: int = 120
  status_rate_limit_per_minute: int = 180
  max_session_room_grants: int = 8
  max_participants_per_room: int = 60
  max_questions_per_room: int = 8
  max_answer_characters: int = MAX_ANSWER_CHARACTERS
  max_extracted_reference_characters: int = 100_000
  max_semantic_reference_characters: int = 100_000
  max_reference_file_bytes: int = 5 * 1024 * 1024
  max_reference_files_per_room: int = 8
  max_pdf_pages: int = 120
  max_docx_uncompressed_bytes: int = 20 * 1024 * 1024

  def __post_init__(self) -> None:
    """Reject unsafe deployment settings even when constructed outside env loading."""
    if self.environment not in {"development", "test", "production"}:
      raise RuntimeError("environment must be development, test, or production.")
    if self.engine_mode not in ENGINE_MODES:
      raise RuntimeError("engine_mode is invalid.")
    if self.provider_timeout_seconds <= 0 or self.semantic_room_timeout_seconds <= 0:
      raise RuntimeError("Semantic timeouts must be positive.")
    if self.provider_timeout_seconds > self.semantic_room_timeout_seconds:
      raise RuntimeError("The provider timeout cannot exceed the semantic room timeout.")
    if self.engine_mode != "placeholder" and (
      self.analysis_stale_seconds <= self.semantic_room_timeout_seconds + self.solver_timeout_seconds
    ):
      raise RuntimeError("Stale-analysis recovery must start after semantic analysis and optimization can finish.")
    if not 1 <= self.synthetic_max_cohort_size <= 20:
      raise RuntimeError("synthetic_max_cohort_size must be between 1 and 20.")
    if self.synthetic_generation_timeout_seconds <= 0:
      raise RuntimeError("Synthetic generation timeout must be positive.")
    if not self.openrouter_model.strip():
      raise RuntimeError("openrouter_model must not be empty.")
    if self.environment != "production":
      return
    if self.synthetic_classroom_enabled:
      raise RuntimeError("Synthetic classroom controls cannot be enabled in production.")
    if self.engine_mode != "openai":
      raise RuntimeError("Production requires the OpenAI analysis engine.")
    if len(self.session_secret) < 32:
      raise RuntimeError("Production session_secret must contain at least 32 characters.")
    if not self.secure_cookies:
      raise RuntimeError("Production secure_cookies must be enabled.")

  @classmethod
  def from_environment(cls, values: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if values is None else values
    environment = source.get("APP_ENV", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
      raise RuntimeError("APP_ENV must be development, test, or production.")

    supplied_secret = source.get("SESSION_SECRET")
    database_url = source.get("DATABASE_URL") or None
    engine_mode = source.get("ANALYSIS_ENGINE", "placeholder").strip().lower()
    if engine_mode not in ENGINE_MODES:
      raise RuntimeError("ANALYSIS_ENGINE must be placeholder, recorded, openai, or openrouter.")
    openai_api_key = source.get("OPENAI_API_KEY") or None
    openrouter_api_key = source.get("OPENROUTER_API_KEY") or None
    reasoning_effort = source.get("OPENAI_REASONING_EFFORT", "high").strip().lower()
    if reasoning_effort not in REASONING_EFFORTS:
      raise RuntimeError("OPENAI_REASONING_EFFORT must be none, low, medium, high, xhigh, or max.")
    if environment == "production":
      if supplied_secret is None or len(supplied_secret) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters in production.")
      session_secret = supplied_secret
      if database_url is None:
        raise RuntimeError("DATABASE_URL is required in production.")
      if engine_mode != "openai":
        raise RuntimeError("ANALYSIS_ENGINE must be openai in production.")
      if openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required when ANALYSIS_ENGINE=openai.")
    else:
      session_secret = supplied_secret or secrets.token_urlsafe(48)

    if engine_mode == "openai" and openai_api_key is None:
      raise RuntimeError("OPENAI_API_KEY is required when ANALYSIS_ENGINE=openai.")
    if engine_mode == "openrouter" and openrouter_api_key is None:
      raise RuntimeError("OPENROUTER_API_KEY is required when ANALYSIS_ENGINE=openrouter.")

    trusted_origins = _environment_origins(source)
    if environment == "production" and any(
      origin == "*" or not origin.startswith("https://") for origin in trusted_origins
    ):
      raise RuntimeError("Production TRUSTED_ORIGINS must contain explicit HTTPS origins.")

    return cls(
      environment=environment,
      session_secret=session_secret,
      secure_cookies=environment == "production",
      database_url=database_url,
      engine_mode=engine_mode,
      openai_api_key=openai_api_key,
      openai_model=source.get("OPENAI_MODEL", "gpt-5.6-luna").strip(),
      openai_reasoning_effort=reasoning_effort,
      openrouter_api_key=openrouter_api_key,
      openrouter_model=source.get("OPENROUTER_MODEL", "google/gemini-2.5-flash").strip(),
      synthetic_classroom_enabled=environment == "development",
      trusted_origins=trusted_origins,
    )


def _default_settings() -> Settings:
  """Load a workstation .env in development without mutating process state."""

  environment = dict(os.environ)
  app_environment = environment.get("APP_ENV", "development").strip().lower()
  if app_environment == "development" and _ROOT_ENV_FILE.is_file():
    local_values = {name: value for name, value in dotenv_values(_ROOT_ENV_FILE).items() if value is not None}
    environment = {**local_values, **environment}
  return Settings.from_environment(environment)


settings = _default_settings()
