from __future__ import annotations

from typing import Any, cast

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
  return cast(dict[str, Any], response.json())


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
  return cast(dict[str, Any], response.json())


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
  return participant, csrf, cast(dict[str, Any], response.json())


def start_room(host: TestClient, csrf: str, room_id: str) -> dict[str, Any]:
  response = host.post(
    f"/api/rooms/{room_id}/start",
    headers={"X-CSRF-Token": csrf},
  )
  assert response.status_code == 200, response.text
  assert response.json()["status"] == "answering"
  return cast(dict[str, Any], response.json())


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
  return cast(dict[str, Any], submission.json())


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


def test_read_only_session_requests_do_not_reissue_the_cookie(harness: AppHarness) -> None:
  with TestClient(harness.app) as client:
    initialized = client.get("/api/session")
    unchanged = client.get("/api/session")

  assert initialized.headers.get("set-cookie") is not None
  assert unchanged.headers.get("set-cookie") is None


def test_activity_history_lists_published_rooms_and_browser_owned_drafts(harness: AppHarness) -> None:
  with TestClient(harness.app) as host, TestClient(harness.app) as other_browser:
    csrf = get_csrf(host)
    draft = create_room(host, csrf)
    harness.clock.advance(seconds=1)
    published, question = create_open_room(host, csrf)
    participants = [join_room(harness.app, published["joinCode"], name) for name in ("Maya", "Alex")]
    try:
      start_room(host, csrf, published["roomId"])
      for index, (client, participant_csrf, _) in enumerate(participants):
        submit_answer(
          client,
          participant_csrf,
          published["roomId"],
          question["id"],
          f"Answer {index + 1}",
        )
      assert harness.scheduler.run_ready() == 2

      history = host.get("/api/activities")
      other_history = other_browser.get("/api/activities")
    finally:
      for client, _, _ in participants:
        client.close()

  assert history.status_code == 200
  activities = history.json()["activities"]
  assert [activity["roomId"] for activity in activities] == [published["roomId"], draft["roomId"]]
  assert activities[0] == {
    "roomId": published["roomId"],
    "joinCode": published["joinCode"],
    "canDelete": True,
    "title": "Reasoning workshop",
    "status": "published",
    "createdAt": "2026-07-18T09:00:01Z",
    "groupingPublishedAt": "2026-07-18T09:00:01Z",
    "participantCount": 2,
    "questionCount": 1,
    "groupCount": 1,
    "generationMode": "placeholder",
    "fullyCoveredGroupQuestions": None,
    "totalGroupQuestions": None,
  }
  assert activities[1]["status"] == "draft"
  assert activities[1]["groupCount"] == 0
  assert activities[1]["canDelete"] is True
  assert other_history.status_code == 200
  public_activities = other_history.json()["activities"]
  assert len(public_activities) == 1
  assert public_activities[0] == {
    **activities[0],
    "joinCode": None,
    "canDelete": False,
  }


def test_published_results_are_read_only_across_browsers_but_drafts_are_not_public(harness: AppHarness) -> None:
  with TestClient(harness.app) as host, TestClient(harness.app) as other_browser:
    csrf = get_csrf(host)
    draft = create_room(host, csrf)
    published, question = create_open_room(host, csrf)
    participants = [join_room(harness.app, published["joinCode"], name) for name in ("Maya", "Alex")]
    try:
      start_room(host, csrf, published["roomId"])
      for index, (client, participant_csrf, _) in enumerate(participants):
        submit_answer(client, participant_csrf, published["roomId"], question["id"], f"Answer {index + 1}")
      assert harness.scheduler.run_ready() == 2

      result = other_browser.get(f"/api/activities/{published['roomId']}")
      private_draft = other_browser.get(f"/api/activities/{draft['roomId']}")
      unavailable_host_view = other_browser.get(f"/api/rooms/{published['roomId']}")
    finally:
      for client, _, _ in participants:
        client.close()

  assert result.status_code == 200
  assert result.json()["roomId"] == published["roomId"]
  assert result.json()["participantCount"] == 2
  members = result.json()["result"]["groups"][0]["members"]
  assert {member["displayName"] for member in members} == {"Maya", "Alex"}
  assert {member["participantId"] for member in members} == {
    participants[0][2]["participantId"],
    participants[1][2]["participantId"],
  }
  assert private_draft.status_code == 404
  assert unavailable_host_view.status_code == 404


