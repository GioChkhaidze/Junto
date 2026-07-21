from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Literal, cast
from uuid import UUID

from junto.api.schemas import (
  ActivitySummaryView,
  AgendaQuestionView,
  CoverageCarrierView,
  CoverageGroupsView,
  CoverageGroupView,
  CoverageMyGroupView,
  CoverageReportView,
  CoverageUnitResultView,
  CoverageUnitView,
  GroupMemberView,
  GroupQuestionResultView,
  GroupSizeDto,
  GroupsView,
  GroupView,
  HostParticipantView,
  HostRoomView,
  MaterialView,
  MyGroupView,
  ObjectiveView,
  ParticipantCoverageGroupView,
  ParticipantIdentityView,
  ParticipantQuestionView,
  ParticipantRoomView,
  PlaceholderGroupsView,
  PlaceholderMyGroupView,
  ProgressView,
  QuestionView,
  RepresentedFamilyView,
  ResponseAuditView,
  ResponseFamilyView,
  SolverView,
  StartEligibilityView,
  StatusView,
)
from junto.domain.entities import (
  GroupingPolicy,
  Participant,
  Question,
  ReferenceAttachment,
  Room,
  RoomStatus,
)
from junto.domain.errors import DomainError, conflict, not_found
from junto.domain.grouping import balanced_capacities
from junto.engine.models import EngineGroup, GroupingArtifact, QuestionSemanticArtifact


def host_room_view(room: Room, *, now: datetime) -> HostRoomView:
  return HostRoomView(
    id=room.id,
    joinCode=room.join_code,
    title=room.title,
    policy=room.policy,
    groupSize=GroupSizeDto(
      minimum=room.group_size.minimum,
      preferred=room.group_size.preferred,
      maximum=room.group_size.maximum,
    ),
    durationMinutes=room.duration_minutes,
    status=room.status,
    activityStarted=room.activity_started,
    startedAt=room.started_at,
    deadlineAt=room.deadline_at,
    serverTime=now,
    remainingSeconds=remaining_seconds(room, now),
    analysisPhase=room.analysis_phase,
    analysisMode=cast(Literal["placeholder", "coverage_aware"], room.analysis_mode),
    questions=[question_view(question) for question in sorted_questions(room)],
    materials=[material_view(item) for item in room.reference_attachments.values()],
    participants=[
      HostParticipantView(
        participantId=participant.id,
        displayName=participant.display_name,
        submittedAt=participant.submitted_at,
      )
      for participant in sorted(
        room.participants.values(),
        key=lambda item: (item.joined_at, str(item.id)),
      )
    ],
    progress=progress_view(room),
    startEligibility=start_eligibility_view(room),
    allowedActions=host_actions(room),
    lastError=room.last_error,
  )


def activity_summary_view(room: Room, *, can_delete: bool = True) -> ActivitySummaryView:
  result = room.grouping_result
  group_count = len(result.groups) if result is not None else 0
  generation_mode: Literal["placeholder", "coverage_aware"] | None = None
  fully_covered: int | None = None
  total: int | None = None
  if result is not None:
    generation_mode = cast(Literal["placeholder", "coverage_aware"], result.generation_mode)
    if isinstance(result, GroupingArtifact):
      coverage_groups = [_coverage_host_group_view(room, group) for group in result.groups]
      fully_covered = sum(question.fullyCovered for group in coverage_groups for question in group.questions)
      total = len(coverage_groups) * len(room.questions)
  return ActivitySummaryView(
    roomId=room.id,
    joinCode=room.join_code if can_delete else None,
    canDelete=can_delete,
    title=room.title,
    status=room.status,
    createdAt=room.created_at,
    groupingPublishedAt=result.generated_at if result is not None else None,
    participantCount=len(room.participants),
    questionCount=len(room.questions),
    groupCount=group_count,
    generationMode=generation_mode,
    fullyCoveredGroupQuestions=fully_covered,
    totalGroupQuestions=total,
  )


