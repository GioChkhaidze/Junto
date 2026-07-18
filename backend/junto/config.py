from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    session_secret: str = "development-only-change-me"
    session_cookie_name: str = "junto_session"
    secure_cookies: bool = False
    max_session_room_grants: int = 8
    max_participants_per_room: int = 60
    max_questions_per_room: int = 8
    max_answer_characters: int = 1_500
    max_reference_characters: int = 8_000
    max_reference_file_bytes: int = 5 * 1024 * 1024
    max_reference_files_per_room: int = 8
    analysis_stage_delay_seconds: float = 0.6


settings = Settings()

