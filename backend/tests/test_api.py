from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import AppHarness


def get_csrf(client: TestClient) -> str:
    response = client.get("/api/session")
    assert response.status_code == 200
    body = response.json()
    assert body["csrfToken"]
    assert body["hostRoomIds"] == []
    assert body["participantRoomIds"] == []
    return str(body["csrfToken"])


def create_room(
    host: TestClient,
    csrf: str,
    *,
    duration_minutes: int = 20,
    group_size: dict[str, int] | None = None,
) -> dict[str, Any]:
    response = host.post(
        "/api/rooms",
        headers={"X-CSRF-Token": csrf},
        json={
            "title": "Reasoning workshop",
            "policy": "teach",
            "durationMinutes": duration_minutes,
            "groupSize": group_size or {"minimum": 2, "preferred": 2, "maximum": 2},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_question(host: TestClient, csrf: str, room_id: str) -> dict[str, Any]:
    response = host.post(
        f"/api/rooms/{room_id}/questions",
        headers={"X-CSRF-Token": csrf},
        json={
            "prompt": "Which recurrence solves the problem, and why?",
            "referenceMaterial": "Use the uploaded lecture notes as supporting context.",
            "coverageUnits": [
                {"text": "Defines the dynamic-programming state"},
                {"text": "Justifies the recurrence"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def open_room(host: TestClient, csrf: str, room_id: str) -> None:
    response = host.post(
        f"/api/rooms/{room_id}/open",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "lobby"


def create_open_room(
    host: TestClient,
    csrf: str,
    *,
    duration_minutes: int = 20,
    group_size: dict[str, int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    room = create_room(
        host,
        csrf,
        duration_minutes=duration_minutes,
        group_size=group_size,
    )
    question = add_question(host, csrf, room["roomId"])
    open_room(host, csrf, room["roomId"])
    return room, question


def join_room(
    app: Any,
    join_code: str,
    display_name: str,
) -> tuple[TestClient, str, dict[str, Any]]:
    participant = TestClient(app)
    csrf = get_csrf(participant)
    response = participant.post(
        f"/api/join/{join_code}",
        headers={"X-CSRF-Token": csrf},
        json={"displayName": display_name},
    )
    assert response.status_code == 201, response.text
    return participant, csrf, response.json()


def start_room(host: TestClient, csrf: str, room_id: str) -> dict[str, Any]:
    response = host.post(
        f"/api/rooms/{room_id}/start",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "answering"
    return response.json()


def submit_answer(
    participant: TestClient,
    csrf: str,
    room_id: str,
    question_id: str,
    text: str,
) -> dict[str, Any]:
    save = participant.put(
        f"/api/rooms/{room_id}/responses/{question_id}",
        headers={"X-CSRF-Token": csrf},
        json={"text": text},
    )
    assert save.status_code == 200, save.text
    assert save.json()["text"] == text
    submission = participant.post(
        f"/api/rooms/{room_id}/submit",
        headers={"X-CSRF-Token": csrf},
    )
    assert submission.status_code == 200, submission.text
    assert submission.json()["submitted"] is True
    return submission.json()


def test_health() -> None:
    from junto.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_session_establishes_csrf_and_host_grant(harness: AppHarness) -> None:
    with TestClient(harness.app) as host:
        csrf = get_csrf(host)

        missing = host.post("/api/rooms", json={"title": "No token"})
        assert missing.status_code == 403
        assert missing.json()["error"]["code"] == "CSRF_INVALID"

        wrong = host.post(
            "/api/rooms",
            headers={"X-CSRF-Token": "wrong-token"},
            json={"title": "Wrong token"},
        )
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "CSRF_INVALID"

        room = create_room(host, csrf)
        session = host.get("/api/session")

    assert session.status_code == 200
    assert session.json()["csrfToken"] == csrf
    assert session.json()["hostRoomIds"] == [room["roomId"]]
    assert session.json()["participantRoomIds"] == []


def test_host_can_upload_material_add_coverage_question_and_open_room(
    harness: AppHarness,
) -> None:
    with TestClient(harness.app) as host:
        csrf = get_csrf(host)
        room = create_room(host, csrf)
        room_id = room["roomId"]

        upload = host.post(
            f"/api/rooms/{room_id}/materials",
            headers={"X-CSRF-Token": csrf},
            files={"file": ("lecture-notes.txt", b"State definition\nRecurrence", "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        material = upload.json()["material"]
        assert material["fileName"] == "lecture-notes.txt"
        assert material["mediaType"] == "text/plain"
        assert material["sizeBytes"] == len(b"State definition\nRecurrence")
        assert material["extractedCharacterCount"] == len("State definition\nRecurrence")

        question = add_question(host, csrf, room_id)
        assert question["position"] == 0
        assert [unit["text"] for unit in question["coverageUnits"]] == [
            "Defines the dynamic-programming state",
            "Justifies the recurrence",
        ]
        assert all(unit["id"].startswith("u_") for unit in question["coverageUnits"])

        open_room(host, csrf, room_id)
        view = host.get(f"/api/rooms/{room_id}")

    assert view.status_code == 200
    assert view.json()["status"] == "lobby"
    assert view.json()["materials"] == [material]
    assert view.json()["questions"] == [question]


def test_upload_rejects_unsupported_reference_type(harness: AppHarness) -> None:
    with TestClient(harness.app) as host:
        csrf = get_csrf(host)
        room = create_room(host, csrf)

        upload = host.post(
            f"/api/rooms/{room['roomId']}/materials",
            headers={"X-CSRF-Token": csrf},
            files={"file": ("payload.exe", b"not reference material", "application/octet-stream")},
        )

    assert upload.status_code == 422
    assert upload.json()["error"]["code"] == "UNSUPPORTED_REFERENCE_TYPE"


def test_participant_join_start_autosave_and_final_submit(harness: AppHarness) -> None:
    with TestClient(harness.app) as host:
        host_csrf = get_csrf(host)
        room, question = create_open_room(host, host_csrf)
        room_id = room["roomId"]

        first, first_csrf, first_join = join_room(harness.app, room["joinCode"], "Maya")
        second, second_csrf, _ = join_room(harness.app, room["joinCode"], "Alex")
        with first, second:
            assert first_join["displayName"] == "Maya"
            waiting = first.get(f"/api/rooms/{room_id}/participant")
            assert waiting.status_code == 200
            assert waiting.json()["questions"] == []
            assert waiting.json()["allowedActions"] == ["waitForStart"]

            start_room(host, host_csrf, room_id)
            activity = first.get(f"/api/rooms/{room_id}/participant")
            assert activity.status_code == 200
            assert activity.json()["questions"][0]["answer"] is None
            assert activity.json()["allowedActions"] == ["answer", "submit"]

            save = first.put(
                f"/api/rooms/{room_id}/responses/{question['id']}",
                headers={"X-CSRF-Token": first_csrf},
                json={"text": "  Let dp[i] be the minimum cost.  "},
            )
            assert save.status_code == 200
            assert save.json()["text"] == "Let dp[i] be the minimum cost."
            assert save.json()["answeredQuestionCount"] == 1

            refreshed = first.get(f"/api/rooms/{room_id}/participant")
            assert refreshed.json()["questions"][0]["answer"] == "Let dp[i] be the minimum cost."

            submitted = first.post(
                f"/api/rooms/{room_id}/submit",
                headers={"X-CSRF-Token": first_csrf},
            )
            assert submitted.status_code == 200
            assert submitted.json()["analysisStarted"] is False
            assert submitted.json()["status"] == "answering"

            immutable = first.put(
                f"/api/rooms/{room_id}/responses/{question['id']}",
                headers={"X-CSRF-Token": first_csrf},
                json={"text": "Try to replace the final response"},
            )
            assert immutable.status_code == 409
            assert immutable.json()["error"]["code"] == "SUBMISSION_FINAL"

            last = submit_answer(
                second,
                second_csrf,
                room_id,
                question["id"],
                "Use the recurrence from the previous two states.",
            )
            assert last["analysisStarted"] is True
            assert last["status"] == "analyzing"


def test_join_is_idempotent_for_one_browser_session(harness: AppHarness) -> None:
    with TestClient(harness.app) as host, TestClient(harness.app) as participant:
        host_csrf = get_csrf(host)
        room, _ = create_open_room(host, host_csrf)
        participant_csrf = get_csrf(participant)

        first = participant.post(
            f"/api/join/{room['joinCode']}",
            headers={"X-CSRF-Token": participant_csrf},
            json={"displayName": "Maya"},
        )
        second = participant.post(
            f"/api/join/{room['joinCode']}",
            headers={"X-CSRF-Token": participant_csrf},
            json={"displayName": "Duplicate request"},
        )
        host_view = host.get(f"/api/rooms/{room['roomId']}")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["participantId"] == first.json()["participantId"]
    assert second.json()["displayName"] == "Maya"
    assert host_view.json()["progress"]["participantCount"] == 1


def test_start_freezes_roster(harness: AppHarness) -> None:
    with TestClient(harness.app) as host:
        host_csrf = get_csrf(host)
        room, _ = create_open_room(host, host_csrf)
        room_id = room["roomId"]
        first, _, first_join = join_room(harness.app, room["joinCode"], "Maya")
        second, _, _ = join_room(harness.app, room["joinCode"], "Alex")
        with first, second:
            start_room(host, host_csrf, room_id)

            late = TestClient(harness.app)
            with late:
                late_csrf = get_csrf(late)
                lookup = late.get(f"/api/join/{room['joinCode']}")
                assert lookup.status_code == 404
                join = late.post(
                    f"/api/join/{room['joinCode']}",
                    headers={"X-CSRF-Token": late_csrf},
                    json={"displayName": "Late arrival"},
                )
                assert join.status_code == 404

            removal = host.delete(
                f"/api/rooms/{room_id}/participants/{first_join['participantId']}",
                headers={"X-CSRF-Token": host_csrf},
            )

    assert removal.status_code == 409
    assert removal.json()["error"]["code"] == "COHORT_ALREADY_FROZEN"


def test_placeholder_groups_auto_publish_and_participant_sees_only_own_group(
    harness: AppHarness,
) -> None:
    with TestClient(harness.app) as host:
        host_csrf = get_csrf(host)
        room, question = create_open_room(host, host_csrf)
        room_id = room["roomId"]
        participants = [
            join_room(harness.app, room["joinCode"], name)
            for name in ("Maya", "Alex", "Noor", "Sam")
        ]
        try:
            start_room(host, host_csrf, room_id)
            for index, (client, csrf, _) in enumerate(participants, start=1):
                receipt = submit_answer(
                    client,
                    csrf,
                    room_id,
                    question["id"],
                    f"Participant answer {index}",
                )
                assert receipt["analysisStarted"] is (index == len(participants))

            analyzing = host.get(f"/api/rooms/{room_id}/status")
            assert analyzing.json()["status"] == "analyzing"
            assert analyzing.json()["analysisPhase"] == "analyzing_responses"

            assert harness.scheduler.run_ready() == 2
            published = host.get(f"/api/rooms/{room_id}/status")
            assert published.json()["status"] == "published"
            assert published.json()["analysisPhase"] == "complete"

            all_groups = host.get(f"/api/rooms/{room_id}/groups")
            assert all_groups.status_code == 200
            assert all_groups.json()["generationMode"] == "placeholder"
            assert all_groups.json()["trigger"] == "all_submitted"
            assert len(all_groups.json()["groups"]) == 2
            assert sorted(len(group["members"]) for group in all_groups.json()["groups"]) == [2, 2]

            first_client, _, first_join = participants[0]
            private = first_client.get(f"/api/rooms/{room_id}/my-group")
            assert private.status_code == 200
            assert set(private.json()) == {"generationMode", "policy", "generatedAt", "group"}
            assert first_join["participantId"] in {
                member["participantId"] for member in private.json()["group"]["members"]
            }

            forbidden_roster = first_client.get(f"/api/rooms/{room_id}")
            forbidden_all_groups = first_client.get(f"/api/rooms/{room_id}/groups")
            assert forbidden_roster.status_code == 404
            assert forbidden_all_groups.status_code == 404
        finally:
            for client, _, _ in participants:
                client.close()


def test_deadline_atomically_claims_analysis_once(harness: AppHarness) -> None:
    with TestClient(harness.app) as host:
        host_csrf = get_csrf(host)
        room, _ = create_open_room(host, host_csrf, duration_minutes=1)
        room_id = room["roomId"]
        first, _, _ = join_room(harness.app, room["joinCode"], "Maya")
        second, _, _ = join_room(harness.app, room["joinCode"], "Alex")
        with first, second:
            start = start_room(host, host_csrf, room_id)
            assert start["remainingSeconds"] == 60
            assert len(harness.scheduler.callbacks) == 1

            harness.clock.advance(seconds=61)
            first_claim = host.get(f"/api/rooms/{room_id}/status")
            second_claim = host.get(f"/api/rooms/{room_id}/status")
            assert first_claim.json()["status"] == "analyzing"
            assert second_claim.json()["status"] == "analyzing"
            assert sum(delay <= 0 for delay, _ in harness.scheduler.callbacks) == 1

            assert harness.scheduler.run_ready() == 2
            groups = host.get(f"/api/rooms/{room_id}/groups")

    assert groups.status_code == 200
    assert groups.json()["trigger"] == "deadline"
