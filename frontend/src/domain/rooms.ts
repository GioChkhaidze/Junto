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

export interface GeneratedCoverageUnit {
  text: string;
}

export interface HostQuestion {
  id: EntityId;
  position: number;
  prompt: string;
  referenceMaterial: string | null;
  coverageUnits: CoverageUnit[];
  expectedTimeMinutes?: number | null;
}

export interface QuestionMutation {
  position: number;
  prompt: string;
  referenceMaterial: string | null;
  coverageUnits: CoverageUnitInput[];
  expectedTimeMinutes?: number | null;
}

export interface ParticipantQuestion {
  id: EntityId;
  position: number;
  prompt: string;
  answer: string | null;
  expectedTimeMinutes?: number | null;
}

export interface RoomProgress {
  participantCount: number;
  submittedResponseCount: number;
  possibleResponseCount: number;
  submittedParticipantCount?: number;
}

export interface ParticipantSummary {
  participantId: EntityId;
  displayName: string;
  submittedAt?: IsoDateTime | null;
}

export interface HostRoom extends ActivityTiming {
  id: EntityId;
  joinCode: string;
  title: string;
  policy: GroupingPolicy;
  groupSize: GroupSize;
  status: RoomStatus;
  questions: HostQuestion[];
  progress: RoomProgress;
  allowedActions: RoomAction[];
  lastError: string | null;
  participants?: ParticipantSummary[];
  analysisPhase?: AnalysisPhase | null;
  generationMode?: "placeholder";
}

export interface CreateRoomRequest {
  title: string;
  policy: GroupingPolicy;
  groupSize: GroupSize;
  durationSeconds?: number;
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
  durationSeconds?: number;
}

export interface CoverageGenerationResponse {
  coverageUnits: GeneratedCoverageUnit[];
}

export interface OpenRoomResponse extends ActivityTiming {
  roomId?: EntityId;
  joinCode?: string;
  status: RoomStatus;
}

export interface StartActivityResponse extends ActivityTiming {
  status: RoomStatus;
}

export interface PublicJoinRoom {
  title: string;
  status: RoomStatus;
  durationSeconds?: number;
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
  questions: ParticipantQuestion[];
  allowedActions: RoomAction[];
  submittedAt?: IsoDateTime | null;
  submitted?: boolean;
  analysisPhase?: AnalysisPhase | null;
  generationMode?: "placeholder";
}

export interface SaveAnswerRequest {
  text: string;
}

/** Older servers return 204; the prototype may return this receipt. */
export interface SaveAnswerReceipt {
  questionId: EntityId;
  text: string;
  savedAt: IsoDateTime;
}

export interface SubmitResponsesResponse extends ActivityTiming {
  status: RoomStatus;
  submittedAt?: IsoDateTime;
}

export interface RoomStatusProjection extends ActivityTiming {
  status: RoomStatus;
  allowedActions: RoomAction[];
  participantCount?: number;
  submittedResponseCount?: number;
  possibleResponseCount?: number;
  submittedParticipantCount?: number;
  answeredQuestionCount?: number;
  questionCount?: number;
  submittedAt?: IsoDateTime | null;
  submitted?: boolean;
  analysisPhase?: AnalysisPhase | null;
  generationMode?: "placeholder";
}

export interface StartAnalysisResponse {
  status: "analyzing";
  phase?: AnalysisPhase;
  generationMode?: "placeholder";
}

export interface ReferenceMaterialUploadResponse {
  referenceMaterial: string;
  fileName?: string;
}
