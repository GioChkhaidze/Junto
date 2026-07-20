"""Create the minimal durable room aggregate schema.

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260719_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  op.create_table(
    "rooms",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("join_code", sa.String(length=6), nullable=False),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("policy", sa.String(length=16), nullable=False),
    sa.Column("minimum_group_size", sa.Integer(), nullable=False),
    sa.Column("preferred_group_size", sa.Integer(), nullable=False),
    sa.Column("maximum_group_size", sa.Integer(), nullable=False),
    sa.Column("duration_minutes", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(length=24), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
      "analysis_mode",
      sa.String(length=24),
      server_default=sa.text("'placeholder'"),
      nullable=False,
    ),
    sa.Column(
      "analysis_phase",
      sa.String(length=32),
      server_default=sa.text("'not_started'"),
      nullable=False,
    ),
    sa.Column("analysis_trigger", sa.String(length=32), nullable=True),
    sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("analysis_completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("analysis_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    sa.Column("analysis_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("grouping_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("last_error", sa.Text(), nullable=True),
    sa.CheckConstraint(
      "(started_at IS NULL AND deadline_at IS NULL) OR "
      "(started_at IS NOT NULL AND deadline_at IS NOT NULL AND deadline_at >= started_at)",
      name=op.f("ck_rooms_activity_times_consistent"),
    ),
    sa.CheckConstraint(
      "analysis_attempt_count >= 0",
      name=op.f("ck_rooms_analysis_attempt_count_nonnegative"),
    ),
    sa.CheckConstraint(
      "analysis_mode IN ('placeholder', 'coverage_aware')",
      name=op.f("ck_rooms_analysis_mode_known"),
    ),
    sa.CheckConstraint(
      "analysis_phase IN ('not_started', 'analyzing_responses', 'forming_groups', 'complete', 'failed')",
      name=op.f("ck_rooms_analysis_phase_known"),
    ),
    sa.CheckConstraint(
      "duration_minutes BETWEEN 1 AND 180",
      name=op.f("ck_rooms_duration_minutes_range"),
    ),
    sa.CheckConstraint("char_length(join_code) = 6", name=op.f("ck_rooms_join_code_length")),
    sa.CheckConstraint(
      "maximum_group_size BETWEEN 2 AND 8",
      name=op.f("ck_rooms_maximum_group_size_range"),
    ),
    sa.CheckConstraint(
      "minimum_group_size BETWEEN 2 AND 8",
      name=op.f("ck_rooms_minimum_group_size_range"),
    ),
    sa.CheckConstraint("policy IN ('teach', 'explore')", name=op.f("ck_rooms_policy_known")),
    sa.CheckConstraint(
      "preferred_group_size BETWEEN minimum_group_size AND maximum_group_size",
      name=op.f("ck_rooms_preferred_group_size_range"),
    ),
    sa.CheckConstraint(
      "status IN ('draft', 'lobby', 'answering', 'analyzing', 'published', 'failed')",
      name=op.f("ck_rooms_status_known"),
    ),
    sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_rooms_title_not_blank")),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
    sa.UniqueConstraint("join_code", name="uq_rooms_join_code"),
  )
  op.create_index("ix_rooms_status_deadline", "rooms", ["status", "deadline_at"])

  op.create_table(
    "questions",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("prompt", sa.Text(), nullable=False),
    sa.Column("reference_material", sa.Text(), nullable=True),
    sa.CheckConstraint("position >= 0", name=op.f("ck_questions_position_nonnegative")),
    sa.CheckConstraint("btrim(prompt) <> ''", name=op.f("ck_questions_prompt_not_blank")),
    sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_questions_room_id_rooms", ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
    sa.UniqueConstraint("room_id", "id", name="uq_questions_room_id_id"),
    sa.UniqueConstraint("room_id", "position", name="uq_questions_room_position"),
  )
  op.create_index("ix_questions_room_position", "questions", ["room_id", "position"])

  op.create_table(
    "reference_materials",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("file_name", sa.String(length=160), nullable=False),
    sa.Column("content_type", sa.String(length=160), nullable=False),
    sa.Column("size_bytes", sa.Integer(), nullable=False),
    sa.Column("extracted_text", sa.Text(), nullable=False),
    sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
      "btrim(content_type) <> ''",
      name=op.f("ck_reference_materials_content_type_not_blank"),
    ),
    sa.CheckConstraint(
      "btrim(file_name) <> ''",
      name=op.f("ck_reference_materials_file_name_not_blank"),
    ),
    sa.CheckConstraint("size_bytes > 0", name=op.f("ck_reference_materials_size_bytes_positive")),
    sa.ForeignKeyConstraint(
      ["room_id"],
      ["rooms.id"],
      name="fk_reference_materials_room_id_rooms",
      ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_materials")),
  )
  op.create_index(
    "ix_reference_materials_room_uploaded",
    "reference_materials",
    ["room_id", "uploaded_at"],
  )

  op.create_table(
    "participants",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("display_name", sa.String(length=160), nullable=False),
    sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("session_nonce", sa.String(length=160), nullable=False),
    sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("cohort_position", sa.Integer(), nullable=True),
    sa.CheckConstraint(
      "cohort_position IS NULL OR cohort_position >= 0",
      name=op.f("ck_participants_cohort_position_nonnegative"),
    ),
    sa.CheckConstraint(
      "btrim(display_name) <> ''",
      name=op.f("ck_participants_display_name_not_blank"),
    ),
    sa.CheckConstraint(
      "btrim(session_nonce) <> ''",
      name=op.f("ck_participants_session_nonce_not_blank"),
    ),
    sa.ForeignKeyConstraint(
      ["room_id"],
      ["rooms.id"],
      name="fk_participants_room_id_rooms",
      ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_participants")),
    sa.UniqueConstraint(
      "room_id",
      "cohort_position",
      name="uq_participants_room_cohort_position",
    ),
    sa.UniqueConstraint("room_id", "id", name="uq_participants_room_id_id"),
    sa.UniqueConstraint("room_id", "session_nonce", name="uq_participants_room_session_nonce"),
  )
  op.create_index("ix_participants_room_joined", "participants", ["room_id", "joined_at"])
  op.create_index("ix_participants_room_submitted", "participants", ["room_id", "submitted_at"])

  op.create_table(
    "coverage_units",
    sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("id", sa.String(length=80), nullable=False),
    sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("text", sa.Text(), nullable=False),
    sa.CheckConstraint("position >= 0", name=op.f("ck_coverage_units_position_nonnegative")),
    sa.CheckConstraint("btrim(text) <> ''", name=op.f("ck_coverage_units_text_not_blank")),
    sa.ForeignKeyConstraint(
      ["room_id", "question_id"],
      ["questions.room_id", "questions.id"],
      name="fk_coverage_units_room_question_questions",
      ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("question_id", "id", name="pk_coverage_units"),
    sa.UniqueConstraint("question_id", "position", name="uq_coverage_units_question_position"),
  )
  op.create_index("ix_coverage_units_room_question", "coverage_units", ["room_id", "question_id"])

  op.create_table(
    "responses",
    sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("text", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("btrim(text) <> ''", name=op.f("ck_responses_text_not_blank")),
    sa.ForeignKeyConstraint(
      ["room_id", "participant_id"],
      ["participants.room_id", "participants.id"],
      name="fk_responses_room_participant_participants",
      ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
      ["room_id", "question_id"],
      ["questions.room_id", "questions.id"],
      name="fk_responses_room_question_questions",
      ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("participant_id", "question_id", name="pk_responses"),
  )
  op.create_index("ix_responses_room_participant", "responses", ["room_id", "participant_id"])
  op.create_index("ix_responses_room_question", "responses", ["room_id", "question_id"])


def downgrade() -> None:
  op.drop_index("ix_responses_room_question", table_name="responses")
  op.drop_index("ix_responses_room_participant", table_name="responses")
  op.drop_table("responses")
  op.drop_index("ix_coverage_units_room_question", table_name="coverage_units")
  op.drop_table("coverage_units")
  op.drop_index("ix_participants_room_submitted", table_name="participants")
  op.drop_index("ix_participants_room_joined", table_name="participants")
  op.drop_table("participants")
  op.drop_index("ix_reference_materials_room_uploaded", table_name="reference_materials")
  op.drop_table("reference_materials")
  op.drop_index("ix_questions_room_position", table_name="questions")
  op.drop_table("questions")
  op.drop_index("ix_rooms_status_deadline", table_name="rooms")
  op.drop_table("rooms")
