from __future__ import annotations

import pytest

from junto.config import Settings


def test_production_requires_a_strong_session_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNTO_ENV", "production")
    monkeypatch.delenv("JUNTO_SESSION_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="JUNTO_SESSION_SECRET"):
        Settings.from_environment()


def test_production_enables_secure_cookies_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUNTO_ENV", "production")
    monkeypatch.setenv("JUNTO_SESSION_SECRET", "x" * 48)
    monkeypatch.delenv("JUNTO_SECURE_COOKIES", raising=False)

    settings = Settings.from_environment()

    assert settings.secure_cookies is True
