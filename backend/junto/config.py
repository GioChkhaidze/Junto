from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _environment_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value.")


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    session_secret: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    session_cookie_name: str = "junto_session"
    secure_cookies: bool = False
    max_session_room_grants: int = 8
    max_participants_per_room: int = 60
    max_questions_per_room: int = 8
    max_answer_characters: int = 1_500
    max_reference_characters: int = 8_000
    max_extracted_reference_characters: int = 100_000
    max_reference_file_bytes: int = 5 * 1024 * 1024
    max_reference_files_per_room: int = 8
    max_pdf_pages: int = 120
    max_docx_uncompressed_bytes: int = 20 * 1024 * 1024
    analysis_stage_delay_seconds: float = 0.0

    @classmethod
    def from_environment(cls) -> Settings:
        environment = os.getenv("JUNTO_ENV", "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise RuntimeError("JUNTO_ENV must be development, test, or production.")

        supplied_secret = os.getenv("JUNTO_SESSION_SECRET")
        if environment == "production":
            if supplied_secret is None or len(supplied_secret) < 32:
                raise RuntimeError(
                    "JUNTO_SESSION_SECRET must contain at least 32 characters in production."
                )
            session_secret = supplied_secret
        else:
            session_secret = supplied_secret or secrets.token_urlsafe(48)

        return cls(
            environment=environment,
            session_secret=session_secret,
            secure_cookies=_environment_flag(
                "JUNTO_SECURE_COOKIES",
                default=environment == "production",
            ),
        )


settings = Settings.from_environment()
