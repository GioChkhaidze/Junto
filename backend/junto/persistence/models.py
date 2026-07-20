from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
  CheckConstraint,
  DateTime,
  ForeignKey,
  ForeignKeyConstraint,
  Index,
  Integer,
  MetaData,
  PrimaryKeyConstraint,
  String,
  Text,
  UniqueConstraint,
  func,
  text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
  "ix": "ix_%(table_name)s_%(column_0_name)s",
  "uq": "uq_%(table_name)s_%(column_0_name)s",
  "ck": "ck_%(table_name)s_%(constraint_name)s",
  "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
  "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
  metadata = MetaData(naming_convention=NAMING_CONVENTION)


class RoomRecord(Base):
  __tablename__ = "rooms"
  __table_args__ = (
    UniqueConstraint("join_code", name="uq_rooms_join_code"),
    CheckConstraint("char_length(join_code) = 6", name="join_code_length"),
    CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
    CheckConstraint("policy IN ('teach', 'explore')", name="policy_known"),
    CheckConstraint("minimum_group_size BETWEEN 2 AND 8", name="minimum_group_size_range"),
    CheckConstraint(
      "preferred_group_size BETWEEN minimum_group_size AND maximum_group_size",
      name="preferred_group_size_range",
    ),
    CheckConstraint("maximum_group_size BETWEEN 2 AND 8", name="maximum_group_size_range"),
    CheckConstraint("duration_minutes BETWEEN 1 AND 180", name="duration_minutes_range"),
    CheckConstraint(
      "status IN ('draft', 'lobby', 'answering', 'analyzing', 'published', 'failed')",
      name="status_known",
    ),
    CheckConstraint(
      "analysis_phase IN ('not_started', 'analyzing_responses', 'forming_groups', 'complete', 'failed')",
      name="analysis_phase_known",
    ),
    CheckConstraint(
      "analysis_mode IN ('placeholder', 'coverage_aware')",
      name="analysis_mode_known",
    ),
    CheckConstraint("analysis_attempt_count >= 0", name="analysis_attempt_count_nonnegative"),
    CheckConstraint(
      "(started_at IS NULL AND deadline_at IS NULL) OR "
      "(started_at IS NOT NULL AND deadline_at IS NOT NULL AND deadline_at >= started_at)",
      name="activity_times_consistent",
    ),
    Index("ix_rooms_status_deadline", "status", "deadline_at"),
  )

  id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
  join_code: Mapped[str] = mapped_column(String(6), nullable=False)
  title: Mapped[str] = mapped_column(Text, nullable=False)
  policy: Mapped[str] = mapped_column(String(16), nullable=False)
  minimum_group_size: Mapped[int] = mapped_column(Integer, nullable=False)
  preferred_group_size: Mapped[int] = mapped_column(Integer, nullable=False)
  maximum_group_size: Mapped[int] = mapped_column(Integer, nullable=False)
  duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
  status: Mapped[str] = mapped_column(String(24), nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
  started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  analysis_mode: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'placeholder'"))
  analysis_phase: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'not_started'"))
  analysis_trigger: Mapped[str | None] = mapped_column(String(32))
  analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  analysis_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
  analysis_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
  grouping_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
  last_error: Mapped[str | None] = mapped_column(Text)


class QuestionRecord(Base):
  __tablename__ = "questions"
  __table_args__ = (
    UniqueConstraint("room_id", "id", name="uq_questions_room_id_id"),
    UniqueConstraint("room_id", "position", name="uq_questions_room_position"),
    CheckConstraint("position >= 0", name="position_nonnegative"),
    CheckConstraint("btrim(prompt) <> ''", name="prompt_not_blank"),
    Index("ix_questions_room_position", "room_id", "position"),
  )

  id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
  room_id: Mapped[UUID] = mapped_column(
    PostgreSQLUUID(as_uuid=True),
    ForeignKey("rooms.id", ondelete="CASCADE", name="fk_questions_room_id_rooms"),
    nullable=False,
  )
  position: Mapped[int] = mapped_column(Integer, nullable=False)
  prompt: Mapped[str] = mapped_column(Text, nullable=False)
  reference_material: Mapped[str | None] = mapped_column(Text)


class CoverageUnitRecord(Base):
  __tablename__ = "coverage_units"
  __table_args__ = (
    PrimaryKeyConstraint("question_id", "id", name="pk_coverage_units"),
    ForeignKeyConstraint(
      ["room_id", "question_id"],
      ["questions.room_id", "questions.id"],
      ondelete="CASCADE",
      name="fk_coverage_units_room_question_questions",
    ),
    UniqueConstraint("question_id", "position", name="uq_coverage_units_question_position"),
    CheckConstraint("position >= 0", name="position_nonnegative"),
    CheckConstraint("btrim(text) <> ''", name="text_not_blank"),
    Index("ix_coverage_units_room_question", "room_id", "question_id"),
  )

  question_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
  id: Mapped[str] = mapped_column(String(80), nullable=False)
  room_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
  position: Mapped[int] = mapped_column(Integer, nullable=False)
  text: Mapped[str] = mapped_column(Text, nullable=False)


class ReferenceMaterialRecord(Base):
  __tablename__ = "reference_materials"
  __table_args__ = (
    CheckConstraint("btrim(file_name) <> ''", name="file_name_not_blank"),
    CheckConstraint("btrim(content_type) <> ''", name="content_type_not_blank"),
    CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
    Index("ix_reference_materials_room_uploaded", "room_id", "uploaded_at"),
  )

  id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
  room_id: Mapped[UUID] = mapped_column(
    PostgreSQLUUID(as_uuid=True),
    ForeignKey("rooms.id", ondelete="CASCADE", name="fk_reference_materials_room_id_rooms"),
    nullable=False,
  )
  file_name: Mapped[str] = mapped_column(String(160), nullable=False)
  content_type: Mapped[str] = mapped_column(String(160), nullable=False)
  size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
  extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
  uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParticipantRecord(Base):
  __tablename__ = "participants"
  __table_args__ = (
    UniqueConstraint("room_id", "id", name="uq_participants_room_id_id"),
    UniqueConstraint("room_id", "session_nonce", name="uq_participants_room_session_nonce"),
    UniqueConstraint("room_id", "cohort_position", name="uq_participants_room_cohort_position"),
    CheckConstraint("btrim(display_name) <> ''", name="display_name_not_blank"),
    CheckConstraint("btrim(session_nonce) <> ''", name="session_nonce_not_blank"),
    CheckConstraint("cohort_position IS NULL OR cohort_position >= 0", name="cohort_position_nonnegative"),
    Index("ix_participants_room_joined", "room_id", "joined_at"),
    Index("ix_participants_room_submitted", "room_id", "submitted_at"),
  )

  id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
  room_id: Mapped[UUID] = mapped_column(
    PostgreSQLUUID(as_uuid=True),
    ForeignKey("rooms.id", ondelete="CASCADE", name="fk_participants_room_id_rooms"),
    nullable=False,
  )
  display_name: Mapped[str] = mapped_column(String(160), nullable=False)
  joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  session_nonce: Mapped[str] = mapped_column(String(160), nullable=False)
  submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  cohort_position: Mapped[int | None] = mapped_column(Integer)


class ResponseRecord(Base):
  __tablename__ = "responses"
  __table_args__ = (
    PrimaryKeyConstraint("participant_id", "question_id", name="pk_responses"),
    ForeignKeyConstraint(
      ["room_id", "participant_id"],
      ["participants.room_id", "participants.id"],
      ondelete="CASCADE",
      name="fk_responses_room_participant_participants",
    ),
    ForeignKeyConstraint(
      ["room_id", "question_id"],
      ["questions.room_id", "questions.id"],
      ondelete="CASCADE",
      name="fk_responses_room_question_questions",
    ),
    CheckConstraint("btrim(text) <> ''", name="text_not_blank"),
    Index("ix_responses_room_question", "room_id", "question_id"),
    Index("ix_responses_room_participant", "room_id", "participant_id"),
  )

  room_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
  participant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
  question_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
  text: Mapped[str] = mapped_column(Text, nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