def participant_room_view(
  room: Room,
  participant_id: UUID,
  *,
  now: datetime,
) -> ParticipantRoomView:
  participant = room.participants.get(participant_id)
  if participant is None:
    raise not_found()
  show_questions = room.status in {
    RoomStatus.ANSWERING,
    RoomStatus.ANALYZING,
    RoomStatus.PUBLISHED,
    RoomStatus.FAILED,
  }
  questions = []
  if show_questions:
    for question in sorted_questions(room):
      response = room.responses.get((participant_id, question.id))
      questions.append(
        ParticipantQuestionView(
          id=question.id,
          position=question.position,
          prompt=question.prompt,
          answer=response.text if response is not None else None,
        )
      )
  answered_count = sum(1 for question in room.questions if (participant_id, question.id) in room.responses)
  return ParticipantRoomView(
    roomId=room.id,
    title=room.title,
    status=room.status,
    activityStarted=room.activity_started,
    durationMinutes=room.duration_minutes,
    startedAt=room.started_at,
    deadlineAt=room.deadline_at,
    serverTime=now,
    remainingSeconds=remaining_seconds(room, now),
    analysisPhase=room.analysis_phase,
    analysisMode=cast(Literal["placeholder", "coverage_aware"], room.analysis_mode),
    participant=ParticipantIdentityView(
      participantId=participant.id,
      displayName=participant.display_name,
      submittedAt=participant.submitted_at,
    ),
    questions=questions,
    answeredQuestionCount=answered_count,
    questionCount=len(room.questions),
    submitted=participant.submitted_at is not None,
    submittedAt=participant.submitted_at,
    allowedActions=participant_actions(room, participant),
  )


def host_status_view(room: Room, *, now: datetime) -> StatusView:
  progress = progress_view(room)
  return StatusView(
    status=room.status,
    activityStarted=room.activity_started,
    startedAt=room.started_at,
    deadlineAt=room.deadline_at,
    serverTime=now,
    remainingSeconds=remaining_seconds(room, now),
    analysisPhase=room.analysis_phase,
    analysisMode=cast(Literal["placeholder", "coverage_aware"], room.analysis_mode),
    allowedActions=host_actions(room),
    startEligibility=start_eligibility_view(room),
    progress=progress,
    participantCount=progress.participantCount,
    submittedParticipantCount=progress.submittedParticipantCount,
    answeredResponseCount=progress.answeredResponseCount,
    submittedResponseCount=progress.submittedResponseCount,
    possibleResponseCount=progress.possibleResponseCount,
  )


def participant_status_view(room: Room, participant_id: UUID, *, now: datetime) -> StatusView:
  participant = room.participants.get(participant_id)
  if participant is None:
    raise not_found()
  answered = sum(1 for question in room.questions if (participant_id, question.id) in room.responses)
  return StatusView(
    status=room.status,
    activityStarted=room.activity_started,
    startedAt=room.started_at,
    deadlineAt=room.deadline_at,
    serverTime=now,
    remainingSeconds=remaining_seconds(room, now),
    analysisPhase=room.analysis_phase,
    analysisMode=cast(Literal["placeholder", "coverage_aware"], room.analysis_mode),
    allowedActions=participant_actions(room, participant),
    submitted=participant.submitted_at is not None,
    submittedAt=participant.submitted_at,
    answeredQuestionCount=answered,
    questionCount=len(room.questions),
  )


def groups_view(room: Room) -> GroupsView:
  result = room.grouping_result
  if room.status != RoomStatus.PUBLISHED or result is None:
    raise conflict("GROUPS_NOT_PUBLISHED", "Groups are not available yet.")
  if isinstance(result, GroupingArtifact):
    coverage_groups = [_coverage_host_group_view(room, group) for group in result.groups]
    fully_covered = sum(question.fullyCovered for group in coverage_groups for question in group.questions)
    return CoverageGroupsView(
      policy=GroupingPolicy(result.policy),
      trigger=result.trigger,
      generatedAt=result.generated_at,
      solver=SolverView(
        status=result.solver_status,
        completeCoverageStatus=result.complete_coverage_status,
        timedOut=result.timed_out,
        solveMilliseconds=result.solve_milliseconds,
        objectives=[
          ObjectiveView(
            name=objective.name,
            value=objective.value,
            provenOptimal=objective.proven_optimal,
          )
          for objective in result.objectives
        ],
      ),
      coverageReport=CoverageReportView(
        fullyCoveredGroupQuestions=fully_covered,
        totalGroupQuestions=len(coverage_groups) * len(room.questions),
      ),
      groups=coverage_groups,
    )
  return PlaceholderGroupsView(
    generationMode="placeholder",
    policy=result.policy,
    trigger=result.trigger,
    generatedAt=result.generated_at,
    groups=[
      GroupView(
        id=group.id,
        members=[member_view(room, participant_id) for participant_id in group.participant_ids],
      )
      for group in result.groups
    ],
  )


