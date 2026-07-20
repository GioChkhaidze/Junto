"""Load a reviewed classroom fixture through Junto's public HTTP API.

This helper is intentionally restricted to loopback URLs. It creates no database
rows directly and receives no privileged application object. Every operation must
pass the same CSRF, room-state, participant, and capacity checks as a browser.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_PATHS = (
  BACKEND_DIRECTORY / "tests/fixtures/semantic/programming_dynamic_programming.json",
  BACKEND_DIRECTORY / "tests/fixtures/semantic/philosophy_ai_proctoring.json",
)


@dataclass(frozen=True, slots=True)
class FixtureQuestion:
  fixture_id: str
  subject: str
  prompt: str
  reference_material: str
  coverage_units: tuple[tuple[str, str], ...]
  answers: tuple[str, ...]

  def payload(self, position: int) -> JsonObject:
    return {
      "position": position,
      "prompt": self.prompt,
      "referenceMaterial": self.reference_material,
      "coverageUnits": [{"text": text} for _unit_id, text in self.coverage_units],
    }

  def answer_for(self, participant_index: int) -> str:
    if participant_index < 0:
      raise ValueError("Participant index cannot be negative.")
    return self.answers[participant_index % len(self.answers)]


def load_reviewed_questions(
  fixture_paths: Sequence[Path] = DEFAULT_FIXTURE_PATHS,
) -> tuple[FixtureQuestion, ...]:
  if not fixture_paths:
    raise ValueError("At least one semantic fixture is required.")
  if len(fixture_paths) > 8:
    raise ValueError("At most eight semantic fixtures can become room questions.")
  questions = tuple(_load_fixture_question(path) for path in fixture_paths)
  fixture_ids = [question.fixture_id for question in questions]
  if len(fixture_ids) != len(set(fixture_ids)):
    raise ValueError("Semantic fixture IDs must be unique.")
  return questions


def _load_fixture_question(path: Path) -> FixtureQuestion:
  try:
    raw = json.loads(path.read_text(encoding="utf-8"))
  except OSError as error:
    raise ValueError(f"Could not read semantic fixture {path.name}.") from error
  except json.JSONDecodeError as error:
    raise ValueError(f"Semantic fixture {path.name} is not valid JSON.") from error
  if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
    raise ValueError(f"Semantic fixture {path.name} must use schema version 1.")

  fixture_id = _bounded_string(raw, "fixtureId", maximum=120, context=path.name)
  subject = _bounded_string(raw, "subject", maximum=80, context=path.name)
  prompt = _bounded_string(raw, "questionPrompt", maximum=4_000, context=path.name)
  reference_material = _bounded_string(
    raw,
    "referenceMaterial",
    maximum=8_000,
    context=path.name,
  )

  raw_units = raw.get("coverageUnits")
  if not isinstance(raw_units, list) or not 1 <= len(raw_units) <= 8:
    raise ValueError(f"Semantic fixture {path.name} must contain 1 to 8 coverage units.")
  units: list[tuple[str, str]] = []
  for index, unit in enumerate(raw_units):
    if not isinstance(unit, dict):
      raise ValueError(f"Semantic fixture {path.name} has an invalid coverage unit.")
    context = f"{path.name} coverage unit {index + 1}"
    unit_id = _bounded_string(unit, "id", maximum=80, context=context)
    unit_text = _bounded_string(unit, "text", maximum=300, context=context)
    units.append((unit_id, unit_text))
  unit_ids = [unit_id for unit_id, _text in units]
  if len(unit_ids) != len(set(unit_ids)):
    raise ValueError(f"Semantic fixture {path.name} has duplicate coverage-unit IDs.")

  raw_participants = raw.get("participants")
  if not isinstance(raw_participants, list) or not raw_participants:
    raise ValueError(f"Semantic fixture {path.name} must contain participant answers.")
  answers: list[str] = []
  for participant in raw_participants:
    if not isinstance(participant, dict) or not isinstance(participant.get("answer"), str):
      raise ValueError(f"Semantic fixture {path.name} has an invalid participant answer.")
    answer = participant["answer"]
    if len(answer) > 1_500:
      raise ValueError(f"Semantic fixture {path.name} has an answer over 1,500 characters.")
    answers.append(answer)

  return FixtureQuestion(
    fixture_id=fixture_id,
    subject=subject,
    prompt=prompt,
    reference_material=reference_material,
    coverage_units=tuple(units),
    answers=tuple(answers),
  )


def _bounded_string(
  value: JsonObject,
  key: str,
  *,
  maximum: int,
  context: str,
) -> str:
  candidate = value.get(key)
  if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > maximum:
    raise ValueError(f"{context} has an invalid {key} value.")
  return candidate


class ApiFailure(RuntimeError):
  """A sanitized API failure suitable for command-line output."""


class BrowserClient:
  def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK_HOSTS:
      raise ValueError("The development fixture loader accepts loopback HTTP(S) URLs only.")
    self._base_url = base_url.rstrip("/")
    self._timeout_seconds = timeout_seconds
    self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    self._csrf_token: str | None = None

  def initialize(self) -> None:
    session = self.request("GET", "/api/session")
    token = session.get("csrfToken")
    if not isinstance(token, str) or not token:
      raise ApiFailure("The session endpoint did not return a CSRF token.")
    self._csrf_token = token

  def request(
    self,
    method: str,
    path: str,
    payload: JsonObject | None = None,
  ) -> JsonObject:
    upper_method = method.upper()
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    if payload is not None:
      data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
      headers["Content-Type"] = "application/json"
    if upper_method not in {"GET", "HEAD", "OPTIONS"}:
      if self._csrf_token is None:
        self.initialize()
      headers["X-CSRF-Token"] = self._csrf_token or ""

    request = urllib.request.Request(
      f"{self._base_url}{path}",
      data=data,
      headers=headers,
      method=upper_method,
    )
    try:
      with self._opener.open(request, timeout=self._timeout_seconds) as response:
        raw = response.read()
    except urllib.error.HTTPError as error:
      raise ApiFailure(_sanitized_error(error)) from error
    except urllib.error.URLError as error:
      raise ApiFailure(f"Could not reach Junto: {error.reason}") from error

    if not raw:
      return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
      raise ApiFailure("The API returned an unexpected response shape.")
    return parsed


def _sanitized_error(error: urllib.error.HTTPError) -> str:
  try:
    payload = json.loads(error.read())
    body = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = body.get("code") if isinstance(body, dict) else None
    message = body.get("message") if isinstance(body, dict) else None
    if isinstance(code, str) and isinstance(message, str):
      return f"Junto rejected the fixture request ({error.code}, {code}): {message}"
  except (json.JSONDecodeError, UnicodeDecodeError):
    pass
  return f"Junto rejected the fixture request with HTTP {error.code}."


def _participant_name(index: int) -> str:
  return f"Demo participant {index + 1:02d}"


def create_room(
  client: BrowserClient,
  questions: Sequence[FixtureQuestion],
  *,
  duration_minutes: int,
) -> tuple[str, str]:
  created = client.request(
    "POST",
    "/api/rooms",
    {
      "title": "Complementary reasoning workshop",
      "policy": "teach",
      "groupSize": {"minimum": 3, "preferred": 4, "maximum": 5},
      "durationMinutes": duration_minutes,
    },
  )
  room_id = str(created["roomId"])
  join_code = str(created["joinCode"])
  for position, question in enumerate(questions):
    client.request("POST", f"/api/rooms/{room_id}/questions", question.payload(position))
  client.request("POST", f"/api/rooms/{room_id}/open")
  return room_id, join_code


def join_cohort(
  base_url: str,
  join_code: str,
  *,
  participants: int,
) -> tuple[list[BrowserClient], str]:
  clients: list[BrowserClient] = []
  room_id: str | None = None
  for index in range(participants):
    client = BrowserClient(base_url)
    joined = client.request(
      "POST",
      f"/api/join/{urllib.parse.quote(join_code, safe='')}",
      {"displayName": _participant_name(index)},
    )
    joined_room_id = str(joined["roomId"])
    if room_id is not None and joined_room_id != room_id:
      raise ApiFailure("The join code resolved to inconsistent room identifiers.")
    room_id = joined_room_id
    clients.append(client)
  if room_id is None:
    raise ApiFailure("The fixture did not create a participant cohort.")
  return clients, room_id


def wait_for_answering(
  clients: list[BrowserClient],
  room_id: str,
  *,
  wait_seconds: float,
) -> JsonObject:
  deadline = time.monotonic() + wait_seconds
  while time.monotonic() < deadline:
    room = clients[0].request("GET", f"/api/rooms/{room_id}/participant")
    status = room.get("status")
    if status == "answering":
      return room
    if status in {"analyzing", "published", "failed"}:
      raise ApiFailure(f"The room entered {status} before the fixture could answer.")
    time.sleep(0.5)
  raise ApiFailure("Timed out waiting for the host to start the activity.")


def answer_and_submit(
  clients: list[BrowserClient],
  room_id: str,
  questions_fixture: Sequence[FixtureQuestion],
) -> None:
  for participant_index, client in enumerate(clients):
    room = client.request("GET", f"/api/rooms/{room_id}/participant")
    questions = room.get("questions")
    if not isinstance(questions, list) or len(questions) != len(questions_fixture):
      raise ApiFailure("The room does not match the reviewed semantic fixtures.")
    for fallback_position, question_view in enumerate(questions):
      if not isinstance(question_view, dict):
        raise ApiFailure("A participant question has an unexpected shape.")
      position_value = question_view.get("position", fallback_position)
      position = int(position_value)
      if position < 0 or position >= len(questions_fixture):
        raise ApiFailure("A participant question has an unknown fixture position.")
      fixture = questions_fixture[position]
      if str(question_view.get("prompt", "")).strip() != fixture.prompt:
        raise ApiFailure("The room question text does not match the reviewed fixture.")
      answer = fixture.answer_for(participant_index)
      question_id = urllib.parse.quote(str(question_view["id"]), safe="")
      client.request(
        "PUT",
        f"/api/rooms/{room_id}/responses/{question_id}",
        {"text": answer},
      )
    client.request("POST", f"/api/rooms/{room_id}/submit")


def wait_for_result(
  client: BrowserClient,
  room_id: str,
  *,
  wait_seconds: float,
) -> str:
  deadline = time.monotonic() + wait_seconds
  last_status = "unknown"
  while time.monotonic() < deadline:
    status_view = client.request("GET", f"/api/rooms/{room_id}/status")
    last_status = str(status_view.get("status", "unknown"))
    if last_status in {"published", "failed"}:
      return last_status
    time.sleep(0.5)
  return last_status


def probe_status_polling(
  clients: list[BrowserClient],
  room_id: str,
  *,
  rounds: int,
) -> JsonObject | None:
  """Exercise the participant status projection without recording response bodies."""

  if rounds <= 0:
    return None
  durations: list[float] = []

  def one_request(client: BrowserClient) -> float:
    started = time.monotonic()
    client.request("GET", f"/api/rooms/{room_id}/status")
    return time.monotonic() - started

  with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, len(clients))) as executor:
    for _round in range(rounds):
      durations.extend(executor.map(one_request, clients))

  ordered = sorted(durations)
  p95_index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
  return {
    "requests": len(durations),
    "medianMilliseconds": round(statistics.median(durations) * 1_000, 1),
    "p95Milliseconds": round(ordered[p95_index] * 1_000, 1),
    "maximumMilliseconds": round(max(durations) * 1_000, 1),
  }


def load_fixture(arguments: argparse.Namespace) -> JsonObject:
  if arguments.participants < 3 or arguments.participants > 60:
    raise ValueError("--participants must be between 3 and 60.")
  if arguments.poll_rounds < 0 or arguments.poll_rounds > 20:
    raise ValueError("--poll-rounds must be between 0 and 20.")
  fixture_paths = arguments.fixture_paths or DEFAULT_FIXTURE_PATHS
  questions_fixture = load_reviewed_questions(fixture_paths)

  host: BrowserClient | None = None
  if arguments.join_code:
    join_code = arguments.join_code.strip().upper()
    lookup_client = BrowserClient(arguments.base_url)
    lookup_client.request("GET", f"/api/join/{urllib.parse.quote(join_code, safe='')}")
    room_id = ""
  else:
    host = BrowserClient(arguments.base_url)
    room_id, join_code = create_room(
      host,
      questions_fixture,
      duration_minutes=arguments.duration_minutes,
    )

  participants, joined_room_id = join_cohort(
    arguments.base_url,
    join_code,
    participants=arguments.participants,
  )
  if not room_id:
    room_id = joined_room_id

  if host is not None:
    host.request("POST", f"/api/rooms/{room_id}/start")
  else:
    print(
      "Cohort joined. Start the activity in the host browser; the loader is waiting.",
      flush=True,
    )

  wait_for_answering(participants, room_id, wait_seconds=arguments.wait_seconds)
  answer_and_submit(participants, room_id, questions_fixture)
  status_client = host or participants[0]
  final_status = wait_for_result(
    status_client,
    room_id,
    wait_seconds=arguments.wait_seconds,
  )
  result = {
    "roomId": room_id,
    "joinCode": join_code,
    "fixtureIds": [question.fixture_id for question in questions_fixture],
    "participantCount": arguments.participants,
    "status": final_status,
  }
  polling_probe = probe_status_polling(
    participants,
    room_id,
    rounds=arguments.poll_rounds,
  )
  if polling_probe is not None:
    result["pollingProbe"] = polling_probe
  return result


def parser() -> argparse.ArgumentParser:
  argument_parser = argparse.ArgumentParser(description=__doc__)
  argument_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
  argument_parser.add_argument(
    "--join-code",
    help="Join a host-authored lobby; omit to create and run the reviewed fixture.",
  )
  argument_parser.add_argument("--participants", type=int, default=12)
  argument_parser.add_argument("--duration-minutes", type=int, default=20)
  argument_parser.add_argument("--wait-seconds", type=float, default=180.0)
  argument_parser.add_argument(
    "--fixture",
    dest="fixture_paths",
    action="append",
    type=Path,
    help=(
      "Semantic JSON fixture to load as a question. Repeat for multiple questions; "
      "the reviewed programming and philosophy fixtures are the default."
    ),
  )
  argument_parser.add_argument(
    "--poll-rounds",
    type=int,
    default=0,
    help="After analysis, concurrently exercise every participant status projection N times.",
  )
  return argument_parser


def main() -> None:
  try:
    result = load_fixture(parser().parse_args())
  except (ApiFailure, KeyError, TypeError, ValueError) as error:
    raise SystemExit(str(error)) from error
  print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
  main()
