from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

ENGINE_MODES = {"placeholder", "recorded", "openai", "openrouter"}
REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}


def _environment_csv(name: str, *, default: str) -> tuple[str, ...]:
  values = tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())
  if not values:
    raise RuntimeError(f"{name} must contain at least one value.")
  return values


def _environment_origins() -> tuple[str, ...]:
  value = os.getenv("TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
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
  openai_model: str = "gpt-5.6-sol"
  openai_reasoning_effort: str = "low"
  provider_timeout_seconds: float = 45.0
  semantic_max_concurrency: int = 4
  openrouter_api_key: str | None = field(default=None, repr=False)
  openrouter_models: tuple[str, ...] = (
    "google/gemini-2.5-flash-lite",
    "qwen/qwen3.5-9b",
  )
  synthetic_classroom_enabled: bool = False
  synthetic_max_cohort_size: int = 20
  synthetic_batch_size: int = 5
  synthetic_max_concurrency: int = 2
  solver_timeout_seconds: float = 10.0
  solver_random_seed: int = 41
  analysis_max_attempts: int = 2
  analysis_stale_seconds: int = 300
  room_retention_hours: int = 24
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
  max_answer_characters: int = 1_500
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
    if not 1 <= self.synthetic_max_cohort_size <= 20:
      raise RuntimeError("synthetic_max_cohort_size must be between 1 and 20.")
    if self.synthetic_batch_size <= 0 or self.synthetic_max_concurrency <= 0:
      raise RuntimeError("Synthetic batch size and concurrency must be positive.")
    if not self.openrouter_models or any(not model.strip() for model in self.openrouter_models):
      raise RuntimeError("openrouter_models must contain at least one model.")
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
  def from_environment(cls) -> Settings:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    if environment not in {"development", "test", "production"}:
      raise RuntimeError("APP_ENV must be development, test, or production.")

    supplied_secret = os.getenv("SESSION_SECRET")
    database_url = os.getenv("DATABASE_URL") or None
    engine_mode = os.getenv("ANALYSIS_ENGINE", "placeholder").strip().lower()
    if engine_mode not in ENGINE_MODES:
      raise RuntimeError("ANALYSIS_ENGINE must be placeholder, recorded, openai, or openrouter.")
    openai_api_key = os.getenv("OPENAI_API_KEY") or None
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY") or None
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower()
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

    trusted_origins = _environment_origins()
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
      openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-sol").strip(),
      openai_reasoning_effort=reasoning_effort,
      openrouter_api_key=openrouter_api_key,
      openrouter_models=_environment_csv(
        "OPENROUTER_MODELS",
        default="google/gemini-2.5-flash-lite,qwen/qwen3.5-9b",
      ),
      synthetic_classroom_enabled=environment == "development",
      trusted_origins=trusted_origins,
    )


settings = Settings.from_environment()
