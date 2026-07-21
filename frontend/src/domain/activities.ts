import type { AnalysisMode } from "./rooms";
import type { EntityId, IsoDateTime, RoomStatus } from "./common";
import type { HostGroupsResponse } from "./groups";

export interface ActivitySummary {
  roomId: EntityId;
  joinCode: string | null;
  canDelete: boolean;
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

export interface PublishedActivity {
  roomId: EntityId;
  title: string;
  createdAt: IsoDateTime;
  participantCount: number;
  result: HostGroupsResponse;
}
