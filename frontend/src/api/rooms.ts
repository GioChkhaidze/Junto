import type {
  ActivityHistory,
  AuthoringSuggestionRequest,
  AuthoringSuggestionResponse,
  ConfigureSyntheticCohortRequest,
  CreateRoomRequest,
  CreateRoomResponse,
  EntityId,
  GenerateSyntheticResponsesRequest,
  GenerateSyntheticResponsesResponse,
  HostGroupsResponse,
  HostQuestion,
  HostRoom,
  JoinRoomRequest,
  JoinRoomResponse,
  MyGroupResponse,
  ParticipantRoom,
  PublicJoinRoom,
  QuestionMutation,
  ReferenceMaterialUploadResponse,
  RoomStatusProjection,
  SaveAnswerReceipt,
  SaveAnswerRequest,
  StartAnalysisResponse,
  SubmitResponsesResponse,
  SyntheticClassroomProjection,
  UpdateRoomRequest,
} from "../domain";
import { apiRequest, invalidateSession, pathSegment } from "./http";

function roomPath(roomId: EntityId): string {
  return `/api/rooms/${pathSegment(roomId)}`;
}

function developmentRoomPath(roomId: EntityId): string {
  return `/api/development/rooms/${pathSegment(roomId)}`;
}

export function suggestAuthoring(input: AuthoringSuggestionRequest, file?: File): Promise<AuthoringSuggestionResponse> {
  const formData = new FormData();
  formData.set("payload", JSON.stringify(input));
  if (file) formData.set("file", file);
  return apiRequest<AuthoringSuggestionResponse>("/api/authoring/suggestions", { method: "POST", formData });
}

export function getActivities(signal?: AbortSignal): Promise<ActivityHistory> {
  return apiRequest<ActivityHistory>("/api/activities", { signal });
}

export async function deleteRoom(roomId: EntityId, confirmationCode: string): Promise<void> {
  await apiRequest<void>(roomPath(roomId), { method: "DELETE", body: { confirmationCode } });
  invalidateSession();
}

export async function createRoom(input: CreateRoomRequest): Promise<CreateRoomResponse> {
  const result = await apiRequest<CreateRoomResponse>("/api/rooms", { method: "POST", body: input });
  invalidateSession();
  return result;
}

export function getRoom(roomId: EntityId, signal?: AbortSignal): Promise<HostRoom> {
  return apiRequest<HostRoom>(roomPath(roomId), { signal });
}

export function updateRoom(roomId: EntityId, input: UpdateRoomRequest): Promise<HostRoom> {
  return apiRequest<HostRoom>(roomPath(roomId), { method: "PATCH", body: input });
}

export function createQuestion(roomId: EntityId, input: QuestionMutation): Promise<HostQuestion> {
  return apiRequest<HostQuestion>(`${roomPath(roomId)}/questions`, { method: "POST", body: input });
}

