import type { AnalysisMode } from "./rooms";
import type { EntityId, IsoDateTime, RoomStatus } from "./common";

export interface ActivitySummary {
  roomId: EntityId;
  joinCode: string;
  title: string;
  status: RoomStatus;
  createdAt: IsoDateTime;
  groupingPublishedAt: IsoDateTime | null;
  participantCount: number;
  questionCount: number;
  groupCount: number;
  generationMode: AnalysisMode | null;
  fullyCoveredGroupQuestions: number | null;
  totalGroupQuestions: number | null;
}

export interface ActivityHistory {
  activities: ActivitySummary[];
}
