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
import secrets
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from random import Random
from typing import Any

from junto.services.personas import synthetic_personas

JsonObject = dict[str, Any]
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
OPENROUTER_COHORT_SIZES = {5, 10, 20}
POLL_INTERVAL_SECONDS = 1.5
RATE_LIMIT_MAX_RETRIES = 4
RETRY_AFTER_SAFETY_SECONDS = 1.0
BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
SEMANTIC_FIXTURE_DIRECTORY = BACKEND_DIRECTORY / "tests/fixtures/semantic"
DEFAULT_FIXTURE_PATHS = (
  SEMANTIC_FIXTURE_DIRECTORY / "programming_dynamic_programming.json",
  SEMANTIC_FIXTURE_DIRECTORY / "philosophy_ai_proctoring.json",
)


@dataclass(frozen=True, slots=True)
class FixtureQuestion:
  fixture_id: str
  subject: str
  prompt: str
  reference_material: str
  coverage_units: tuple[tuple[str, str], ...]
  answers: tuple[str, ...]

  def payload(self, position: int, *, include_reference: bool = True) -> JsonObject:
    payload: JsonObject = {
      "position": position,
      "prompt": self.prompt,
      "coverageUnits": [{"text": text} for _unit_id, text in self.coverage_units],
    }
    if include_reference:
      payload["referenceMaterial"] = self.reference_material
    return payload

  def answer_for(self, participant_index: int) -> str:
    if participant_index < 0:
      raise ValueError("Participant index cannot be negative.")
    return self.answers[participant_index % len(self.answers)]

  def answer_schedule(self, participant_count: int, *, seed: int) -> tuple[str, ...]:
    answers = [self.answer_for(index) for index in range(participant_count)]
    Random(f"{seed}:{self.fixture_id}").shuffle(answers)
    return tuple(answers)


def load_reviewed_questions(
  fixture_paths: Sequence[Path] = DEFAULT_FIXTURE_PATHS,
) -> tuple[FixtureQuestion, ...]:
  if not fixture_paths:
    raise ValueError("At least one semantic fixture is required.")
  questions = tuple(_load_fixture_question(path) for path in fixture_paths)
  fixture_ids = [question.fixture_id for question in questions]
  if len(fixture_ids) != len(set(fixture_ids)):
    raise ValueError("Semantic fixture IDs must be unique.")
  return questions


def discover_reviewed_activity_paths() -> tuple[Path, ...]:
  paths = tuple(sorted(SEMANTIC_FIXTURE_DIRECTORY.glob("*.json"), key=lambda path: path.name))
  if not paths:
    raise ValueError("No reviewed semantic activity fixtures were found.")
  return paths


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