def my_group_view(room: Room, participant_id: UUID) -> MyGroupView:
  result = room.grouping_result
  if room.status != RoomStatus.PUBLISHED or result is None:
    raise conflict("GROUPS_NOT_PUBLISHED", "Your group is not available yet.")
  group = next(
    (candidate for candidate in result.groups if participant_id in candidate.participant_ids),
    None,
  )
  if group is None:
    raise not_found()
  if isinstance(result, GroupingArtifact):
    engine_group = cast(EngineGroup, group)
    return CoverageMyGroupView(
      policy=GroupingPolicy(result.policy),
      generatedAt=result.generated_at,
      completeCoverageStatus=result.complete_coverage_status,
      group=_coverage_participant_group_view(room, engine_group),
    )
  return PlaceholderMyGroupView(
    generationMode="placeholder",
    policy=result.policy,
    generatedAt=result.generated_at,
    group=GroupView(
      id=group.id,
      members=[member_view(room, member_id) for member_id in group.participant_ids],
    ),
  )


def _semantic_question(room: Room, question_id: UUID) -> QuestionSemanticArtifact:
  artifact = room.analysis_result
  if artifact is None:
    raise conflict("GROUP_ARTIFACT_INVALID", "The published result is incomplete.")
  semantic_question = next(
    (item for item in artifact.questions if item.question_id == question_id),
    None,
  )
  if semantic_question is None:
    raise conflict("GROUP_ARTIFACT_INVALID", "The published result is incomplete.")
  return semantic_question


def _coverage_question_parts(
  room: Room,
  group: EngineGroup,
  question: Question,
) -> tuple[
  list[CoverageUnitResultView],
  list[RepresentedFamilyView],
  list[ResponseAuditView],
]:
  semantic = _semantic_question(room, question.id)
  assignments = {item.participant_id: item for item in semantic.assignments}
  family_by_id = {family.id: family for family in semantic.families}
  members = tuple(group.participant_ids)
  units: list[CoverageUnitResultView] = []
  for unit in question.coverage_units:
    carriers = [
      member_view(room, member_id) for member_id in members if unit.id in assignments[member_id].covered_unit_ids
    ]
    units.append(
      CoverageUnitResultView(
        id=unit.id,
        text=unit.text,
        covered=bool(carriers),
        carriers=[
          CoverageCarrierView(
            participantId=carrier.participantId,
            displayName=carrier.displayName,
          )
          for carrier in carriers
        ],
      )
    )

  represented: list[RepresentedFamilyView] = []
  for family in semantic.families:
    family_members = [
      member_view(room, member_id) for member_id in members if assignments[member_id].family_id == family.id
    ]
    if family_members:
      represented.append(
        RepresentedFamilyView(
          id=family.id,
          label=family.label,
          members=family_members,
        )
      )

  audit: list[ResponseAuditView] = []
  unit_order = {unit.id: index for index, unit in enumerate(question.coverage_units)}
  for member_id in members:
    assignment = assignments[member_id]
    assigned_family = family_by_id[assignment.family_id] if assignment.family_id is not None else None
    response = room.responses.get((member_id, question.id))
    audit.append(
      ResponseAuditView(
        participant=member_view(room, member_id),
        answer=response.text if response is not None else None,
        coveredUnitIds=sorted(
          assignment.covered_unit_ids,
          key=unit_order.__getitem__,
        ),
        family=(
          ResponseFamilyView(
            id=assigned_family.id,
            label=assigned_family.label,
          )
          if assigned_family is not None
          else None
        ),
      )
    )
  return units, represented, audit


def _coverage_host_group_view(room: Room, group: EngineGroup) -> CoverageGroupView:
  questions: list[GroupQuestionResultView] = []
  for question in sorted_questions(room):
    units, represented, audit = _coverage_question_parts(room, group, question)
    questions.append(
      GroupQuestionResultView(
        questionId=question.id,
        position=question.position,
        prompt=question.prompt,
        fullyCovered=all(unit.covered for unit in units),
        units=units,
        representedFamilies=represented,
        responseAudit=audit,
      )
    )
  return CoverageGroupView(
    id=group.id,
    members=[member_view(room, member_id) for member_id in group.participant_ids],
    questions=questions,
  )


