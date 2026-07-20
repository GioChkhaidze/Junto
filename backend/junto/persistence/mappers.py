from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from junto.domain.entities import (
  AnalysisPhase,
  CoverageUnit,
  Group,
  GroupingPolicy,
  GroupingResult,
  GroupSize,
  Participant,
  Question,
  ReferenceAttachment,
  Response,
  Room,
  RoomStatus,
)
from junto.engine.models import GroupingArtifact, SemanticArtifact
from junto.persistence.models import (
  CoverageUnitRecord,
  ParticipantRecord,
  QuestionRecord,
  ReferenceMaterialRecord,
  ResponseRecord,
  RoomRecord,
)

_DATETIME = TypeAdapter(datetime)


def load_room_aggregate(session: Session, room_record: RoomRecord) -> Room:
  """Hydrate a domain aggregate without attaching persistence objects to it."""

  room_id = room_record.id
  question_records = list(
    session.scalars(
      select(QuestionRecord)
      .where(QuestionRecord.room_id == room_id)
      .order_by(QuestionRecord.position, QuestionRecord.id)
    )
  )
  unit_records = list(
    session.scalars(
      select(CoverageUnitRecord)
      .where(CoverageUnitRecord.room_id == room_id)
      .order_by(
        CoverageUnitRecord.question_id,
        CoverageUnitRecord.position,
        CoverageUnitRecord.id,
      )
    )
  )
  units_by_question: dict[UUID, list[CoverageUnit]] = {}
  for record in unit_records:
    units_by_question.setdefault(record.question_id, []).append(CoverageUnit(id=record.id, text=record.text))
  questions = [
    Question(
      id=record.id,
      position=record.position,
      prompt=record.prompt,
      reference_material=record.reference_material,
      coverage_units=units_by_question.get(record.id, []),
    )
    for record in question_records
  ]

  material_records = list(
    session.scalars(
      select(ReferenceMaterialRecord)
      .where(ReferenceMaterialRecord.room_id == room_id)
      .order_by(ReferenceMaterialRecord.uploaded_at, ReferenceMaterialRecord.id)
    )
  )
  attachments = {
    record.id: ReferenceAttachment(
      id=record.id,
      file_name=record.file_name,
      content_type=record.content_type,
      size_bytes=record.size_bytes,
      extracted_text=record.extracted_text,
      uploaded_at=record.uploaded_at,
    )
    for record in material_records
  }

  participant_records = list(
    session.scalars(
      select(ParticipantRecord)
      .where(ParticipantRecord.room_id == room_id)
      .order_by(ParticipantRecord.joined_at, ParticipantRecord.id)
    )
  )
  participants = {
    record.id: Participant(
      id=record.id,
      display_name=record.display_name,
      joined_at=record.joined_at,
      session_nonce=record.session_nonce,
      submitted_at=record.submitted_at,
    )
    for record in participant_records
  }
  cohort_ids = tuple(
    record.id
    for record in sorted(
      (item for item in participant_records if item.cohort_position is not None),
      key=lambda item: cast(int, item.cohort_position),
    )
  )

  response_records = list(
    session.scalars(
      select(ResponseRecord)
      .where(ResponseRecord.room_id == room_id)
      .order_by(ResponseRecord.participant_id, ResponseRecord.question_id)
    )
  )
  responses = {
    (record.participant_id, record.question_id): Response(
      participant_id=record.participant_id,
      question_id=record.question_id,
      text=record.text,
      updated_at=record.updated_at,
    )
    for record in response_records
  }

  return Room(
    id=room_record.id,
    join_code=room_record.join_code,
    title=room_record.title,
    policy=GroupingPolicy(room_record.policy),
    group_size=GroupSize(
      minimum=room_record.minimum_group_size,
      preferred=room_record.preferred_group_size,
      maximum=room_record.maximum_group_size,
    ),
    duration_minutes=room_record.duration_minutes,
    status=RoomStatus(room_record.status),
    created_at=room_record.created_at,
    updated_at=room_record.updated_at,
    questions=questions,
    participants=participants,
    responses=responses,
    reference_attachments=attachments,
    cohort_ids=cohort_ids,
    started_at=room_record.started_at,
    deadline_at=room_record.deadline_at,
    analysis_mode=room_record.analysis_mode,
    analysis_phase=AnalysisPhase(room_record.analysis_phase),
    analysis_trigger=room_record.analysis_trigger,
    analysis_started_at=room_record.analysis_started_at,
    analysis_completed_at=room_record.analysis_completed_at,
    analysis_attempt_count=room_record.analysis_attempt_count,
    analysis_result=_deserialize_semantic(room_record.analysis_result),
    grouping_result=_deserialize_grouping(room_record.grouping_result),
    last_error=room_record.last_error,
  )


