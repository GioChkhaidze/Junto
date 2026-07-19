from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RoomStatus(StrEnum):
    DRAFT = "draft"
    LOBBY = "lobby"
    ANSWERING = "answering"
    ANALYZING = "analyzing"
    PUBLISHED = "published"
    FAILED = "failed"


class GroupingPolicy(StrEnum):
    TEACH = "teach"
    EXPLORE = "explore"


class AnalysisPhase(StrEnum):
    NOT_STARTED = "not_started"
    ANALYZING_RESPONSES = "analyzing_responses"
    FORMING_GROUPS = "forming_groups"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class GroupSize:
    minimum: int
    preferred: int
    maximum: int


@dataclass(slots=True)
class CoverageUnit:
    id: str
    text: str


@dataclass(slots=True)
class Question:
    id: UUID
    position: int
    prompt: str
    reference_material: str | None = None
    coverage_units: list[CoverageUnit] = field(default_factory=list)


@dataclass(slots=True)
class ReferenceAttachment:
    id: UUID
    file_name: str
    content_type: str
    size_bytes: int
    extracted_text: str
    uploaded_at: datetime


@dataclass(slots=True)
class Participant:
    id: UUID
    display_name: str
    joined_at: datetime
    session_nonce: str
    submitted_at: datetime | None = None


@dataclass(slots=True)
class Response:
    participant_id: UUID
    question_id: UUID
    text: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AnswerSaveResult:
    question_id: UUID
    text: str
    saved_at: datetime
    answered_question_count: int


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    participant_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class GroupingResult:
    generation_mode: str
    policy: GroupingPolicy
    trigger: str
    generated_at: datetime
    groups: tuple[Group, ...]


@dataclass(slots=True)
class Room:
    id: UUID
    join_code: str
    title: str
    policy: GroupingPolicy
    group_size: GroupSize
    duration_minutes: int
    status: RoomStatus
    created_at: datetime
    updated_at: datetime
    questions: list[Question] = field(default_factory=list)
    participants: dict[UUID, Participant] = field(default_factory=dict)
    responses: dict[tuple[UUID, UUID], Response] = field(default_factory=dict)
    reference_attachments: dict[UUID, ReferenceAttachment] = field(default_factory=dict)
    cohort_ids: tuple[UUID, ...] = ()
    started_at: datetime | None = None
    deadline_at: datetime | None = None
    analysis_phase: AnalysisPhase = AnalysisPhase.NOT_STARTED
    analysis_trigger: str | None = None
    grouping_result: GroupingResult | None = None
    last_error: str | None = None

    @property
    def activity_started(self) -> bool:
        return self.status not in {RoomStatus.DRAFT, RoomStatus.LOBBY}
