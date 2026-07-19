import type {
  ActivityTiming,
  AnalysisPhase,
  EntityId,
  GroupingPolicy,
  GroupSize,
  IsoDateTime,
  RoomAction,
  RoomStatus,
} from "./common";

export interface SessionDto {
  csrfToken: string;
  hostRoomIds: EntityId[];
  participantRoomIds: EntityId[];
}

export interface CoverageUnit {
  id: EntityId;
  text: string;
}

export interface CoverageUnitInput {
  id?: EntityId;
  text: string;
}

export interface HostQuestion {
  id: EntityId;
  position: number;
  prompt: string;
  referenceMaterial: string | null;
  coverageUnits: CoverageUnit[];
}

export interface ReferenceAttachment {
  id: EntityId;
  fileName: string;
  mediaType: string;
  sizeBytes: number;
  extractedCharacterCount: number;
  uploadedAt: IsoDateTime;
}

export interface QuestionMutation {
  position: number;
  prompt: string;
  referenceMaterial?: string | null;
  coverageUnits: CoverageUnitInput[];
}

export interface ParticipantQuestion {
  id: EntityId;
  position: number;
  prompt: string;
  answer: string | null;
}

export interface RoomProgress {
  participantCount: number;
  submittedParticipantCount: number;
  answeredResponseCount: number;
  submittedResponseCount: number;
  possibleResponseCount: number;
}

export interface ParticipantSummary {
  participantId: EntityId;
  displayName: string;
  submittedAt: IsoDateTime | null;
}

export interface HostRoom extends ActivityTiming {
  id: EntityId;
  joinCode: string;
  title: string;
  policy: GroupingPolicy;
  groupSize: GroupSize;
  status: RoomStatus;
  questions: HostQuestion[];
  materials: ReferenceAttachment[];
  progress: RoomProgress;
  allowedActions: RoomAction[];
  lastError: string | null;
  participants: ParticipantSummary[];
  analysisPhase: AnalysisPhase;
}

export interface CreateRoomRequest {
  title: string;
  policy: GroupingPolicy;
  groupSize: GroupSize;
  durationMinutes: number;
}

export interface CreateRoomResponse {
  roomId: EntityId;
  joinCode: string;
  status: RoomStatus;
}

export interface UpdateRoomRequest {
  title?: string;
  policy?: GroupingPolicy;
  groupSize?: GroupSize;
  durationMinutes?: number;
}

export type OpenRoomResponse = HostRoom;

export type StartActivityResponse = HostRoom;

export interface PublicJoinRoom {
  title: string;
  status: "lobby";
  durationMinutes: number;
  questionCount: number;
}

export interface JoinRoomRequest {
  displayName: string;
}

export interface JoinRoomResponse {
  roomId: EntityId;
  participantId: EntityId;
  displayName: string;
}

export interface ParticipantRoom extends ActivityTiming {
  roomId: EntityId;
  title: string;
  status: RoomStatus;
  participant: {
    participantId: EntityId;
    displayName: string;
    submittedAt: IsoDateTime | null;
  };
  questions: ParticipantQuestion[];
  answeredQuestionCount: number;
  questionCount: number;
  allowedActions: RoomAction[];
  submittedAt: IsoDateTime | null;
  submitted: boolean;
  analysisPhase: AnalysisPhase;
}

export interface SaveAnswerRequest {
  text: string;
}

/** Older servers return 204; the prototype may return this receipt. */
export interface SaveAnswerReceipt {
  questionId: EntityId;
  text: string;
  savedAt: IsoDateTime;
  answeredQuestionCount: number;
}

export interface SubmitResponsesResponse extends ActivityTiming {
  status: RoomStatus;
  submittedAt: IsoDateTime;
  answeredQuestionCount: number;
  questionCount: number;
  analysisStarted: boolean;
}

export interface RoomStatusProjection extends ActivityTiming {
  status: RoomStatus;
  allowedActions: RoomAction[];
  participantCount?: number;
  submittedResponseCount?: number;
  answeredResponseCount?: number;
  possibleResponseCount?: number;
  submittedParticipantCount?: number;
  answeredQuestionCount?: number;
  questionCount?: number;
  submittedAt?: IsoDateTime | null;
  submitted?: boolean;
  analysisPhase: AnalysisPhase;
}

export interface StartAnalysisResponse {
  status: "analyzing";
  analysisPhase: AnalysisPhase;
}

export interface ReferenceMaterialUploadResponse {
  material: ReferenceAttachment;
}