def test_host_deletion_requires_the_room_invite_code(harness: AppHarness) -> None:
  with TestClient(harness.app) as host:
    csrf = get_csrf(host)
    room = create_room(host, csrf)
    room_id = room["roomId"]

    rejected = host.request(
      "DELETE",
      f"/api/rooms/{room_id}",
      headers={"X-CSRF-Token": csrf},
      json={"confirmationCode": "WRONG1"},
    )
    still_present = host.get(f"/api/rooms/{room_id}")
    deleted = host.request(
      "DELETE",
      f"/api/rooms/{room_id}",
      headers={"X-CSRF-Token": csrf},
      json={"confirmationCode": room["joinCode"].lower()},
    )
    history = host.get("/api/activities")
    session = host.get("/api/session")

  assert rejected.status_code == 422
  assert rejected.json()["error"]["code"] == "ROOM_DELETE_CONFIRMATION_INVALID"
  assert still_present.status_code == 200
  assert deleted.status_code == 204
  assert history.json()["activities"] == []
  assert session.json()["hostRoomIds"] == []


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


def test_participant_access_recovers_when_a_stale_cookie_loses_the_join_grant(harness: AppHarness) -> None:
  with TestClient(harness.app) as host, TestClient(harness.app) as participant, TestClient(harness.app) as second:
    host_csrf = get_csrf(host)
    room, _ = create_open_room(host, host_csrf)
    participant_csrf = get_csrf(participant)
    stale_cookie = participant.cookies.get("junto_session")
    assert stale_cookie is not None

    joined = participant.post(
      f"/api/join/{room['joinCode']}",
      headers={"X-CSRF-Token": participant_csrf},
      json={"displayName": "Maya"},
    )
    assert joined.status_code == 201
    second_csrf = get_csrf(second)
    second_joined = second.post(
      f"/api/join/{room['joinCode']}",
      headers={"X-CSRF-Token": second_csrf},
      json={"displayName": "Alex"},
    )
    assert second_joined.status_code == 201
    start_room(host, host_csrf, room["roomId"])

    stale_headers = {"Cookie": f"junto_session={stale_cookie}"}
    stale_session = participant.get("/api/session", headers=stale_headers)
    resume_lookup = participant.get(f"/api/join/{room['joinCode']}", headers=stale_headers)
    resumed = participant.post(
      f"/api/join/{room['joinCode']}",
      headers={**stale_headers, "X-CSRF-Token": participant_csrf},
      json={"displayName": "Ignored replacement name"},
    )
    recovered = participant.get(f"/api/rooms/{room['roomId']}/participant", headers=stale_headers)

  assert stale_session.json()["participantRoomIds"] == []
  assert resume_lookup.status_code == 200
  assert resume_lookup.json()["status"] == "answering"
  assert resumed.status_code == 201, resumed.text
  assert resumed.json()["participantId"] == joined.json()["participantId"]
  assert resumed.json()["displayName"] == "Maya"
  assert recovered.status_code == 200
  assert recovered.json()["participant"]["participantId"] == joined.json()["participantId"]
  assert recovered.json()["status"] == "answering"
  assert recovered.json()["questions"]
  assert recovered.headers.get("set-cookie") is not None


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
    participants = [join_room(harness.app, room["joinCode"], name) for name in ("Maya", "Alex", "Noor", "Sam")]
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
      assert first_join["participantId"] in {member["participantId"] for member in private.json()["group"]["members"]}

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
