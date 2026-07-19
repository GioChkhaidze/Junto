from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from tests.conftest import create_prepared_room, join_participant, mutate


def test_complete_lobby_questionnaire_and_placeholder_group_flow(backend: tuple) -> None:
    app, _scheduler, _clock = backend
    host = TestClient(app)
    room_id, join_code, question_id = create_prepared_room(host)

    material = mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/materials",
        files={"file": ("reading.md", b"# Shared reading\nA bounded reference.", "text/markdown")},
    )
    assert material.status_code == 201
    assert material.json()["material"]["fileName"] == "reading.md"
    assert material.json()["material"]["extractedCharacterCount"] > 0

    opened = mutate(host, "POST", f"/api/rooms/{room_id}/open")
    assert opened.status_code == 200
    assert opened.json()["status"] == "lobby"

    participants = [
        join_participant(app, join_code, name)
        for name in ("Maya", "Alex", "Noor", "Sam")
    ]
    lobby_view = participants[0].get(f"/api/rooms/{room_id}/participant").json()
    assert lobby_view["questions"] == []
    assert lobby_view["allowedActions"] == ["waitForStart"]
    assert "materials" not in lobby_view
    assert "referenceMaterial" not in str(lobby_view)

    host_lobby = host.get(f"/api/rooms/{room_id}").json()
    assert len(host_lobby["participants"]) == 4
    assert host_lobby["materials"][0]["fileName"] == "reading.md"

    started = mutate(host, "POST", f"/api/rooms/{room_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "answering"
    assert started.json()["deadlineAt"] is not None
    assert started.json()["remainingSeconds"] == 20 * 60

    late = TestClient(app)
    assert late.get(f"/api/join/{join_code}").status_code == 404

    for index, participant in enumerate(participants):
        receipt = mutate(
            participant,
            "PUT",
            f"/api/rooms/{room_id}/responses/{question_id}",
            json={"text": f"Participant {index} identifies a different tradeoff."},
        )
        assert receipt.status_code == 200
        assert receipt.json()["answeredQuestionCount"] == 1
        assert receipt.json()["questionId"] == question_id

    for participant in participants[:-1]:
        submitted = mutate(participant, "POST", f"/api/rooms/{room_id}/submit")
        assert submitted.status_code == 200
        assert submitted.json()["analysisStarted"] is False
        assert submitted.json()["answeredQuestionCount"] == 1

    last = mutate(participants[-1], "POST", f"/api/rooms/{room_id}/submit")
    assert last.status_code == 200
    assert last.json()["analysisStarted"] is True
    assert last.json()["status"] == "analyzing"

    service = app.state.room_service
    domain_room_id = UUID(room_id)
    assert service.advance_analysis_now(domain_room_id).analysis_phase == "forming_groups"
    assert service.advance_analysis_now(domain_room_id).status == "published"

    groups = host.get(f"/api/rooms/{room_id}/groups")
    assert groups.status_code == 200
    payload = groups.json()
    assert payload["generationMode"] == "placeholder"
    assert "solverStatus" not in payload
    assert "fullCoverageStatus" not in payload
    assert sorted(len(group["members"]) for group in payload["groups"]) == [4]

    mine = participants[0].get(f"/api/rooms/{room_id}/my-group")
    assert mine.status_code == 200
    assert mine.json()["generationMode"] == "placeholder"
    assert len(mine.json()["group"]["members"]) == 4

    late_edit = mutate(
        participants[0],
        "PUT",
        f"/api/rooms/{room_id}/responses/{question_id}",
        json={"text": "Too late"},
    )
    assert late_edit.status_code == 409


def test_deadline_claims_analysis_once_and_freezes_answers(backend: tuple) -> None:
    app, _scheduler, clock = backend
    host = TestClient(app)
    room_id, join_code, question_id = create_prepared_room(host, duration_minutes=1)
    mutate(host, "POST", f"/api/rooms/{room_id}/open")
    participants = [join_participant(app, join_code, name) for name in ("A", "B", "C")]
    mutate(host, "POST", f"/api/rooms/{room_id}/start")

    clock.advance(minutes=1, seconds=1)
    first_status = host.get(f"/api/rooms/{room_id}/status")
    assert first_status.status_code == 200
    assert first_status.json()["status"] == "analyzing"
    assert first_status.json()["analysisPhase"] == "analyzing_responses"

    rejected = mutate(
        participants[0],
        "PUT",
        f"/api/rooms/{room_id}/responses/{question_id}",
        json={"text": "After deadline"},
    )
    assert rejected.status_code == 409

    service = app.state.room_service
    domain_room_id = UUID(room_id)
    service.advance_analysis_now(domain_room_id)
    published = service.advance_analysis_now(domain_room_id)
    assert published.status == "published"
    assert published.grouping_result is not None
    assert published.grouping_result.trigger == "deadline"


def test_open_requires_host_approved_coverage_units(backend: tuple) -> None:
    app, _scheduler, _clock = backend
    host = TestClient(app)
    created = mutate(host, "POST", "/api/rooms", json={"title": "Undefined room"})
    room_id = created.json()["roomId"]
    mutate(
        host,
        "POST",
        f"/api/rooms/{room_id}/questions",
        json={"prompt": "A question", "coverageUnits": []},
    )
    opened = mutate(host, "POST", f"/api/rooms/{room_id}/open")
    assert opened.status_code == 409
    assert opened.json()["error"]["code"] == "COVERAGE_UNITS_REQUIRED"


def test_room_capabilities_prevent_cross_session_host_access(backend: tuple) -> None:
    app, _scheduler, _clock = backend
    host = TestClient(app)
    room_id, _join_code, _question_id = create_prepared_room(host)
    stranger = TestClient(app)
    assert stranger.get(f"/api/rooms/{room_id}").status_code == 404
    forbidden = mutate(
        stranger,
        "PATCH",
        f"/api/rooms/{room_id}",
        json={"title": "Stolen"},
    )
    assert forbidden.status_code == 404
