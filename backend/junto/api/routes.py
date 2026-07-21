from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from junto.access.sessions import (
  browser_session_nonce,
  ensure_session,
  grant_host,
  grant_participant,
  optional_participant_grant,
  participant_grant,
  require_csrf,
  require_host,
  revoke_room_grant,
  room_grants,
)
from junto.api.presenters import (
  activity_summary_view,
  groups_view,
  host_room_view,
  host_status_view,
  material_view,
  my_group_view,
  participant_room_view,
  participant_status_view,
  question_view,
)
from junto.api.schemas import (
  ActivityHistoryView,
  AnalysisAccepted,
  AnswerReceipt,
  AnswerWrite,
  AuthoringSuggestionRequest,
  AuthoringSuggestionResponse,
  GroupSizeDto,
  GroupsView,
  HostRoomView,
  JoinLookupView,
  JoinRequest,
  JoinResponse,
  MaterialUploadResponse,
  MyGroupView,
  ParticipantRoomView,
  PublishedActivityView,
  QuestionCreate,
  QuestionPatch,
  QuestionView,
  RoomCreate,
  RoomCreated,
  RoomDelete,
  RoomPatch,
  SessionView,
  StatusView,
  SubmissionView,
  SyntheticClassroomView,
  SyntheticCohortWrite,
  SyntheticGenerationView,
  SyntheticResponsesResultView,
  SyntheticResponsesWrite,
)
from junto.domain.entities import GroupSize
from junto.domain.errors import DomainError, invalid, not_found
from junto.engine.provider import (
  ProviderInvalidOutput,
  ProviderPermanentError,
  ProviderRefusalError,
  ProviderTransientError,
)
from junto.services.authoring import AuthoringQuestion, AuthoringRequest, AuthoringService
from junto.services.references import ReferenceTextExtractor
from junto.services.rooms import RoomService
from junto.services.simulation import SyntheticClassroomProjection, SyntheticClassroomService


