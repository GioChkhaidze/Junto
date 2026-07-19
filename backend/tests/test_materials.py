from __future__ import annotations

from fastapi.testclient import TestClient

from junto.config import Settings
from junto.main import create_app
from tests.conftest import CapturingScheduler, ManualClock, create_prepared_room, mutate


def test_material_type_and_size_are_bounded() -> None:
    app = create_app(
        app_settings=Settings(
            session_secret="test-session-secret",
            max_reference_file_bytes=12,
        ),
        scheduler=CapturingScheduler(),
        clock=ManualClock(),
    )
    host = TestClient(app)
    room_id, _join_code, _question_id = create_prepared_room(host)

    invalid_type = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/materials",
        files={"file": ("notes.exe", b"plain text", "application/octet-stream")},
    )
    assert invalid_type.status_code == 422
    assert invalid_type.json()["error"]["code"] == "UNSUPPORTED_REFERENCE_TYPE"

    legacy_doc = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/materials",
        files={"file": ("notes.doc", b"legacy", "application/msword")},
    )
    assert legacy_doc.status_code == 422
    assert legacy_doc.json()["error"]["code"] == "UNSUPPORTED_REFERENCE_TYPE"

    oversized = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/materials",
        files={"file": ("notes.txt", b"x" * 13, "text/plain")},
    )
    assert oversized.status_code == 422
    assert oversized.json()["error"]["code"] == "REFERENCE_FILE_TOO_LARGE"


def test_material_can_only_change_in_draft(backend: tuple) -> None:
    app, _scheduler, _clock = backend
    host = TestClient(app)
    room_id, _join_code, _question_id = create_prepared_room(host)
    mutate(host, "POST", f"/api/rooms/{room_id}/open")
    response = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/materials",
        files={"file": ("late.txt", b"late reference", "text/plain")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROOM_NOT_DRAFT"


def test_material_request_is_bounded_before_multipart_processing() -> None:
    app = create_app(
        app_settings=Settings(
            session_secret="test-session-secret",
            max_reference_file_bytes=12,
        ),
        scheduler=CapturingScheduler(),
        clock=ManualClock(),
    )
    host = TestClient(app)
    room_id, _join_code, _question_id = create_prepared_room(host)

    response = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/materials",
        files={"file": ("large.txt", b"x" * (300 * 1024), "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REFERENCE_REQUEST_TOO_LARGE"
