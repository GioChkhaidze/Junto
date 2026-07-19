from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from junto.domain.entities import AnalysisPhase, GroupingPolicy, RoomStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GroupSizeDto(ApiModel):
    minimum: int = Field(default=3, ge=2, le=8)
    preferred: int = Field(default=4, ge=2, le=8)
    maximum: int = Field(default=5, ge=2, le=8)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if not self.minimum <= self.preferred <= self.maximum:
            raise ValueError("Group sizes must satisfy minimum <= preferred <= maximum.")
        return self


class RoomCreate(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    policy: GroupingPolicy = GroupingPolicy.TEACH
    groupSize: GroupSizeDto = Field(default_factory=GroupSizeDto)
    durationMinutes: int = Field(default=20, ge=1, le=180)


class RoomPatch(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    policy: GroupingPolicy | None = None
    groupSize: GroupSizeDto | None = None
    durationMinutes: int | None = Field(default=None, ge=1, le=180)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one room field is required.")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("Room fields cannot be null.")
        return self


class CoverageUnitWrite(ApiModel):
    id: str | None = Field(default=None, min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=300)


class CoverageUnitView(ApiModel):
    id: str
    text: str


class QuestionCreate(ApiModel):
    position: int | None = Field(default=None, ge=0)
    prompt: str = Field(min_length=1, max_length=4_000)
    referenceMaterial: str | None = Field(default=None, max_length=8_000)
    coverageUnits: list[CoverageUnitWrite] = Field(default_factory=list, max_length=8)


class QuestionPatch(ApiModel):
    position: int | None = Field(default=None, ge=0)
    prompt: str | None = Field(default=None, min_length=1, max_length=4_000)
    referenceMaterial: str | None = Field(default=None, max_length=8_000)
    coverageUnits: list[CoverageUnitWrite] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one question field is required.")
        nullable_fields = self.model_fields_set - {"referenceMaterial"}
        if any(getattr(self, field_name) is None for field_name in nullable_fields):
            raise ValueError("Question fields other than referenceMaterial cannot be null.")
        return self


class QuestionView(ApiModel):
    id: UUID
    position: int
    prompt: str
    referenceMaterial: str | None
    coverageUnits: list[CoverageUnitView]


class ParticipantQuestionView(ApiModel):
    id: UUID
    position: int
    prompt: str
    answer: str | None


class MaterialView(ApiModel):
    id: UUID
    fileName: str
    mediaType: str
    sizeBytes: int
    extractedCharacterCount: int
    uploadedAt: datetime


class MaterialUploadResponse(ApiModel):
    material: MaterialView


class ProgressView(ApiModel):
    participantCount: int
    submittedParticipantCount: int
    answeredResponseCount: int
    submittedResponseCount: int
    possibleResponseCount: int


class HostParticipantView(ApiModel):
    participantId: UUID
    displayName: str
    submittedAt: datetime | None


class RoomCreated(ApiModel):
    roomId: UUID
    joinCode: str
    status: RoomStatus


class HostRoomView(ApiModel):
    id: UUID
    joinCode: str
    title: str
    policy: GroupingPolicy
    groupSize: GroupSizeDto
    durationMinutes: int
    status: RoomStatus
    activityStarted: bool
    startedAt: datetime | None
    deadlineAt: datetime | None
    serverTime: datetime
    remainingSeconds: int | None
    analysisPhase: AnalysisPhase
    questions: list[QuestionView]
    materials: list[MaterialView]
    participants: list[HostParticipantView]
    progress: ProgressView
    allowedActions: list[str]
    lastError: str | None


class SessionView(ApiModel):
    csrfToken: str
    hostRoomIds: list[UUID]
    participantRoomIds: list[UUID]


class JoinLookupView(ApiModel):
    title: str
    status: RoomStatus
    durationMinutes: int
    questionCount: int


class JoinRequest(ApiModel):
    displayName: str = Field(min_length=1, max_length=80)


class JoinResponse(ApiModel):
    roomId: UUID
    participantId: UUID
    displayName: str


class ParticipantIdentityView(ApiModel):
    participantId: UUID
    displayName: str
    submittedAt: datetime | None


class ParticipantRoomView(ApiModel):
    roomId: UUID
    title: str
    status: RoomStatus
    activityStarted: bool
    durationMinutes: int
    startedAt: datetime | None
    deadlineAt: datetime | None
    serverTime: datetime
    remainingSeconds: int | None
    analysisPhase: AnalysisPhase
    participant: ParticipantIdentityView
    questions: list[ParticipantQuestionView]
    answeredQuestionCount: int
    questionCount: int
    submitted: bool
    submittedAt: datetime | None
    allowedActions: list[str]


class AnswerWrite(ApiModel):
    text: str = Field(max_length=1_500)


class AnswerReceipt(ApiModel):
    questionId: UUID
    text: str
    savedAt: datetime
    answeredQuestionCount: int


class SubmissionView(ApiModel):
    submitted: bool
    submittedAt: datetime
    status: RoomStatus
    answeredQuestionCount: int
    questionCount: int
    analysisStarted: bool


class StatusView(ApiModel):
    status: RoomStatus
    activityStarted: bool
    startedAt: datetime | None
    deadlineAt: datetime | None
    serverTime: datetime
    remainingSeconds: int | None
    analysisPhase: AnalysisPhase
    allowedActions: list[str]
    progress: ProgressView | None = None
    participantCount: int | None = None
    submittedParticipantCount: int | None = None
    answeredResponseCount: int | None = None
    submittedResponseCount: int | None = None
    possibleResponseCount: int | None = None
    submitted: bool | None = None
    submittedAt: datetime | None = None
    answeredQuestionCount: int | None = None
    questionCount: int | None = None


class AnalysisAccepted(ApiModel):
    status: RoomStatus
    analysisPhase: AnalysisPhase


class GroupMemberView(ApiModel):
    participantId: UUID
    displayName: str


class GroupView(ApiModel):
    id: str
    members: list[GroupMemberView]


class GroupsView(ApiModel):
    generationMode: str
    policy: GroupingPolicy
    trigger: str
    generatedAt: datetime
    groups: list[GroupView]


class MyGroupView(ApiModel):
    generationMode: str
    policy: GroupingPolicy
    generatedAt: datetime
    group: GroupView


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(ApiModel):
    error: ErrorBody