def build_router(
  service: RoomService,
  *,
  authoring_service: AuthoringService | None = None,
  reference_extractor: ReferenceTextExtractor,
  synthetic_classroom: SyntheticClassroomService,
) -> APIRouter:
  router = APIRouter(prefix="/api")

  @router.get("/health")
  def health() -> dict[str, str]:
    return {"status": "ok"}

  @router.get("/ready", response_model=None)
  def ready() -> dict[str, str] | JSONResponse:
    if service.repository_ready():
      return {"status": "ready"}
    return JSONResponse(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      content={"status": "unavailable"},
    )

  @router.get("/session", response_model=SessionView)
  def session(request: Request) -> SessionView:
    csrf, _ = ensure_session(request)
    hosts, participants = room_grants(request)
    return SessionView(
      csrfToken=csrf,
      hostRoomIds=hosts,
      participantRoomIds=participants,
    )

  @router.get("/activities", response_model=ActivityHistoryView)
  def activity_history(request: Request) -> ActivityHistoryView:
    host_room_ids, _ = room_grants(request)
    rooms = []
    for room_id in host_room_ids:
      try:
        rooms.append(service.get_room(room_id))
      except DomainError as error:
        if error.status_code != 404:
          raise
    rooms.sort(key=lambda room: (room.created_at, str(room.id)), reverse=True)
    return ActivityHistoryView(activities=[activity_summary_view(room) for room in rooms])

  @router.get("/activities/{room_id}", response_model=PublishedActivityView)
  def published_activity(room_id: UUID) -> PublishedActivityView:
    room = service.get_room(room_id)
    if room.status.value != "published":
      raise not_found("This activity result is unavailable.")
    return PublishedActivityView(
      roomId=room.id,
      title=room.title,
      createdAt=room.created_at,
      participantCount=len(room.participants),
      result=groups_view(room),
    )

  @router.post(
    "/authoring/suggestions",
    response_model=AuthoringSuggestionResponse,
    dependencies=[Depends(require_csrf)],
  )
  async def suggest_authoring(
    payload: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
  ) -> AuthoringSuggestionResponse:
    if authoring_service is None:
      raise DomainError(
        "AUTHORING_ASSIST_UNAVAILABLE",
        "AI drafting is not available right now. You can keep editing manually.",
        503,
      )
    try:
      draft = AuthoringSuggestionRequest.model_validate_json(payload)
    except ValidationError as error:
      raise invalid(
        "AUTHORING_DRAFT_INVALID",
        "The activity draft could not be read. Refresh the page and try again.",
        {"fields": _safe_validation_errors(error)},
      ) from None

    if file is not None and draft.referenceText:
      await file.close()
      raise invalid(
        "AUTHORING_REFERENCE_AMBIGUOUS",
        "Use either an uploaded file or pasted reference text, not both.",
      )
    if file is not None:
      if not file.filename:
        await file.close()
        raise invalid("REFERENCE_FILE_NAME_INVALID", "A reference file name is required.")
      file_name = _safe_reference_file_name(file.filename)
      content = await read_bounded_upload(
        file,
        maximum=service.settings.max_reference_file_bytes,
      )
      if not content:
        raise invalid("REFERENCE_FILE_EMPTY", "The uploaded reference file is empty.")
      _, reference_text = reference_extractor.extract(
        file_name=file_name,
        content=content,
      )
    else:
      reference_text = (draft.referenceText or "").strip()
      if not reference_text:
        raise invalid(
          "AUTHORING_REFERENCE_REQUIRED",
          "Add reference material before requesting a suggestion.",
        )

    request = AuthoringRequest(
      activity_title=draft.activityTitle,
      target=draft.target,
      target_question_index=draft.targetQuestionIndex,
      questions=tuple(
        AuthoringQuestion(
          prompt=question.prompt,
          coverage_units=tuple(question.coverageUnits),
        )
        for question in draft.questions
      ),
      reference_text=reference_text,
    )
    try:
      suggestion = await authoring_service.suggest(request)
    except ProviderRefusalError:
      raise invalid(
        "AUTHORING_SUGGESTION_DECLINED",
        "Junto could not draft from this material. Revise the reference or keep editing manually.",
      ) from None
    except ProviderTransientError:
      raise DomainError(
        "AUTHORING_ASSIST_TEMPORARILY_UNAVAILABLE",
        "Junto could not finish the suggestion. Try again in a moment.",
        503,
      ) from None
    except (ProviderInvalidOutput, ProviderPermanentError):
      raise DomainError(
        "AUTHORING_ASSIST_FAILED",
        "Junto could not produce a usable suggestion. Your draft was not changed.",
        502,
      ) from None
    return AuthoringSuggestionResponse(
      questionPrompt=suggestion.question_prompt,
      coverageUnits=list(suggestion.coverage_units),
    )

  @router.post(
    "/rooms",
    response_model=RoomCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
  )
  def create_room(payload: RoomCreate, request: Request) -> RoomCreated:
    room = service.create_room(
      title=payload.title,
      policy=payload.policy,
      group_size=to_group_size(payload.groupSize),
      duration_minutes=payload.durationMinutes,
    )
    grant_host(
      request,
      room.id,
      maximum=service.settings.max_session_room_grants,
    )
    return RoomCreated(roomId=room.id, joinCode=room.join_code, status=room.status)

  @router.get("/rooms/{room_id}", response_model=HostRoomView)
  def get_host_room(room_id: UUID, request: Request) -> HostRoomView:
    require_host(request, room_id)
    return host_room_view(service.get_room(room_id), now=service.current_time())

  @router.get(
    "/development/rooms/{room_id}/synthetic-classroom",
    response_model=SyntheticClassroomView,
  )
  def get_synthetic_classroom(room_id: UUID, request: Request) -> SyntheticClassroomView:
    require_host(request, room_id)
    return _synthetic_classroom_view(synthetic_classroom.projection(room_id))

  @router.put(
    "/development/rooms/{room_id}/synthetic-cohort",
    response_model=SyntheticClassroomView,
    dependencies=[Depends(require_csrf)],
  )
  def configure_synthetic_cohort(
    room_id: UUID,
    payload: SyntheticCohortWrite,
    request: Request,
  ) -> SyntheticClassroomView:
    require_host(request, room_id)
    projection = synthetic_classroom.configure(
      room_id,
      target_size=payload.targetSize,
      seed=payload.seed,
    )
    return _synthetic_classroom_view(projection)

  @router.post(
    "/development/rooms/{room_id}/synthetic-responses",
    response_model=SyntheticResponsesResultView,
    dependencies=[Depends(require_csrf)],
  )
  async def generate_synthetic_responses(
    room_id: UUID,
    payload: SyntheticResponsesWrite,
    request: Request,
  ) -> SyntheticResponsesResultView:
    require_host(request, room_id)
    result = await synthetic_classroom.generate_and_submit(
      room_id,
      source=payload.source,
    )
    return SyntheticResponsesResultView(
      simulation=_synthetic_classroom_view(synthetic_classroom.projection(room_id)),
      source=result.source,
      participantCount=result.participant_count,
      responseCount=result.response_count,
      models=list(result.models),
    )

  @router.patch(
    "/rooms/{room_id}",
    response_model=HostRoomView,
    dependencies=[Depends(require_csrf)],
  )
  def patch_room(room_id: UUID, payload: RoomPatch, request: Request) -> HostRoomView:
    require_host(request, room_id)
    room = service.update_room(
      room_id,
      title=payload.title if "title" in payload.model_fields_set else None,
      policy=payload.policy if "policy" in payload.model_fields_set else None,
      group_size=(
        to_group_size(payload.groupSize)
        if "groupSize" in payload.model_fields_set and payload.groupSize is not None
        else None
      ),
      duration_minutes=(payload.durationMinutes if "durationMinutes" in payload.model_fields_set else None),
    )
    return host_room_view(room, now=service.current_time())

  @router.delete(
    "/rooms/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
  )
  def delete_room(room_id: UUID, payload: RoomDelete, request: Request) -> Response:
    require_host(request, room_id)
    service.delete_room(room_id, confirmation_code=payload.confirmationCode)
    revoke_room_grant(request, room_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

  @router.post(
    "/rooms/{room_id}/questions",
    response_model=QuestionView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
  )
  def create_question(
    room_id: UUID,
    payload: QuestionCreate,
    request: Request,
  ) -> QuestionView:
    require_host(request, room_id)
    question = service.add_question(
      room_id,
      prompt=payload.prompt,
      position=payload.position,
      reference_material=payload.referenceMaterial,
      coverage_units=[(unit.id, unit.text) for unit in payload.coverageUnits],
    )
    return question_view(question)

  @router.patch(
    "/rooms/{room_id}/questions/{question_id}",
    response_model=QuestionView,
    dependencies=[Depends(require_csrf)],
  )
  def patch_question(
    room_id: UUID,
    question_id: UUID,
    payload: QuestionPatch,
    request: Request,
  ) -> QuestionView:
    require_host(request, room_id)
    question = service.update_question(
      room_id,
      question_id,
      prompt=payload.prompt,
      prompt_set="prompt" in payload.model_fields_set,
      position=payload.position,
      position_set="position" in payload.model_fields_set,
      reference_material=payload.referenceMaterial,
      reference_material_set="referenceMaterial" in payload.model_fields_set,
      coverage_units=(
        [(unit.id, unit.text) for unit in payload.coverageUnits] if payload.coverageUnits is not None else None
      ),
      coverage_units_set="coverageUnits" in payload.model_fields_set,
    )
    return question_view(question)

  @router.delete(
    "/rooms/{room_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
  )
  def delete_question(room_id: UUID, question_id: UUID, request: Request) -> Response:
    require_host(request, room_id)
    service.delete_question(room_id, question_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

  @router.post(
    "/rooms/{room_id}/materials",
    response_model=MaterialUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
  )
  async def upload_material(
    room_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File()],
  ) -> MaterialUploadResponse:
    require_host(request, room_id)
    if not file.filename:
      raise invalid("REFERENCE_FILE_NAME_INVALID", "A reference file name is required.")
    content = await read_bounded_upload(
      file,
      maximum=service.settings.max_reference_file_bytes,
    )
    attachment = service.add_reference_attachment(
      room_id,
      file_name=file.filename,
      content=content,
    )
    return MaterialUploadResponse(material=material_view(attachment))

  @router.delete(
    "/rooms/{room_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
  )
  def delete_material(room_id: UUID, material_id: UUID, request: Request) -> Response:
    require_host(request, room_id)
    service.delete_reference_attachment(room_id, material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

  @router.post(
    "/rooms/{room_id}/open",
    response_model=HostRoomView,
    dependencies=[Depends(require_csrf)],
  )
  def open_lobby(room_id: UUID, request: Request) -> HostRoomView:
    require_host(request, room_id)
    return host_room_view(service.open_lobby(room_id), now=service.current_time())

  @router.post(
    "/rooms/{room_id}/start",
    response_model=HostRoomView,
    dependencies=[Depends(require_csrf)],
  )
  def start_activity(room_id: UUID, request: Request) -> HostRoomView:
    require_host(request, room_id)
    return host_room_view(service.start_activity(room_id), now=service.current_time())

  @router.get("/join/{join_code}", response_model=JoinLookupView)
  def lookup_join(join_code: str) -> JoinLookupView:
    room = service.get_public_room(join_code)
    return JoinLookupView(
      title=room.title,
      status=room.status,
      durationMinutes=room.duration_minutes,
      questionCount=len(room.questions),
      analysisMode=cast(
        Literal["placeholder", "coverage_aware"],
        room.analysis_mode,
      ),
    )

  @router.post(
    "/join/{join_code}",
    response_model=JoinResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
  )
  def join(join_code: str, payload: JoinRequest, request: Request) -> JoinResponse:
    room = service.get_public_room(join_code)
    existing = optional_participant_grant(request, room.id)
    joined_room, participant = service.join_room(
      join_code,
      display_name=payload.displayName,
      existing_participant_id=existing,
      session_nonce=browser_session_nonce(request),
    )
    grant_participant(
      request,
      joined_room.id,
      participant.id,
      maximum=service.settings.max_session_room_grants,
    )
    return JoinResponse(
      roomId=joined_room.id,
      participantId=participant.id,
      displayName=participant.display_name,
    )

  @router.get("/rooms/{room_id}/participant", response_model=ParticipantRoomView)
  def get_participant_room(room_id: UUID, request: Request) -> ParticipantRoomView:
    participant_id = participant_grant(request, room_id)
    return participant_room_view(
      service.get_room(room_id),
      participant_id,
      now=service.current_time(),
    )

  @router.put(
    "/rooms/{room_id}/responses/{question_id}",
    response_model=AnswerReceipt,
    dependencies=[Depends(require_csrf)],
  )
  def save_answer(
    room_id: UUID,
    question_id: UUID,
    payload: AnswerWrite,
    request: Request,
  ) -> AnswerReceipt:
    participant_id = participant_grant(request, room_id)
    receipt = service.save_answer(room_id, participant_id, question_id, text=payload.text)
    return AnswerReceipt(
      questionId=receipt.question_id,
      text=receipt.text,
      savedAt=receipt.saved_at,
      answeredQuestionCount=receipt.answered_question_count,
    )

  @router.post(
    "/rooms/{room_id}/submit",
    response_model=SubmissionView,
    dependencies=[Depends(require_csrf)],
  )
  def submit(room_id: UUID, request: Request) -> SubmissionView:
    participant_id = participant_grant(request, room_id)
    participant, analysis_started = service.submit(room_id, participant_id)
    room = service.get_room(room_id)
    if participant.submitted_at is None:
      raise not_found()
    return SubmissionView(
      submitted=True,
      submittedAt=participant.submitted_at,
      status=room.status,
      answeredQuestionCount=sum(1 for question in room.questions if (participant_id, question.id) in room.responses),
      questionCount=len(room.questions),
      analysisStarted=analysis_started,
    )

  @router.delete(
    "/rooms/{room_id}/participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
  )
  def remove_participant(
    room_id: UUID,
    participant_id: UUID,
    request: Request,
  ) -> Response:
    require_host(request, room_id)
    service.remove_participant(room_id, participant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

  @router.get(
    "/rooms/{room_id}/status",
    response_model=StatusView,
    response_model_exclude_none=True,
  )
  def room_status(room_id: UUID, request: Request) -> StatusView:
    room = service.get_room(room_id)
    try:
      require_host(request, room_id)
      return host_status_view(room, now=service.current_time())
    except DomainError as host_error:
      participant_id = optional_participant_grant(request, room_id)
      if participant_id is None:
        raise host_error
      return participant_status_view(room, participant_id, now=service.current_time())

  @router.post(
    "/rooms/{room_id}/analysis",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf)],
  )
  def analyze(room_id: UUID, request: Request) -> AnalysisAccepted:
    require_host(request, room_id)
    synthetic_classroom.require_analysis_ready(room_id)
    room = service.start_analysis(room_id)
    return AnalysisAccepted(status=room.status, analysisPhase=room.analysis_phase)

  @router.post(
    "/rooms/{room_id}/analysis/retry",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf)],
  )
  def retry_analysis(room_id: UUID, request: Request) -> AnalysisAccepted:
    require_host(request, room_id)
    room = service.retry_analysis(room_id)
    return AnalysisAccepted(status=room.status, analysisPhase=room.analysis_phase)

  @router.get("/rooms/{room_id}/groups", response_model=GroupsView)
  def get_groups(room_id: UUID, request: Request) -> GroupsView:
    require_host(request, room_id)
    return groups_view(service.get_room(room_id))

  @router.get("/rooms/{room_id}/my-group", response_model=MyGroupView)
  def get_my_group(room_id: UUID, request: Request) -> MyGroupView:
    participant_id = participant_grant(request, room_id)
    return my_group_view(service.get_room(room_id), participant_id)

  return router