def room_record_from_domain(room: Room) -> RoomRecord:
  return RoomRecord(
    id=room.id,
    join_code=room.join_code,
    title=room.title,
    policy=room.policy.value,
    minimum_group_size=room.group_size.minimum,
    preferred_group_size=room.group_size.preferred,
    maximum_group_size=room.group_size.maximum,
    duration_minutes=room.duration_minutes,
    status=room.status.value,
    created_at=room.created_at,
    updated_at=room.updated_at,
    started_at=room.started_at,
    deadline_at=room.deadline_at,
    analysis_mode=room.analysis_mode,
    analysis_phase=room.analysis_phase.value,
    analysis_trigger=room.analysis_trigger,
    analysis_started_at=room.analysis_started_at,
    analysis_completed_at=room.analysis_completed_at,
    analysis_attempt_count=room.analysis_attempt_count,
    analysis_result=_serialize_semantic(room.analysis_result),
    grouping_result=_serialize_grouping(room.grouping_result),
    last_error=room.last_error,
  )


def update_room_record(record: RoomRecord, room: Room) -> None:
  record.join_code = room.join_code
  record.title = room.title
  record.policy = room.policy.value
  record.minimum_group_size = room.group_size.minimum
  record.preferred_group_size = room.group_size.preferred
  record.maximum_group_size = room.group_size.maximum
  record.duration_minutes = room.duration_minutes
  record.status = room.status.value
  record.created_at = room.created_at
  record.updated_at = room.updated_at
  record.started_at = room.started_at
  record.deadline_at = room.deadline_at
  record.analysis_mode = room.analysis_mode
  record.analysis_phase = room.analysis_phase.value
  record.analysis_trigger = room.analysis_trigger
  record.analysis_started_at = room.analysis_started_at
  record.analysis_completed_at = room.analysis_completed_at
  record.analysis_attempt_count = room.analysis_attempt_count
  record.analysis_result = _serialize_semantic(room.analysis_result)
  record.grouping_result = _serialize_grouping(room.grouping_result)
  record.last_error = room.last_error


def child_records_from_domain(
  room: Room,
) -> tuple[
  list[QuestionRecord],
  list[CoverageUnitRecord],
  list[ReferenceMaterialRecord],
  list[ParticipantRecord],
  list[ResponseRecord],
]:
  question_records: list[QuestionRecord] = []
  unit_records: list[CoverageUnitRecord] = []
  for question in sorted(room.questions, key=lambda item: item.position):
    question_records.append(
      QuestionRecord(
        id=question.id,
        room_id=room.id,
        position=question.position,
        prompt=question.prompt,
        reference_material=question.reference_material,
      )
    )
    unit_records.extend(
      CoverageUnitRecord(
        question_id=question.id,
        id=unit.id,
        room_id=room.id,
        position=position,
        text=unit.text,
      )
      for position, unit in enumerate(question.coverage_units)
    )

  material_records = [
    ReferenceMaterialRecord(
      id=attachment.id,
      room_id=room.id,
      file_name=attachment.file_name,
      content_type=attachment.content_type,
      size_bytes=attachment.size_bytes,
      extracted_text=attachment.extracted_text,
      uploaded_at=attachment.uploaded_at,
    )
    for attachment in room.reference_attachments.values()
  ]
  cohort_positions = {participant_id: position for position, participant_id in enumerate(room.cohort_ids)}
  participant_records = [
    ParticipantRecord(
      id=participant.id,
      room_id=room.id,
      display_name=participant.display_name,
      joined_at=participant.joined_at,
      session_nonce=participant.session_nonce,
      submitted_at=participant.submitted_at,
      cohort_position=cohort_positions.get(participant.id),
    )
    for participant in room.participants.values()
  ]
  response_records = [
    ResponseRecord(
      room_id=room.id,
      participant_id=response.participant_id,
      question_id=response.question_id,
      text=response.text,
      updated_at=response.updated_at,
    )
    for response in room.responses.values()
  ]
  return (
    question_records,
    unit_records,
    material_records,
    participant_records,
    response_records,
  )


def _serialize_semantic(value: SemanticArtifact | None) -> dict[str, Any] | None:
  if value is None:
    return None
  return value.model_dump(mode="json", by_alias=True)


def _deserialize_semantic(value: dict[str, Any] | None) -> SemanticArtifact | None:
  if value is None:
    return None
  return SemanticArtifact.model_validate(value)


def _serialize_grouping(
  value: GroupingResult | GroupingArtifact | None,
) -> dict[str, Any] | None:
  if value is None:
    return None
  if isinstance(value, GroupingArtifact):
    return value.model_dump(mode="json", by_alias=True)
  return {
    "generationMode": value.generation_mode,
    "policy": value.policy.value,
    "trigger": value.trigger,
    "generatedAt": value.generated_at.isoformat(),
    "groups": [
      {
        "id": group.id,
        "participantIds": [str(participant_id) for participant_id in group.participant_ids],
      }
      for group in value.groups
    ],
  }


def _deserialize_grouping(
  value: dict[str, Any] | None,
) -> GroupingResult | GroupingArtifact | None:
  if value is None:
    return None
  if value.get("generationMode") == "coverage_aware":
    return GroupingArtifact.model_validate(value)
  groups = cast(Iterable[dict[str, Any]], value.get("groups", []))
  return GroupingResult(
    generation_mode=str(value["generationMode"]),
    policy=GroupingPolicy(str(value["policy"])),
    trigger=str(value["trigger"]),
    generated_at=_DATETIME.validate_python(value["generatedAt"]),
    groups=tuple(
      Group(
        id=str(group["id"]),
        participant_ids=tuple(UUID(str(item)) for item in group["participantIds"]),
      )
      for group in groups
    ),
  )
