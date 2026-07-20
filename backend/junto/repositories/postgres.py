from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from junto.domain.entities import Room
from junto.domain.errors import DomainError, conflict, not_found
from junto.persistence.mappers import (
  child_records_from_domain,
  load_room_aggregate,
  room_record_from_domain,
  update_room_record,
)
from junto.persistence.models import (
  CoverageUnitRecord,
  ParticipantRecord,
  QuestionRecord,
  ReferenceMaterialRecord,
  ResponseRecord,
  RoomRecord,
)


class PostgresRoomRepository:
  """SQLAlchemy adapter preserving Junto's room-aggregate transaction protocol.

  Every mutation locks the parent room row before hydrating or replacing its
  children. That one lock serializes cohort freeze, answer/deadline races,
  analysis claims, and publication without leaking database objects into the
  domain layer.
  """

  def __init__(self, session_factory: sessionmaker[Session]) -> None:
    self._session_factory = session_factory

  def add(self, room: Room) -> None:
    try:
      with self._session_factory.begin() as session:
        session.add(room_record_from_domain(room))
        session.flush()
        self._insert_children(session, room)
    except IntegrityError as error:
      raise self._translate_integrity_error(error) from error

  def get(self, room_id: UUID) -> Room | None:
    with self._session_factory() as session:
      record = session.scalar(select(RoomRecord).where(RoomRecord.id == room_id))
      return load_room_aggregate(session, record) if record is not None else None

  def get_by_join_code(self, join_code: str) -> Room | None:
    with self._session_factory() as session:
      record = session.scalar(select(RoomRecord).where(RoomRecord.join_code == join_code))
      return load_room_aggregate(session, record) if record is not None else None

  def ping(self) -> bool:
    try:
      with self._session_factory() as session:
        session.execute(select(1))
      return True
    except SQLAlchemyError:
      return False

  def delete(self, room_id: UUID) -> bool:
    with self._session_factory.begin() as session:
      result = cast(
        CursorResult[Any],
        session.execute(delete(RoomRecord).where(RoomRecord.id == room_id)),
      )
      return result.rowcount > 0

  def delete_expired(self, *, before: datetime, answering_before: datetime) -> int:
    with self._session_factory.begin() as session:
      result = cast(
        CursorResult[Any],
        session.execute(
          delete(RoomRecord).where(
            RoomRecord.updated_at < before,
            or_(
              RoomRecord.status.in_(("draft", "lobby", "published", "failed")),
              and_(
                RoomRecord.status == "answering",
                RoomRecord.deadline_at.is_not(None),
                RoomRecord.deadline_at < answering_before,
              ),
            ),
          )
        ),
      )
      return result.rowcount

  def recover_stale_analyses(self, *, before: datetime, failed_at: datetime) -> int:
    with self._session_factory.begin() as session:
      result = cast(
        CursorResult[Any],
        session.execute(
          update(RoomRecord)
          .where(
            RoomRecord.status == "analyzing",
            func.coalesce(RoomRecord.analysis_started_at, RoomRecord.updated_at) < before,
          )
          .values(
            status="failed",
            analysis_phase="failed",
            analysis_result=None,
            grouping_result=None,
            analysis_completed_at=failed_at,
            last_error="Analysis was interrupted. The host can retry once.",
            updated_at=failed_at,
          )
        ),
      )
      return result.rowcount

  @contextmanager
  def transaction(self, room_id: UUID) -> Iterator[Room]:
    try:
      with self._session_factory.begin() as session:
        record = session.scalar(select(RoomRecord).where(RoomRecord.id == room_id).with_for_update())
        if record is None:
          raise not_found()
        working = load_room_aggregate(session, record)
        yield working
        update_room_record(record, working)
        self._replace_children(session, working)
        session.flush()
    except IntegrityError as error:
      raise self._translate_integrity_error(error) from error

  def _replace_children(self, session: Session, room: Room) -> None:
    room_id = room.id
    session.execute(delete(ResponseRecord).where(ResponseRecord.room_id == room_id))
    session.execute(delete(CoverageUnitRecord).where(CoverageUnitRecord.room_id == room_id))
    session.execute(delete(ReferenceMaterialRecord).where(ReferenceMaterialRecord.room_id == room_id))
    session.execute(delete(ParticipantRecord).where(ParticipantRecord.room_id == room_id))
    session.execute(delete(QuestionRecord).where(QuestionRecord.room_id == room_id))
    session.flush()
    self._insert_children(session, room)

  @staticmethod
  def _insert_children(session: Session, room: Room) -> None:
    questions, units, materials, participants, responses = child_records_from_domain(room)
    session.add_all([*questions, *materials, *participants])
    session.flush()
    session.add_all([*units, *responses])
    session.flush()

  @staticmethod
  def _translate_integrity_error(error: IntegrityError) -> DomainError:
    diagnostic = getattr(error.orig, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint == "uq_rooms_join_code":
      return conflict("JOIN_CODE_COLLISION", "The join code is already in use.")
    if constraint == "pk_rooms":
      return conflict("ROOM_ALREADY_EXISTS", "The room already exists.")
    if constraint == "uq_participants_room_session_nonce":
      return conflict(
        "PARTICIPANT_SESSION_COLLISION",
        "This browser session already joined the room.",
      )
    return conflict(
      "PERSISTENCE_CONFLICT",
      "The room changed concurrently or violates a persistence constraint.",
    )