export function updateQuestion(roomId: EntityId, questionId: EntityId, input: QuestionMutation): Promise<HostQuestion> {
  return apiRequest<HostQuestion>(`${roomPath(roomId)}/questions/${pathSegment(questionId)}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteQuestion(roomId: EntityId, questionId: EntityId): Promise<void> {
  return apiRequest<void>(`${roomPath(roomId)}/questions/${pathSegment(questionId)}`, { method: "DELETE" });
}

export function uploadReferenceMaterial(roomId: EntityId, file: File): Promise<ReferenceMaterialUploadResponse> {
  const formData = new FormData();
  formData.set("file", file);
  return apiRequest<ReferenceMaterialUploadResponse>(`${roomPath(roomId)}/materials`, { method: "POST", formData });
}

export function deleteReferenceMaterial(roomId: EntityId, materialId: EntityId): Promise<void> {
  return apiRequest<void>(`${roomPath(roomId)}/materials/${pathSegment(materialId)}`, { method: "DELETE" });
}

export function openRoom(roomId: EntityId): Promise<HostRoom> {
  return apiRequest<HostRoom>(`${roomPath(roomId)}/open`, { method: "POST" });
}

export function startActivity(roomId: EntityId): Promise<HostRoom> {
  return apiRequest<HostRoom>(`${roomPath(roomId)}/start`, { method: "POST" });
}

export function lookupJoinCode(joinCode: string, signal?: AbortSignal): Promise<PublicJoinRoom> {
  return apiRequest<PublicJoinRoom>(`/api/join/${pathSegment(joinCode)}`, { signal });
}

export async function joinRoom(joinCode: string, input: JoinRoomRequest): Promise<JoinRoomResponse> {
  const result = await apiRequest<JoinRoomResponse>(`/api/join/${pathSegment(joinCode)}`, {
    method: "POST",
    body: input,
  });
  invalidateSession();
  return result;
}

export function getParticipantRoom(roomId: EntityId, signal?: AbortSignal): Promise<ParticipantRoom> {
  return apiRequest<ParticipantRoom>(`${roomPath(roomId)}/participant`, { signal });
}

export function saveAnswer(
  roomId: EntityId,
  questionId: EntityId,
  input: SaveAnswerRequest,
): Promise<SaveAnswerReceipt> {
  return apiRequest<SaveAnswerReceipt>(`${roomPath(roomId)}/responses/${pathSegment(questionId)}`, {
    method: "PUT",
    body: input,
  });
}

/** Idempotently marks this participant's answer set as final. */
export function submitResponses(roomId: EntityId): Promise<SubmitResponsesResponse> {
  return apiRequest<SubmitResponsesResponse>(`${roomPath(roomId)}/submit`, { method: "POST" });
}

export function removeParticipant(roomId: EntityId, participantId: EntityId): Promise<void> {
  return apiRequest<void>(`${roomPath(roomId)}/participants/${pathSegment(participantId)}`, { method: "DELETE" });
}

export function getRoomStatus(roomId: EntityId, signal?: AbortSignal): Promise<RoomStatusProjection> {
  return apiRequest<RoomStatusProjection>(`${roomPath(roomId)}/status`, { signal });
}

export function startAnalysis(roomId: EntityId): Promise<StartAnalysisResponse> {
  return apiRequest<StartAnalysisResponse>(`${roomPath(roomId)}/analysis`, { method: "POST" });
}

export function retryAnalysis(roomId: EntityId): Promise<StartAnalysisResponse> {
  return apiRequest<StartAnalysisResponse>(`${roomPath(roomId)}/analysis/retry`, { method: "POST" });
}

export function getSyntheticClassroom(roomId: EntityId, signal?: AbortSignal): Promise<SyntheticClassroomProjection> {
  return apiRequest<SyntheticClassroomProjection>(`${developmentRoomPath(roomId)}/synthetic-classroom`, { signal });
}

export function configureSyntheticCohort(
  roomId: EntityId,
  input: ConfigureSyntheticCohortRequest,
): Promise<SyntheticClassroomProjection> {
  return apiRequest<SyntheticClassroomProjection>(`${developmentRoomPath(roomId)}/synthetic-cohort`, {
    method: "PUT",
    body: input,
  });
}

export function generateSyntheticResponses(
  roomId: EntityId,
  input: GenerateSyntheticResponsesRequest,
): Promise<GenerateSyntheticResponsesResponse> {
  return apiRequest<GenerateSyntheticResponsesResponse>(`${developmentRoomPath(roomId)}/synthetic-responses`, {
    method: "POST",
    body: input,
    signal: AbortSignal.timeout(125_000),
  });
}

export function getGroups(roomId: EntityId, signal?: AbortSignal): Promise<HostGroupsResponse> {
  return apiRequest<HostGroupsResponse>(`${roomPath(roomId)}/groups`, { signal });
}

export function getMyGroup(roomId: EntityId, signal?: AbortSignal): Promise<MyGroupResponse> {
  return apiRequest<MyGroupResponse>(`${roomPath(roomId)}/my-group`, { signal });
}
