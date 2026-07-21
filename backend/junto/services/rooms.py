from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from uuid import UUID, uuid4

from junto.config import Settings
from junto.domain.entities import (
  AnalysisPhase,
  AnswerSaveResult,
  CoverageUnit,
  GroupingPolicy,
  GroupSize,
  Participant,
  Question,
  ReferenceAttachment,
  Response,
  Room,
  RoomStatus,
)
from junto.domain.errors import DomainError, conflict, invalid, not_found
from junto.domain.grouping import GroupingService, balanced_capacities
from junto.engine.compiler import SemanticCompilerError
from junto.repositories.base import RoomRepository
from junto.services.analysis import AnalysisPipeline, build_reference_material
from junto.services.personas import (
  SyntheticPersona,
  is_synthetic_participant,
  synthetic_participant_id,
  synthetic_session_nonce,
)
from junto.services.references import ReferenceTextExtractor
from junto.services.scheduling import Scheduler

Clock = Callable[[], datetime]
JOIN_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def utc_now() -> datetime:
  return datetime.now(UTC)


class RoomService:
  def __init__(
    self,
    repository: RoomRepository,
    grouping: GroupingService,
    extractor: ReferenceTextExtractor,
    scheduler: Scheduler,
    settings: Settings,
    *,
    clock: Clock = utc_now,
    analysis_pipeline: AnalysisPipeline | None = None,
  ) -> None:
    self._repository = repository
    self._grouping = grouping
    self._extractor = extractor
    self._scheduler = scheduler
    self._settings = settings
    self._clock = clock
    self._analysis_pipeline = analysis_pipeline

  def current_time(self) -> datetime:
    return self._clock()

  @property
  def settings(self) -> Settings:
    return self._settings

  def create_room(
    self,
    *,
    title: str,
    policy: GroupingPolicy,
    group_size: GroupSize,
    duration_minutes: int,
  ) -> Room:
    self.run_maintenance()
    now = self._clock()
    for _ in range(20):
      room = Room(
        id=uuid4(),
        join_code="".join(secrets.choice(JOIN_ALPHABET) for _ in range(6)),
        title=title.strip(),
        policy=policy,
        group_size=group_size,
        duration_minutes=duration_minutes,
        status=RoomStatus.DRAFT,
        created_at=now,
        updated_at=now,
        analysis_mode=("placeholder" if self._settings.engine_mode == "placeholder" else "coverage_aware"),
      )
      try:
        self._repository.add(room)
        return room
      except DomainError as error:
        if error.code != "JOIN_CODE_COLLISION":
          raise
    raise conflict("JOIN_CODE_EXHAUSTED", "A unique invite code could not be created.")

  def get_room(self, room_id: UUID) -> Room:
    self.close_collection_if_due(room_id)
    room = self._repository.get(room_id)
    if room is None:
      raise not_found()
    return room

  def list_published_rooms(self) -> list[Room]:
    self.run_maintenance()
    return self._repository.list_published()

  def repository_ready(self) -> bool:
    try:
      return self._repository.ping()
    except Exception:
      return False

  def run_maintenance(self) -> int:
    now = self._clock()
    return self._repository.recover_stale_analyses(
      before=now - timedelta(seconds=self._settings.analysis_stale_seconds),
      failed_at=now,
    )

  def delete_room(self, room_id: UUID, *, confirmation_code: str) -> None:
    room = self._repository.get(room_id)
    if room is None:
      raise not_found()
    if not secrets.compare_digest(room.join_code, confirmation_code.strip().upper()):
      raise invalid("ROOM_DELETE_CONFIRMATION_INVALID", "The invite code does not match.")
    if not self._repository.delete(room_id):
      raise not_found()

  def get_public_room(self, join_code: str) -> Room:
    room = self._repository.get_by_join_code(join_code.strip().upper())
    if room is None or not self._is_lobby(room):
      raise not_found("This invite is unavailable.")
    return room

  def get_join_room(self, join_code: str, *, session_nonce: str) -> Room:
    room = self._repository.get_by_join_code(join_code.strip().upper())
    if room is None:
      raise not_found("This invite is unavailable.")
    existing = any(participant.session_nonce == session_nonce for participant in room.participants.values())
    if not self._is_lobby(room) and not existing:
      raise not_found("This invite is unavailable.")
    return room

  def update_room(
    self,
    room_id: UUID,
    *,
    title: str | None = None,
    policy: GroupingPolicy | None = None,
    group_size: GroupSize | None = None,
    duration_minutes: int | None = None,
  ) -> Room:
    with self._repository.transaction(room_id) as room:
      self._require_draft(room)
      if title is not None:
        room.title = title.strip()
      if policy is not None:
        room.policy = policy
      if group_size is not None:
        room.group_size = group_size
      if duration_minutes is not None:
        room.duration_minutes = duration_minutes
      room.updated_at = self._clock()
    return self.get_room(room_id)

  def add_question(
    self,
    room_id: UUID,
    *,
    prompt: str,
    position: int | None,
    reference_material: str | None,
    coverage_units: list[tuple[str | None, str]],
  ) -> Question:
    with self._repository.transaction(room_id) as room:
      self._require_draft(room)
      if len(room.questions) >= self._settings.max_questions_per_room:
        raise invalid(
          "QUESTION_LIMIT_REACHED",
          (f"A room can contain at most {self._settings.max_questions_per_room} questions."),
        )
      target = len(room.questions) if position is None else position
      if target < 0 or target > len(room.questions):
        raise invalid("QUESTION_POSITION_INVALID", "Question position is out of range.")
      for question in room.questions:
        if question.position >= target:
          question.position += 1
      question = Question(
        id=uuid4(),
        position=target,
        prompt=prompt.strip(),
        reference_material=self._normalize_optional(reference_material),
        coverage_units=self._new_coverage_units(coverage_units, allow_ids=False),
      )
      room.questions.append(question)
      room.questions.sort(key=lambda item: item.position)
      room.updated_at = self._clock()
      saved = deepcopy(question)
    return saved

  def update_question(
    self,
    room_id: UUID,
    question_id: UUID,
    *,
    prompt: str | None,
    prompt_set: bool,
    position: int | None,
    position_set: bool,
    reference_material: str | None,
    reference_material_set: bool,
    coverage_units: list[tuple[str | None, str]] | None,
    coverage_units_set: bool,
  ) -> Question:
    with self._repository.transaction(room_id) as room:
      self._require_draft(room)
      question = self._find_question(room, question_id)
      if prompt_set:
        if prompt is None:
          raise invalid("QUESTION_PROMPT_REQUIRED", "Question prompt cannot be null.")
        question.prompt = prompt.strip()
      if reference_material_set:
        question.reference_material = self._normalize_optional(reference_material)
      if coverage_units_set:
        question.coverage_units = self._replace_coverage_units(
          question,
          coverage_units or [],
        )
      if position_set:
        if position is None or position < 0 or position >= len(room.questions):
          raise invalid("QUESTION_POSITION_INVALID", "Question position is out of range.")
        old_position = question.position
        if position != old_position:
          for other in room.questions:
            if other.id == question.id:
              continue
            if old_position < position and old_position < other.position <= position:
              other.position -= 1
            elif position < old_position and position <= other.position < old_position:
              other.position += 1
          question.position = position
          room.questions.sort(key=lambda item: item.position)
      room.updated_at = self._clock()
      saved = deepcopy(question)
    return saved

  def delete_question(self, room_id: UUID, question_id: UUID) -> None:
    with self._repository.transaction(room_id) as room:
      self._require_draft(room)
      question = self._find_question(room, question_id)
      room.questions.remove(question)
      ordered_questions = sorted(room.questions, key=lambda item: item.position)
      for index, remaining in enumerate(ordered_questions):
        remaining.position = index
      room.updated_at = self._clock()

  def add_reference_attachment(
    self,
    room_id: UUID,
    *,
    file_name: str,
    content: bytes,
  ) -> ReferenceAttachment:
    snapshot = self._repository.get(room_id)
    if snapshot is None:
      raise not_found()
    self._require_reference_slot(snapshot)
    safe_name = self._safe_file_name(file_name)
    if not content:
      raise invalid("REFERENCE_FILE_EMPTY", "The uploaded reference file is empty.")
    if len(content) > self._settings.max_reference_file_bytes:
      raise invalid(
        "REFERENCE_FILE_TOO_LARGE",
        f"Reference files must be at most {self._settings.max_reference_file_bytes} bytes.",
      )
    content_type, extracted_text = self._extractor.extract(
      file_name=safe_name,
      content=content,
    )
    with self._repository.transaction(room_id) as room:
      self._require_reference_slot(room)
      now = self._clock()
      attachment = ReferenceAttachment(
        id=uuid4(),
        file_name=safe_name,
        content_type=content_type,
        size_bytes=len(content),
        extracted_text=extracted_text,
        uploaded_at=now,
      )
      room.reference_attachments[attachment.id] = attachment
      room.updated_at = now
      saved = deepcopy(attachment)
    return saved

  def delete_reference_attachment(self, room_id: UUID, attachment_id: UUID) -> None:
    with self._repository.transaction(room_id) as room:
      self._require_draft(room)
      if attachment_id not in room.reference_attachments:
        raise not_found()
      del room.reference_attachments[attachment_id]
      room.updated_at = self._clock()

  def open_lobby(self, room_id: UUID) -> Room:
    with self._repository.transaction(room_id) as room:
      self._require_draft(room)
      if not room.questions:
        raise conflict("ROOM_HAS_NO_QUESTIONS", "Add at least one question before opening.")
      missing_units = [str(question.id) for question in room.questions if not question.coverage_units]
      if missing_units:
        raise conflict(
          "COVERAGE_UNITS_REQUIRED",
          "Every question needs at least one host-approved coverage unit before opening.",
        )
      if self._settings.engine_mode != "placeholder" and any(
        len(build_reference_material(room, question) or "") > self._settings.max_semantic_reference_characters
        for question in room.questions
      ):
        raise conflict(
          "REFERENCE_CONTEXT_TOO_LARGE",
          "Remove or shorten reference material before opening this room.",
        )
      room.status = RoomStatus.LOBBY
      room.updated_at = self._clock()
    return self.get_room(room_id)

  def join_room(
    self,
    join_code: str,
    *,
    display_name: str,
    existing_participant_id: UUID | None = None,
    session_nonce: str,
  ) -> tuple[Room, Participant]:
    candidate = self._repository.get_by_join_code(join_code.strip().upper())
    if candidate is None:
      raise not_found("This invite is unavailable.")
    with self._repository.transaction(candidate.id) as room:
      if existing_participant_id is not None:
        existing = room.participants.get(existing_participant_id)
        if existing is not None:
          return deepcopy(room), deepcopy(existing)
      existing_for_session = next(
        (participant for participant in room.participants.values() if participant.session_nonce == session_nonce),
        None,
      )
      if existing_for_session is not None:
        return deepcopy(room), deepcopy(existing_for_session)
      if not self._is_lobby(room):
        raise not_found("This invite is unavailable.")
      if len(room.participants) >= self._settings.max_participants_per_room:
        raise conflict("ROOM_FULL", "This room has reached its participant limit.")
      participant = Participant(
        id=uuid4(),
        display_name=display_name.strip(),
        joined_at=self._clock(),
        session_nonce=session_nonce,
      )
      room.participants[participant.id] = participant
      room.updated_at = self._clock()
      saved_room = deepcopy(room)
      saved_participant = deepcopy(participant)
    return saved_room, saved_participant

  def remove_participant(self, room_id: UUID, participant_id: UUID) -> None:
    with self._repository.transaction(room_id) as room:
      if not self._is_lobby(room):
        raise conflict(
          "COHORT_ALREADY_FROZEN",
          "Participants can only be removed before the activity starts.",
        )
      if participant_id not in room.participants:
        raise not_found()
      del room.participants[participant_id]
      room.responses = {
        key: response for key, response in room.responses.items() if response.participant_id != participant_id
      }
      room.updated_at = self._clock()

  def configure_synthetic_cohort(
    self,
    room_id: UUID,
    personas: Sequence[SyntheticPersona],
    *,
    seed: int,
  ) -> Room:
    """Replace only a lobby's synthetic roster with one deterministic target cohort."""
    target = tuple(personas)
    persona_ids = [persona.id for persona in target]
    if len(set(persona_ids)) != len(persona_ids) or any(not persona_id.strip() for persona_id in persona_ids):
      raise invalid(
        "SYNTHETIC_PERSONAS_INVALID",
        "Simulated participant identities must be unique and non-empty.",
      )
    if any(not persona.display_name.strip() or len(persona.display_name.strip()) > 80 for persona in target):
      raise invalid(
        "SYNTHETIC_PERSONAS_INVALID",
        "Simulated participant names must contain between 1 and 80 characters.",
      )
    if any(len(synthetic_session_nonce(persona.id, seed=seed)) > 160 for persona in target):
      raise invalid(
        "SYNTHETIC_PERSONAS_INVALID",
        "A simulated participant identity is too long.",
      )

    with self._repository.transaction(room_id) as room:
      if not self._is_lobby(room):
        raise conflict(
          "ROOM_NOT_IN_LOBBY",
          "Simulated participants can only be configured in the invite lobby.",
        )
      human_ids = {
        participant_id
        for participant_id, participant in room.participants.items()
        if not is_synthetic_participant(participant)
      }
      prospective_count = len(human_ids) + len(target)
      if prospective_count > self._settings.max_participants_per_room:
        raise conflict("ROOM_FULL", "This room has reached its participant limit.")
      # Validate the final target before touching the aggregate so an infeasible
      # resize cannot remove a previously valid simulated roster. Removing the
      # synthetic roster is always allowed in the lobby; start eligibility owns
      # whether the remaining human cohort can begin.
      if target:
        balanced_capacities(prospective_count, room.group_size)

      expected = {synthetic_participant_id(room.id, persona.id, seed=seed): persona for persona in target}
      if any(participant_id in human_ids for participant_id in expected):
        raise conflict(
          "SYNTHETIC_IDENTITY_COLLISION",
          "A simulated participant identity conflicts with the existing roster.",
        )

      changed = False
      for participant_id, participant in tuple(room.participants.items()):
        if is_synthetic_participant(participant) and participant_id not in expected:
          del room.participants[participant_id]
          changed = True
      if changed:
        room.responses = {key: response for key, response in room.responses.items() if key[0] in room.participants}

      joined_at = self._clock()
      for participant_id, persona in expected.items():
        nonce = synthetic_session_nonce(persona.id, seed=seed)
        display_name = persona.display_name.strip()
        existing = room.participants.get(participant_id)
        if existing is None:
          room.participants[participant_id] = Participant(
            id=participant_id,
            display_name=display_name,
            joined_at=joined_at,
            session_nonce=nonce,
          )
          changed = True
          continue
        if not is_synthetic_participant(existing):
          raise conflict(
            "SYNTHETIC_IDENTITY_COLLISION",
            "A simulated participant identity conflicts with the existing roster.",
          )
        if existing.display_name != display_name or existing.session_nonce != nonce:
          existing.display_name = display_name
          existing.session_nonce = nonce
          changed = True

      if changed:
        room.updated_at = joined_at
      saved = deepcopy(room)
    return saved

  def start_activity(self, room_id: UUID) -> Room:
    with self._repository.transaction(room_id) as room:
      if not self._is_lobby(room):
        raise conflict(
          "ROOM_NOT_IN_LOBBY",
          "The activity can only start from the invite lobby.",
        )
      balanced_capacities(len(room.participants), room.group_size)
      now = self._clock()
      room.cohort_ids = tuple(
        sorted(
          room.participants,
          key=lambda participant_id: (
            room.participants[participant_id].joined_at,
            str(participant_id),
          ),
        )
      )
      room.started_at = now
      room.deadline_at = now + timedelta(minutes=room.duration_minutes)
      room.status = RoomStatus.ANSWERING
      room.updated_at = now
      deadline_delay = max(0.0, (room.deadline_at - now).total_seconds())
    self._scheduler.schedule(deadline_delay, lambda: self._close_collection_scheduled(room_id))
    return self.get_room(room_id)

  def _close_collection_scheduled(self, room_id: UUID) -> None:
    self.close_collection_if_due(room_id)

  def save_answer(
    self,
    room_id: UUID,
    participant_id: UUID,
    question_id: UUID,
    *,
    text: str,
  ) -> AnswerSaveResult:
    self.close_collection_if_due(room_id)
    with self._repository.transaction(room_id) as room:
      participant = self._require_answering_participant(room, participant_id)
      if participant.submitted_at is not None:
        raise conflict(
          "SUBMISSION_FINAL",
          "Submitted answers can no longer be changed.",
        )
      self._find_question(room, question_id)
      normalized = text.strip()
      key = (participant_id, question_id)
      saved_at = self._clock()
      if not normalized:
        room.responses.pop(key, None)
      else:
        room.responses[key] = Response(
          participant_id=participant_id,
          question_id=question_id,
          text=normalized,
          updated_at=saved_at,
        )
      room.updated_at = saved_at
      answered_count = sum(1 for question in room.questions if (participant_id, question.id) in room.responses)
      return AnswerSaveResult(
        question_id=question_id,
        text=normalized,
        saved_at=saved_at,
        answered_question_count=answered_count,
      )

  def complete_synthetic_responses(
    self,
    room_id: UUID,
    answers: Mapping[UUID, Mapping[UUID, str]],
  ) -> int:
    """Validate, save, and submit all pending synthetic answers in one transaction."""
    should_schedule = False
    deadline_passed = False
    response_count = 0
    with self._repository.transaction(room_id) as room:
      if not self._is_answering(room):
        raise conflict(
          "ROOM_NOT_ANSWERING",
          "Answers are not being collected right now.",
        )
      now = self._clock()
      if room.deadline_at is not None and room.deadline_at <= now:
        should_schedule = self._claim_analysis(room, trigger="deadline")
        deadline_passed = True
      else:
        pending_ids = {
          participant_id
          for participant_id in room.cohort_ids
          if (
            (participant := room.participants.get(participant_id)) is not None
            and is_synthetic_participant(participant)
            and participant.submitted_at is None
          )
        }
        if set(answers) != pending_ids:
          raise invalid(
            "SYNTHETIC_PARTICIPANT_MATRIX_INVALID",
            "Responses must contain every pending simulated participant exactly once.",
          )
        question_ids = {question.id for question in room.questions}
        normalized_matrix: dict[UUID, dict[UUID, str]] = {}
        for participant_id, participant_answers in answers.items():
          if not isinstance(participant_answers, Mapping) or (set(participant_answers) != question_ids):
            raise invalid(
              "SYNTHETIC_QUESTION_MATRIX_INVALID",
              ("Each simulated participant must answer every room question exactly once."),
            )
          normalized_answers: dict[UUID, str] = {}
          for question_id, text in participant_answers.items():
            if not isinstance(text, str):
              raise invalid(
                "SYNTHETIC_ANSWER_INVALID",
                "Simulated answers must be text.",
              )
            if len(text) > self._settings.max_answer_characters:
              raise invalid(
                "ANSWER_TOO_LONG",
                (f"An answer cannot exceed {self._settings.max_answer_characters} characters."),
              )
            normalized_answers[question_id] = text.strip()
          normalized_matrix[participant_id] = normalized_answers

        if pending_ids:
          for participant_id, participant_answers in normalized_matrix.items():
            for question_id, text in participant_answers.items():
              key = (participant_id, question_id)
              if text:
                room.responses[key] = Response(
                  participant_id=participant_id,
                  question_id=question_id,
                  text=text,
                  updated_at=now,
                )
                response_count += 1
              else:
                room.responses.pop(key, None)
            room.participants[participant_id].submitted_at = now
          room.updated_at = now
          if all(room.participants[participant_id].submitted_at is not None for participant_id in room.cohort_ids):
            should_schedule = self._claim_analysis(room, trigger="all_submitted")

    if should_schedule:
      self._schedule_analysis(room_id)
    if deadline_passed:
      raise conflict("DEADLINE_PASSED", "The response deadline has passed.")
    return response_count

  def complete_synthetic_response(
    self,
    room_id: UUID,
    *,
    participant_id: UUID,
    answers: Mapping[UUID, str],
  ) -> int:
    """Save and submit one generated participant so demo progress is observable and retryable."""

    should_schedule = False
    response_count = 0
    with self._repository.transaction(room_id) as room:
      if not self._is_answering(room):
        raise conflict("ROOM_NOT_ANSWERING", "Answers are not being collected right now.")
      now = self._clock()
      if room.deadline_at is not None and room.deadline_at <= now:
        raise conflict("DEADLINE_PASSED", "The response deadline has passed.")
      participant = room.participants.get(participant_id)
      if participant is None or participant_id not in room.cohort_ids or not is_synthetic_participant(participant):
        raise not_found()
      if participant.submitted_at is not None:
        return 0
      question_ids = {question.id for question in room.questions}
      if not isinstance(answers, Mapping) or set(answers) != question_ids:
        raise invalid(
          "SYNTHETIC_QUESTION_MATRIX_INVALID",
          "A simulated participant must answer every room question exactly once.",
        )
      normalized_answers: dict[UUID, str] = {}
      for question_id, text in answers.items():
        if not isinstance(text, str):
          raise invalid("SYNTHETIC_ANSWER_INVALID", "Simulated answers must be text.")
        if len(text) > self._settings.max_answer_characters:
          raise invalid(
            "ANSWER_TOO_LONG",
            f"An answer cannot exceed {self._settings.max_answer_characters} characters.",
          )
        normalized_answers[question_id] = text.strip()
      for question_id, text in normalized_answers.items():
        key = (participant_id, question_id)
        if text:
          room.responses[key] = Response(
            participant_id=participant_id,
            question_id=question_id,
            text=text,
            updated_at=now,
          )
          response_count += 1
        else:
          room.responses.pop(key, None)
      participant.submitted_at = now
      room.updated_at = now
      if all(room.participants[member_id].submitted_at is not None for member_id in room.cohort_ids):
        should_schedule = self._claim_analysis(room, trigger="all_submitted")
    if should_schedule:
      self._schedule_analysis(room_id)
    return response_count

  def submit(self, room_id: UUID, participant_id: UUID) -> tuple[Participant, bool]:
    self.close_collection_if_due(room_id)
    should_schedule = False
    with self._repository.transaction(room_id) as room:
      participant = room.participants.get(participant_id)
      if participant is None or participant_id not in room.cohort_ids:
        raise not_found()
      if participant.submitted_at is not None:
        return deepcopy(participant), False
      self._require_answering_participant(room, participant_id)
      now = self._clock()
      participant.submitted_at = now
      room.updated_at = now
      if all(room.participants[member_id].submitted_at is not None for member_id in room.cohort_ids):
        should_schedule = self._claim_analysis(room, trigger="all_submitted")
      saved = deepcopy(participant)
    if should_schedule:
      self._schedule_analysis(room_id)
    return saved, should_schedule

  def start_analysis(self, room_id: UUID) -> Room:
    self.close_collection_if_due(room_id)
    with self._repository.transaction(room_id) as room:
      if not self._is_answering(room):
        raise conflict("ROOM_NOT_ANSWERING", "Analysis can only start during collection.")
      should_schedule = self._claim_analysis(room, trigger="host")
    if should_schedule:
      self._schedule_analysis(room_id)
    return self.get_room(room_id)

  def retry_analysis(self, room_id: UUID) -> Room:
    with self._repository.transaction(room_id) as room:
      if room.status != RoomStatus.FAILED:
        raise conflict(
          "ANALYSIS_NOT_FAILED",
          "Only a failed analysis can be retried.",
        )
      if room.analysis_attempt_count >= self._settings.analysis_max_attempts:
        raise conflict(
          "ANALYSIS_RETRY_EXHAUSTED",
          "The analysis retry has already been used.",
        )
      room.status = RoomStatus.ANSWERING
      should_schedule = self._claim_analysis(
        room,
        trigger=room.analysis_trigger or "host",
      )
    if should_schedule:
      self._schedule_analysis(room_id)
    return self.get_room(room_id)

  def close_collection_if_due(self, room_id: UUID) -> bool:
    room = self._repository.get(room_id)
    if room is None or not self._is_answering(room):
      return False
    now = self._clock()
    if room.deadline_at is None or room.deadline_at > now:
      return False
    with self._repository.transaction(room_id) as mutable:
      if not self._is_answering(mutable):
        return False
      if mutable.deadline_at is None or mutable.deadline_at > self._clock():
        return False
      claimed = self._claim_analysis(mutable, trigger="deadline")
    if claimed:
      self._schedule_analysis(room_id)
    return claimed

  def _schedule_analysis(self, room_id: UUID) -> None:
    if self._analysis_pipeline is not None:
      room = self._repository.get(room_id)
      if room is None:
        return
      attempt = room.analysis_attempt_count
      self._scheduler.schedule(
        0,
        lambda: self._run_coverage_analysis(room_id, attempt),
      )
      return
    self._scheduler.schedule(0, lambda: self._begin_grouping(room_id, schedule_next=True))

  def _run_coverage_analysis(self, room_id: UUID, attempt: int) -> None:
    snapshot = self._repository.get(room_id)
    if (
      snapshot is None
      or snapshot.status != RoomStatus.ANALYZING
      or snapshot.analysis_phase != AnalysisPhase.ANALYZING_RESPONSES
      or snapshot.analysis_attempt_count != attempt
      or self._analysis_pipeline is None
    ):
      return
    try:
      semantic = self._analysis_pipeline.compile(snapshot)
      with self._repository.transaction(room_id) as room:
        if (
          room.status != RoomStatus.ANALYZING
          or room.analysis_phase != AnalysisPhase.ANALYZING_RESPONSES
          or room.analysis_attempt_count != attempt
        ):
          return
        room.analysis_phase = AnalysisPhase.FORMING_GROUPS
        room.updated_at = self._clock()

      grouping = self._analysis_pipeline.optimize(
        snapshot,
        semantic,
        trigger=snapshot.analysis_trigger or "host",
      )
      with self._repository.transaction(room_id) as room:
        if (
          room.status != RoomStatus.ANALYZING
          or room.analysis_phase != AnalysisPhase.FORMING_GROUPS
          or room.analysis_attempt_count != attempt
        ):
          return
        room.analysis_result = semantic
        room.grouping_result = grouping
        room.analysis_phase = AnalysisPhase.COMPLETE
        room.status = RoomStatus.PUBLISHED
        room.analysis_completed_at = self._clock()
        room.last_error = None
        room.updated_at = self._clock()
    except Exception as error:
      safe_message = (
        str(error) if isinstance(error, SemanticCompilerError) else "Groups could not be formed from this response set."
      )
      with self._repository.transaction(room_id) as room:
        if room.analysis_attempt_count != attempt:
          return
        room.status = RoomStatus.FAILED
        room.analysis_phase = AnalysisPhase.FAILED
        room.analysis_result = None
        room.grouping_result = None
        room.analysis_completed_at = self._clock()
        room.last_error = safe_message
        room.updated_at = self._clock()

  def _begin_grouping(self, room_id: UUID, *, schedule_next: bool) -> None:
    with self._repository.transaction(room_id) as room:
      if room.status != RoomStatus.ANALYZING or room.analysis_phase != AnalysisPhase.ANALYZING_RESPONSES:
        return
      room.analysis_phase = AnalysisPhase.FORMING_GROUPS
      room.updated_at = self._clock()
    if schedule_next:
      self._scheduler.schedule(0, lambda: self._complete_grouping(room_id))

  def _complete_grouping(self, room_id: UUID) -> None:
    snapshot = self._repository.get(room_id)
    if (
      snapshot is None
      or snapshot.status != RoomStatus.ANALYZING
      or snapshot.analysis_phase != AnalysisPhase.FORMING_GROUPS
    ):
      return
    try:
      snapshot.updated_at = self._clock()
      result = self._grouping.form_groups(
        snapshot,
        trigger=snapshot.analysis_trigger or "unknown",
      )
      with self._repository.transaction(room_id) as room:
        if room.status != RoomStatus.ANALYZING or room.analysis_phase != AnalysisPhase.FORMING_GROUPS:
          return
        room.grouping_result = result
        room.analysis_phase = AnalysisPhase.COMPLETE
        # The placeholder slice auto-releases groups. The real semantic/optimizer
        # pipeline will restore ready -> explicit host publication.
        room.status = RoomStatus.PUBLISHED
        room.analysis_completed_at = self._clock()
        room.last_error = None
        room.updated_at = self._clock()
    except Exception:
      with self._repository.transaction(room_id) as room:
        room.status = RoomStatus.FAILED
        room.analysis_phase = AnalysisPhase.FAILED
        room.analysis_result = None
        room.grouping_result = None
        room.analysis_completed_at = self._clock()
        room.last_error = "Groups could not be formed. Please retry."
        room.updated_at = self._clock()

  def _claim_analysis(self, room: Room, *, trigger: str) -> bool:
    if room.status == RoomStatus.ANALYZING:
      return False
    now = self._clock()
    room.status = RoomStatus.ANALYZING
    room.analysis_phase = AnalysisPhase.ANALYZING_RESPONSES
    room.analysis_trigger = trigger
    room.analysis_attempt_count += 1
    room.analysis_started_at = now
    room.analysis_completed_at = None
    room.analysis_result = None
    room.grouping_result = None
    room.last_error = None
    room.updated_at = now
    return True

  @staticmethod
  def _is_lobby(room: Room) -> bool:
    return room.status == RoomStatus.LOBBY

  @staticmethod
  def _is_answering(room: Room) -> bool:
    return room.status == RoomStatus.ANSWERING

  @staticmethod
  def _require_draft(room: Room) -> None:
    if room.status != RoomStatus.DRAFT:
      raise conflict("ROOM_NOT_DRAFT", "This room can no longer be edited.")

  def _require_reference_slot(self, room: Room) -> None:
    self._require_draft(room)
    if len(room.reference_attachments) >= self._settings.max_reference_files_per_room:
      raise invalid(
        "REFERENCE_FILE_LIMIT_REACHED",
        "Remove an existing reference file before uploading another.",
      )

  def _require_answering_participant(self, room: Room, participant_id: UUID) -> Participant:
    if not self._is_answering(room):
      raise conflict("ROOM_NOT_ANSWERING", "Answers are not being collected right now.")
    if room.deadline_at is not None and room.deadline_at <= self._clock():
      raise conflict("DEADLINE_PASSED", "The response deadline has passed.")
    participant = room.participants.get(participant_id)
    if participant is None or participant_id not in room.cohort_ids:
      raise not_found()
    return participant

  @staticmethod
  def _find_question(room: Room, question_id: UUID) -> Question:
    for question in room.questions:
      if question.id == question_id:
        return question
    raise not_found()

  @staticmethod
  def _normalize_optional(value: str | None) -> str | None:
    if value is None:
      return None
    normalized = value.strip()
    return normalized or None

  @staticmethod
  def _safe_file_name(file_name: str) -> str:
    normalized = file_name.replace("\\", "/")
    safe_name = PurePath(normalized).name.strip()
    if not safe_name or len(safe_name) > 160 or any(ord(character) < 32 for character in safe_name):
      raise invalid("REFERENCE_FILE_NAME_INVALID", "The reference file name is invalid.")
    return safe_name

  @staticmethod
  def _new_coverage_units(
    values: list[tuple[str | None, str]],
    *,
    allow_ids: bool,
  ) -> list[CoverageUnit]:
    units: list[CoverageUnit] = []
    for supplied_id, text in values:
      if supplied_id is not None and not allow_ids:
        raise invalid(
          "COVERAGE_UNIT_ID_INVALID",
          "New coverage units cannot supply persistent IDs.",
        )
      units.append(CoverageUnit(id=supplied_id or f"u_{uuid4().hex}", text=text.strip()))
    return units

  def _replace_coverage_units(
    self,
    question: Question,
    values: list[tuple[str | None, str]],
  ) -> list[CoverageUnit]:
    existing = {unit.id for unit in question.coverage_units}
    supplied_existing = [unit_id for unit_id, _ in values if unit_id is not None]
    if len(supplied_existing) != len(set(supplied_existing)):
      raise invalid("COVERAGE_UNIT_ID_DUPLICATE", "Coverage unit IDs must be unique.")
    unknown = set(supplied_existing) - existing
    if unknown:
      raise invalid("COVERAGE_UNIT_ID_UNKNOWN", "An unknown coverage unit ID was supplied.")
    return self._new_coverage_units(values, allow_ids=True)
