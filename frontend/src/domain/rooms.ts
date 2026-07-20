import type { AnalysisPhase, EntityId, GroupingPolicy, GroupSize, IsoDateTime, RoomAction, RoomStatus } from "./common";

export type AnalysisMode = "placeholder" | "coverage_aware";

interface RoomTiming {
  durationMinutes: number;
  serverTime: IsoDateTime;
  startedAt: IsoDateTime | null;
  deadlineAt: IsoDateTime | null;
  remainingSeconds: number | null;
  activityStarted: boolean;
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

export interface StartEligibility {
  eligible: boolean;
  reasonCode: "room_not_in_lobby" | "minimum_participants" | "group_size_infeasible" | null;
  message: string;
}

export interface HostRoom extends RoomTiming {
  id: EntityId;
  joinCode: string;
  title: string;
  policy: GroupingPolicy;
  groupSize: GroupSize;
  status: RoomStatus;
  questions: HostQuestion[];
  materials: ReferenceAttachment[];
  progress: RoomProgress;
  startEligibility: StartEligibility;
  allowedActions: RoomAction[];
  lastError: string | null;
  participants: ParticipantSummary[];
  analysisPhase: AnalysisPhase;
  analysisMode: AnalysisMode;
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

export interface PublicJoinRoom {
  title: string;
  status: "lobby";
  durationMinutes: number;
  questionCount: number;
  analysisMode: AnalysisMode;
}

export interface JoinRoomRequest {
  displayName: string;
}

export interface JoinRoomResponse {
  roomId: EntityId;
  participantId: EntityId;
  displayName: string;
}

export interface ParticipantRoom extends RoomTiming {
  roomId: EntityId;
  title: string;
  status: RoomStatus;
  participant: { participantId: EntityId; displayName: string; submittedAt: IsoDateTime | null };
  questions: ParticipantQuestion[];
  answeredQuestionCount: number;
  questionCount: number;
  allowedActions: RoomAction[];
  submittedAt: IsoDateTime | null;
  submitted: boolean;
  analysisPhase: AnalysisPhase;
  analysisMode: AnalysisMode;
}

export interface SaveAnswerRequest {
  text: string;
}

export interface SaveAnswerReceipt {
  questionId: EntityId;
  text: string;
  savedAt: IsoDateTime;
  answeredQuestionCount: number;
}

export interface SubmitResponsesResponse {
  status: RoomStatus;
  submittedAt: IsoDateTime;
  answeredQuestionCount: number;
  questionCount: number;
  analysisStarted: boolean;
}

export interface RoomStatusProjection extends RoomTiming {
  status: RoomStatus;
  allowedActions: RoomAction[];
  startEligibility?: StartEligibility;
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
  analysisMode: AnalysisMode;
}

export interface StartAnalysisResponse {
  status: "analyzing";
  analysisPhase: AnalysisPhase;
}

export interface ReferenceMaterialUploadResponse {
  material: ReferenceAttachment;
}

export type AuthoringSuggestionTarget = "question" | "coverage";

export interface AuthoringQuestionDraft {
  prompt: string;
  coverageUnits: string[];
}

export interface AuthoringSuggestionRequest {
  activityTitle: string;
  target: AuthoringSuggestionTarget;
  targetQuestionIndex: number;
  questions: AuthoringQuestionDraft[];
  referenceText?: string;
}

export interface AuthoringSuggestionResponse {
  questionPrompt: string;
  coverageUnits: string[];
}
