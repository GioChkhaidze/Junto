from __future__ import annotations

from datetime import datetime
from math import ceil
from uuid import UUID

from junto.api.schemas import (
    CoverageUnitView,
    GroupMemberView,
    GroupSizeDto,
    GroupsView,
    GroupView,
    HostParticipantView,
    HostRoomView,
    MaterialView,
    MyGroupView,
    ParticipantIdentityView,
    ParticipantQuestionView,
    ParticipantRoomView,
    ProgressView,
    QuestionView,
    StatusView,
)
from junto.domain.entities import Participant, Question, ReferenceAttachment, Room, RoomStatus
from junto.domain.errors import DomainError, conflict, not_found
from junto.domain.grouping import balanced_capacities


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
        allowedActions=host_actions(room),
        lastError=room.last_error,
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
    answered_count = sum(
        1 for question in room.questions if (participant_id, question.id) in room.responses
    )
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
        allowedActions=host_actions(room),
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
    answered = sum(
        1 for question in room.questions if (participant_id, question.id) in room.responses
    )
    return StatusView(
        status=room.status,
        activityStarted=room.activity_started,
        startedAt=room.started_at,
        deadlineAt=room.deadline_at,
        serverTime=now,
        remainingSeconds=remaining_seconds(room, now),
        analysisPhase=room.analysis_phase,
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
    return GroupsView(
        generationMode=result.generation_mode,
        policy=result.policy,
        trigger=result.trigger,
        generatedAt=result.generated_at,
        groups=[
            GroupView(
                id=group.id,
                members=[
                    member_view(room, participant_id) for participant_id in group.participant_ids
                ],
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
    return MyGroupView(
        generationMode=result.generation_mode,
        policy=result.policy,
        generatedAt=result.generated_at,
        group=GroupView(
            id=group.id,
            members=[member_view(room, member_id) for member_id in group.participant_ids],
        ),
    )


def question_view(question: Question) -> QuestionView:
    return QuestionView(
        id=question.id,
        position=question.position,
        prompt=question.prompt,
        referenceMaterial=question.reference_material,
        coverageUnits=[
            CoverageUnitView(id=unit.id, text=unit.text) for unit in question.coverage_units
        ],
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
    submitted = sum(
        room.participants[participant_id].submitted_at is not None
        for participant_id in participant_ids
    )
    response_count = sum(
        response.participant_id in participant_ids for response in room.responses.values()
    )
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
        try:
            balanced_capacities(len(room.participants), room.group_size)
        except DomainError:
            return actions
        return ["startActivity", *actions]
    if room.status == RoomStatus.ANSWERING:
        return ["viewProgress", "startAnalysis"]
    if room.status == RoomStatus.ANALYZING:
        return ["viewAnalysisProgress"]
    if room.status == RoomStatus.PUBLISHED:
        return ["viewGroups"]
    if room.status == RoomStatus.FAILED:
        return ["viewFailure"]
    return []


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