class ActivityRunFailure(ApiFailure):
  """A sanitized failure with the already-issued room locator."""

  def __init__(self, message: str, *, room_id: str, join_code: str) -> None:
    super().__init__(message)
    self.room_id = room_id
    self.join_code = join_code


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

    raw = self._send(upper_method, path, headers=headers, data=data)
    if not raw:
      return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
      raise ApiFailure("The API returned an unexpected response shape.")
    return parsed

  def upload_text(self, path: str, *, file_name: str, text: str) -> JsonObject:
    if self._csrf_token is None:
      self.initialize()
    boundary = f"----junto-{secrets.token_hex(12)}"
    body = (
      (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
      ).encode()
      + text.encode()
      + f"\r\n--{boundary}--\r\n".encode()
    )
    raw = self._send(
      "POST",
      path,
      headers={
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-CSRF-Token": self._csrf_token or "",
      },
      data=body,
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
      raise ApiFailure("The API returned an unexpected response shape.")
    return parsed

  def _send(
    self,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    data: bytes | None,
  ) -> bytes:
    raw: bytes | None = None
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
      request = urllib.request.Request(
        f"{self._base_url}{path}",
        data=data,
        headers=headers,
        method=method,
      )
      try:
        with self._opener.open(request, timeout=self._timeout_seconds) as response:
          raw = response.read()
        break
      except urllib.error.HTTPError as error:
        can_retry = error.code == 429 and attempt < RATE_LIMIT_MAX_RETRIES
        retry_after = _retry_after_seconds(error) if can_retry else None
        if retry_after is None:
          raise ApiFailure(_sanitized_error(error)) from error
        time.sleep(retry_after + RETRY_AFTER_SAFETY_SECONDS)
      except urllib.error.URLError as error:
        raise ApiFailure("The connection to Junto was interrupted before the fixture request completed.") from error
      except TimeoutError as error:
        raise ApiFailure("Junto did not respond before the fixture request timed out.") from error
      except OSError as error:
        raise ApiFailure("The connection to Junto was interrupted before the fixture request completed.") from error

    if raw is None:
      raise ApiFailure("Junto kept rate limiting the fixture request.")
    return raw


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


def _retry_after_seconds(error: urllib.error.HTTPError) -> int | None:
  value = error.headers.get("Retry-After")
  try:
    seconds = int(value) if value is not None else 0
  except ValueError:
    return None
  return seconds if 1 <= seconds <= 60 else None


def _participant_names(size: int, *, seed: int) -> tuple[str, ...]:
  persona_count = min(size, 20)
  names = [persona.display_name for persona in synthetic_personas(persona_count, seed=seed)]
  names.extend(f"Simulated student {index + 1:02d}" for index in range(persona_count, size))
  return tuple(names)


def create_room(
  client: BrowserClient,
  questions: Sequence[FixtureQuestion],
  *,
  duration_minutes: int,
  title: str = "Complementary reasoning workshop",
  student_material: str | None = None,
  include_question_reference: bool = True,
) -> tuple[str, str]:
  created = client.request(
    "POST",
    "/api/rooms",
    {
      "title": title,
      "policy": "teach",
      "groupSize": {"minimum": 3, "preferred": 4, "maximum": 5},
      "durationMinutes": duration_minutes,
    },
  )
  room_id = str(created["roomId"])
  join_code = str(created["joinCode"])
  try:
    for position, question in enumerate(questions):
      client.request(
        "POST",
        f"/api/rooms/{room_id}/questions",
        question.payload(position, include_reference=include_question_reference),
      )
    if student_material:
      client.upload_text(
        f"/api/rooms/{room_id}/materials",
        file_name="student-reference.txt",
        text=student_material,
      )
    client.request("POST", f"/api/rooms/{room_id}/open")
  except ApiFailure as error:
    raise ActivityRunFailure(str(error), room_id=room_id, join_code=join_code) from error
  return room_id, join_code


def join_cohort(
  base_url: str,
  join_code: str,
  *,
  participants: int,
  seed: int = 41,
) -> tuple[list[BrowserClient], str]:
  clients: list[BrowserClient] = []
  room_id: str | None = None
  for display_name in _participant_names(participants, seed=seed):
    client = BrowserClient(base_url)
    joined = client.request(
      "POST",
      f"/api/join/{urllib.parse.quote(join_code, safe='')}",
      {"displayName": display_name},
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
    time.sleep(POLL_INTERVAL_SECONDS)
  raise ApiFailure("Timed out waiting for the host to start the activity.")


def answer_and_submit(
  clients: list[BrowserClient],
  room_id: str,
  questions_fixture: Sequence[FixtureQuestion],
  *,
  seed: int = 41,
) -> None:
  answer_schedules = {
    fixture.fixture_id: fixture.answer_schedule(len(clients), seed=seed) for fixture in questions_fixture
  }
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
      answer = answer_schedules[fixture.fixture_id][participant_index]
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
    time.sleep(POLL_INTERVAL_SECONDS)
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


def _published_summary(client: BrowserClient, room_id: str, participant_count: int) -> JsonObject:
  result = client.request("GET", f"/api/rooms/{room_id}/groups")
  if result.get("generationMode") != "coverage_aware":
    raise ApiFailure("The room published without the semantic evaluator and optimizer.")
  groups = result.get("groups")
  if not isinstance(groups, list) or not groups:
    raise ApiFailure("The published room did not contain groups.")
  group_sizes: list[int] = []
  member_ids: list[str] = []
  for group in groups:
    if not isinstance(group, dict) or not isinstance(group.get("members"), list):
      raise ApiFailure("The published room contained an invalid group.")
    members = group["members"]
    group_sizes.append(len(members))
    for member in members:
      if not isinstance(member, dict) or not isinstance(member.get("participantId"), str):
        raise ApiFailure("The published room contained an invalid group member.")
      member_ids.append(member["participantId"])
  if len(member_ids) != participant_count or len(member_ids) != len(set(member_ids)):
    raise ApiFailure("The published grouping did not assign every participant exactly once.")
  if any(size < 3 or size > 5 for size in group_sizes):
    raise ApiFailure("The published grouping violated the configured group sizes.")

  summary: JsonObject = {"groupCount": len(groups), "groupSizes": group_sizes}
  coverage_report = result.get("coverageReport")
  if not isinstance(coverage_report, dict) or coverage_report.get("totalGroupQuestions") != len(groups):
    raise ApiFailure("The semantic coverage report was missing or inconsistent.")
  summary["coverageReport"] = coverage_report
  solver = result.get("solver")
  if not isinstance(solver, dict) or not isinstance(solver.get("status"), str):
    raise ApiFailure("The optimizer result did not include solver provenance.")
  summary["solverStatus"] = solver["status"]
  return summary


def _activity_result(
  host: BrowserClient,
  fixture: FixtureQuestion,
  room_id: str,
  join_code: str,
  participant_count: int,
  status: str,
  *,
  source: str,
  models: Sequence[str] = (),
) -> JsonObject:
  result: JsonObject = {
    "fixtureId": fixture.fixture_id,
    "roomId": room_id,
    "joinCode": join_code,
    "participantCount": participant_count,
    "studentSource": source,
    "status": status,
  }
  if models:
    result["models"] = list(models)
  if status == "published":
    result.update(_published_summary(host, room_id, participant_count))
  elif status == "failed":
    room_view = host.request("GET", f"/api/rooms/{room_id}")
    last_error = room_view.get("lastError")
    if isinstance(last_error, str) and last_error:
      result["lastError"] = last_error
  return result


def run_reviewed_activity(
  arguments: argparse.Namespace,
  fixture: FixtureQuestion,
) -> JsonObject:
  host = BrowserClient(arguments.base_url)
  room_id, join_code = create_room(
    host,
    (fixture,),
    duration_minutes=arguments.duration_minutes,
    title=f"{fixture.subject.title()} reasoning workshop",
  )
  try:
    participants, joined_room_id = join_cohort(
      arguments.base_url,
      join_code,
      participants=arguments.participants,
      seed=arguments.seed,
    )
    if joined_room_id != room_id:
      raise ApiFailure("The reviewed cohort joined an unexpected room.")
    host.request("POST", f"/api/rooms/{room_id}/start")
    wait_for_answering(participants, room_id, wait_seconds=arguments.wait_seconds)
    answer_and_submit(participants, room_id, (fixture,), seed=arguments.seed)
    final_status = wait_for_result(host, room_id, wait_seconds=arguments.wait_seconds)
    result = _activity_result(
      host,
      fixture,
      room_id,
      join_code,
      arguments.participants,
      final_status,
      source="reviewed",
    )
    polling_probe = probe_status_polling(participants, room_id, rounds=arguments.poll_rounds)
    if polling_probe is not None:
      result["pollingProbe"] = polling_probe
    return result
  except ActivityRunFailure:
    raise
  except ApiFailure as error:
    raise ActivityRunFailure(str(error), room_id=room_id, join_code=join_code) from error


def run_openrouter_activity(
  arguments: argparse.Namespace,
  fixture: FixtureQuestion,
) -> JsonObject:
  host = BrowserClient(arguments.base_url, timeout_seconds=arguments.wait_seconds)
  room_id, join_code = create_room(
    host,
    (fixture,),
    duration_minutes=arguments.duration_minutes,
    title=f"{fixture.subject.title()} reasoning workshop",
    student_material=fixture.reference_material,
    include_question_reference=False,
  )
  try:
    cohort = host.request(
      "PUT",
      f"/api/development/rooms/{room_id}/synthetic-cohort",
      {"targetSize": arguments.participants, "seed": arguments.seed},
    )
    if cohort.get("syntheticParticipantCount") != arguments.participants:
      raise ApiFailure("The synthetic cohort did not reach its requested size.")
    host.request("POST", f"/api/rooms/{room_id}/start")
    generated = host.request(
      "POST",
      f"/api/development/rooms/{room_id}/synthetic-responses",
      {"source": "openrouter"},
    )
    raw_models = generated.get("models", [])
    if not raw_models or not isinstance(raw_models, list) or any(not isinstance(model, str) for model in raw_models):
      raise ApiFailure("The synthetic response endpoint returned invalid model provenance.")
    final_status = wait_for_result(host, room_id, wait_seconds=arguments.wait_seconds)
    return _activity_result(
      host,
      fixture,
      room_id,
      join_code,
      arguments.participants,
      final_status,
      source="openrouter",
      models=raw_models,
    )
  except ActivityRunFailure:
    raise
  except ApiFailure as error:
    raise ActivityRunFailure(str(error), room_id=room_id, join_code=join_code) from error


def load_activity_suite(arguments: argparse.Namespace) -> JsonObject:
  if arguments.student_source not in {"reviewed", "openrouter"}:
    raise ValueError("--student-source must be reviewed or openrouter.")
  if arguments.student_source == "openrouter" and arguments.participants not in OPENROUTER_COHORT_SIZES:
    raise ValueError("--participants must be 5, 10, or 20 with --student-source openrouter.")
  if arguments.student_source == "reviewed" and not 3 <= arguments.participants <= 20:
    raise ValueError("--participants must be between 3 and 20 for simulated activities.")
  if arguments.wait_seconds <= 0:
    raise ValueError("--wait-seconds must be greater than zero.")
  if not 0 <= arguments.seed <= 2_147_483_647:
    raise ValueError("--seed must be between 0 and 2,147,483,647.")
  if arguments.poll_rounds < 0 or arguments.poll_rounds > 20:
    raise ValueError("--poll-rounds must be between 0 and 20.")
  fixture_paths = arguments.fixture_paths or discover_reviewed_activity_paths()
  fixtures = load_reviewed_questions(fixture_paths)
  runner = run_openrouter_activity if arguments.student_source == "openrouter" else run_reviewed_activity
  activities: list[JsonObject] = []
  for fixture in fixtures:
    try:
      activities.append(runner(arguments, fixture))
    except ApiFailure as error:
      failure: JsonObject = {"fixtureId": fixture.fixture_id, "status": "loader_failed", "error": str(error)}
      if isinstance(error, ActivityRunFailure):
        failure.update({"roomId": error.room_id, "joinCode": error.join_code})
      activities.append(failure)
  return {
    "activityCount": len(activities),
    "allPublished": all(activity.get("status") == "published" for activity in activities),
    "activities": activities,
  }


def load_fixture(arguments: argparse.Namespace) -> JsonObject:
  if arguments.participants < 3 or arguments.participants > 60:
    raise ValueError("--participants must be between 3 and 60.")
  if arguments.wait_seconds <= 0:
    raise ValueError("--wait-seconds must be greater than zero.")
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
    seed=getattr(arguments, "seed", 41),
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
  answer_and_submit(participants, room_id, questions_fixture, seed=getattr(arguments, "seed", 41))
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
  argument_parser.add_argument("--participants", type=int, default=20)
  argument_parser.add_argument("--duration-minutes", type=int, default=20)
  argument_parser.add_argument("--wait-seconds", type=float, default=180.0)
  argument_parser.add_argument("--seed", type=int, default=41)
  argument_parser.add_argument(
    "--student-source",
    choices=("reviewed", "openrouter"),
    default="reviewed",
    help="Use reviewed fixture answers offline, or ask the configured OpenRouter simulator.",
  )
  argument_parser.add_argument(
    "--fixture",
    dest="fixture_paths",
    action="append",
    type=Path,
    help=(
      "Reviewed semantic fixture to run as its own activity. Repeat to select several; "
      "all reviewed semantic fixtures are the default."
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
    arguments = parser().parse_args()
    result = load_fixture(arguments) if arguments.join_code else load_activity_suite(arguments)
  except (ApiFailure, KeyError, TypeError, ValueError) as error:
    raise SystemExit(str(error)) from error
  print(json.dumps(result, indent=2, sort_keys=True))
  if result.get("allPublished") is False:
    raise SystemExit(1)


if __name__ == "__main__":
  main()
