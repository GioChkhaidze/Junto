import type { RoomStatus } from "./common";

export type SyntheticResponseSource = "patterned" | "openrouter";

export interface SyntheticClassroomProjection {
  enabled: boolean;
  stage: RoomStatus;
  syntheticParticipantCount: number;
  pendingSyntheticParticipantCount: number;
  targetSizes: number[];
  canConfigure: boolean;
  canGenerate: boolean;
  patternedAvailable: boolean;
  openRouterAvailable: boolean;
}

export interface ConfigureSyntheticCohortRequest {
  targetSize: number;
  seed?: number;
}

export interface GenerateSyntheticResponsesRequest {
  source: SyntheticResponseSource;
}

export interface GenerateSyntheticResponsesResponse {
  simulation: SyntheticClassroomProjection;
  source: SyntheticResponseSource;
  participantCount: number;
  responseCount: number;
  models: string[];
}