def to_group_size(value: GroupSizeDto) -> GroupSize:
  return GroupSize(
    minimum=value.minimum,
    preferred=value.preferred,
    maximum=value.maximum,
  )


def _synthetic_classroom_view(
  projection: SyntheticClassroomProjection,
) -> SyntheticClassroomView:
  generation = projection.generation
  return SyntheticClassroomView(
    enabled=projection.enabled,
    stage=projection.stage,
    syntheticParticipantCount=projection.synthetic_participant_count,
    pendingSyntheticParticipantCount=projection.pending_synthetic_participant_count,
    targetSizes=list(projection.target_sizes),
    canConfigure=projection.can_configure,
    canGenerate=projection.can_generate,
    patternedAvailable=projection.patterned_available,
    openRouterAvailable=projection.openrouter_available,
    syntheticParticipantIds=list(projection.synthetic_participant_ids),
    pendingSyntheticParticipantIds=list(projection.pending_synthetic_participant_ids),
    generation=(
      SyntheticGenerationView(
        status=generation.status,
        source=generation.source,
        requestedParticipantCount=generation.requested_participant_count,
        completedParticipantCount=generation.completed_participant_count,
        failedParticipantCount=generation.failed_participant_count,
        startedAt=generation.started_at,
        finishedAt=generation.finished_at,
        error=generation.error,
      )
      if generation is not None
      else None
    ),
  )


def _safe_reference_file_name(file_name: str) -> str:
  normalized = file_name.replace("\\", "/")
  safe_name = PurePath(normalized).name.strip()
  if not safe_name or len(safe_name) > 160 or any(ord(character) < 32 for character in safe_name):
    raise invalid("REFERENCE_FILE_NAME_INVALID", "The reference file name is invalid.")
  return safe_name


def _safe_validation_errors(error: ValidationError) -> list[dict[str, object]]:
  return [
    {
      "location": [str(part) for part in item.get("loc", ())],
      "type": str(item.get("type", "validation_error")),
    }
    for item in error.errors(include_input=False, include_url=False)[:20]
  ]


async def read_bounded_upload(file: UploadFile, *, maximum: int) -> bytes:
  chunks: list[bytes] = []
  size = 0
  try:
    while True:
      chunk = await file.read(min(64 * 1024, maximum + 1 - size))
      if not chunk:
        break
      size += len(chunk)
      if size > maximum:
        raise invalid(
          "REFERENCE_FILE_TOO_LARGE",
          f"Reference files must be at most {maximum} bytes.",
        )
      chunks.append(chunk)
  finally:
    await file.close()
  return b"".join(chunks)
