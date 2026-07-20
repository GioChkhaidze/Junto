from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from junto.domain.entities import AnalysisPhase, GroupingPolicy, RoomStatus
from junto.engine.models import CompleteCoverageStatus, SolverStatus


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


class AuthoringQuestionDraft(ApiModel):
  prompt: str = Field(default="", max_length=2_000)
  coverageUnits: list[Annotated[str, Field(max_length=240)]] = Field(
    default_factory=list,
    max_length=8,
  )


class AuthoringSuggestionRequest(ApiModel):
  activityTitle: str = Field(default="", max_length=120)
  target: Literal["question", "coverage"]
  targetQuestionIndex: int = Field(ge=0, le=7)
  questions: list[AuthoringQuestionDraft] = Field(min_length=1, max_length=8)
  referenceText: str | None = Field(default=None, max_length=8_000)

  @model_validator(mode="after")
  def validate_target_question(self) -> Self:
    if self.targetQuestionIndex >= len(self.questions):
      raise ValueError("The target question must be present in the draft.")
    return self


class AuthoringSuggestionResponse(ApiModel):
  questionPrompt: str = Field(min_length=5, max_length=2_000)
  coverageUnits: list[Annotated[str, Field(min_length=3, max_length=240)]] = Field(
    min_length=1,
    max_length=8,
  )


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


class StartEligibilityView(ApiModel):
  eligible: bool
  reasonCode: (
    Literal[
      "room_not_in_lobby",
      "minimum_participants",
      "group_size_infeasible",
    ]
    | None
  )
  message: str


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
  analysisMode: Literal["placeholder", "coverage_aware"]
  questions: list[QuestionView]
  materials: list[MaterialView]
  participants: list[HostParticipantView]
  progress: ProgressView
  startEligibility: StartEligibilityView
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
  analysisMode: Literal["placeholder", "coverage_aware"]


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
  analysisMode: Literal["placeholder", "coverage_aware"]
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
  analysisMode: Literal["placeholder", "coverage_aware"]
  allowedActions: list[str]
  startEligibility: StartEligibilityView | None = None
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


class SyntheticClassroomView(ApiModel):
  enabled: bool
  stage: RoomStatus
  syntheticParticipantCount: int = Field(ge=0, le=20)
  pendingSyntheticParticipantCount: int = Field(ge=0, le=20)
  targetSizes: list[int]
  canConfigure: bool
  canGenerate: bool
  patternedAvailable: bool
  openRouterAvailable: bool


class SyntheticCohortWrite(ApiModel):
  targetSize: int = Field(ge=0, le=20)
  seed: int = Field(default=41, ge=0, le=2_147_483_647)


class SyntheticResponsesWrite(ApiModel):
  source: Literal["patterned", "openrouter"] = "patterned"


class SyntheticResponsesResultView(ApiModel):
  simulation: SyntheticClassroomView
  source: Literal["patterned", "openrouter"]
  participantCount: int = Field(ge=0, le=20)
  responseCount: int = Field(ge=0)
  models: list[str]


class GroupMemberView(ApiModel):
  participantId: UUID
  displayName: str


class GroupView(ApiModel):
  id: str
  members: list[GroupMemberView]


class PlaceholderGroupsView(ApiModel):
  generationMode: Literal["placeholder"] = "placeholder"
  policy: GroupingPolicy
  trigger: str
  generatedAt: datetime
  groups: list[GroupView]


class PlaceholderMyGroupView(ApiModel):
  generationMode: Literal["placeholder"] = "placeholder"
  policy: GroupingPolicy
  generatedAt: datetime
  group: GroupView


class ObjectiveView(ApiModel):
  name: str
  value: int
  provenOptimal: bool


class SolverView(ApiModel):
  status: SolverStatus
  completeCoverageStatus: CompleteCoverageStatus
  timedOut: bool
  solveMilliseconds: int
  objectives: list[ObjectiveView]


class CoverageCarrierView(ApiModel):
  participantId: UUID
  displayName: str


class CoverageUnitResultView(ApiModel):
  id: str
  text: str
  covered: bool
  carriers: list[CoverageCarrierView]


class RepresentedFamilyView(ApiModel):
  id: str
  label: str
  members: list[GroupMemberView]


class ResponseFamilyView(ApiModel):
  id: str
  label: str


class ResponseAuditView(ApiModel):
  participant: GroupMemberView
  answer: str | None
  coveredUnitIds: list[str]
  family: ResponseFamilyView | None


class GroupQuestionResultView(ApiModel):
  questionId: UUID
  position: int
  prompt: str
  fullyCovered: bool
  units: list[CoverageUnitResultView]
  representedFamilies: list[RepresentedFamilyView]
  responseAudit: list[ResponseAuditView]


class CoverageGroupView(ApiModel):
  id: str
  members: list[GroupMemberView]
  questions: list[GroupQuestionResultView]


class AgendaQuestionView(ApiModel):
  questionId: UUID
  position: int
  prompt: str
  fullyCovered: bool
  units: list[CoverageUnitResultView]
  representedFamilies: list[RepresentedFamilyView]


class ParticipantCoverageGroupView(ApiModel):
  id: str
  members: list[GroupMemberView]
  questions: list[AgendaQuestionView]


class CoverageReportView(ApiModel):
  fullyCoveredGroupQuestions: int
  totalGroupQuestions: int


class CoverageGroupsView(ApiModel):
  generationMode: Literal["coverage_aware"] = "coverage_aware"
  policy: GroupingPolicy
  trigger: str
  generatedAt: datetime
  solver: SolverView
  coverageReport: CoverageReportView
  groups: list[CoverageGroupView]


class CoverageMyGroupView(ApiModel):
  generationMode: Literal["coverage_aware"] = "coverage_aware"
  policy: GroupingPolicy
  generatedAt: datetime
  completeCoverageStatus: CompleteCoverageStatus
  group: ParticipantCoverageGroupView


GroupsView = PlaceholderGroupsView | CoverageGroupsView
MyGroupView = PlaceholderMyGroupView | CoverageMyGroupView