def _coverage_participant_group_view(
  room: Room,
  group: EngineGroup,
) -> ParticipantCoverageGroupView:
  questions: list[AgendaQuestionView] = []
  for question in sorted_questions(room):
    units, represented, _audit = _coverage_question_parts(room, group, question)
    questions.append(
      AgendaQuestionView(
        questionId=question.id,
        position=question.position,
        prompt=question.prompt,
        fullyCovered=all(unit.covered for unit in units),
        units=units,
        representedFamilies=represented,
      )
    )
  return ParticipantCoverageGroupView(
    id=group.id,
    members=[member_view(room, member_id) for member_id in group.participant_ids],
    questions=questions,
  )


def question_view(question: Question) -> QuestionView:
  return QuestionView(
    id=question.id,
    position=question.position,
    prompt=question.prompt,
    referenceMaterial=question.reference_material,
    coverageUnits=[CoverageUnitView(id=unit.id, text=unit.text) for unit in question.coverage_units],
  )


def material_view(attachment: ReferenceAttachment) -> MaterialView:
  return MaterialView(
    id=attachment.id,
    fileName=attachment.file_name,
    mediaType=attachment.content_type,
    sizeBytes=attachment.size_bytes,
    extractedCharacterCount=len(attachment.extracted_text),
    uploadedAt=attachment.uploaded_at,
  )


def progress_view(room: Room) -> ProgressView:
  participant_ids = room.cohort_ids or tuple(room.participants)
  submitted = sum(room.participants[participant_id].submitted_at is not None for participant_id in participant_ids)
  response_count = sum(response.participant_id in participant_ids for response in room.responses.values())
  return ProgressView(
    participantCount=len(participant_ids),
    submittedParticipantCount=submitted,
    answeredResponseCount=response_count,
    submittedResponseCount=response_count,
    possibleResponseCount=len(participant_ids) * len(room.questions),
  )


def host_actions(room: Room) -> list[str]:
  if room.status == RoomStatus.DRAFT:
    return ["editRoom", "editQuestions", "uploadMaterials", "openLobby"]
  if room.status == RoomStatus.LOBBY:
    actions = ["removeParticipant"]
    if not start_eligibility_view(room).eligible:
      return actions
    return ["startActivity", *actions]
  if room.status == RoomStatus.ANSWERING:
    return ["viewProgress", "startAnalysis"]
  if room.status == RoomStatus.ANALYZING:
    return ["viewAnalysisProgress"]
  if room.status == RoomStatus.PUBLISHED:
    return ["viewGroups"]
  if room.status == RoomStatus.FAILED:
    actions = ["viewFailure"]
    if room.analysis_attempt_count < 2:
      actions.append("retryAnalysis")
    return actions
  return []


def start_eligibility_view(room: Room) -> StartEligibilityView:
  if room.status != RoomStatus.LOBBY:
    return StartEligibilityView(
      eligible=False,
      reasonCode="room_not_in_lobby",
      message="The activity can start only while the room is in the lobby.",
    )
  participant_count = len(room.participants)
  if participant_count < room.group_size.minimum:
    return StartEligibilityView(
      eligible=False,
      reasonCode="minimum_participants",
      message=(f"At least {room.group_size.minimum} participants must join before the activity can start."),
    )
  try:
    balanced_capacities(participant_count, room.group_size)
  except DomainError:
    return StartEligibilityView(
      eligible=False,
      reasonCode="group_size_infeasible",
      message=(
        f"{participant_count} participants cannot be divided into groups of "
        f"{room.group_size.minimum}-{room.group_size.maximum}. Wait for another "
        "participant or remove one."
      ),
    )
  return StartEligibilityView(
    eligible=True,
    reasonCode=None,
    message=("Starting freezes the participant list and begins everyone's shared timer."),
  )


def participant_actions(room: Room, participant: Participant) -> list[str]:
  if room.status == RoomStatus.LOBBY:
    return ["waitForStart"]
  if room.status == RoomStatus.ANSWERING:
    return ["waitForAnalysis"] if participant.submitted_at is not None else ["answer", "submit"]
  if room.status == RoomStatus.ANALYZING:
    return ["waitForGroups"]
  if room.status == RoomStatus.PUBLISHED:
    return ["viewMyGroup"]
  return []


def remaining_seconds(room: Room, now: datetime) -> int | None:
  if room.deadline_at is None:
    return None
  return max(0, ceil((room.deadline_at - now).total_seconds()))


def sorted_questions(room: Room) -> list[Question]:
  return sorted(room.questions, key=lambda question: question.position)


def member_view(room: Room, participant_id: UUID) -> GroupMemberView:
  participant = room.participants.get(participant_id)
  if participant is None:
    raise not_found()
  return GroupMemberView(participantId=participant.id, displayName=participant.display_name)
