export type EntityId = string;
export type IsoDateTime = string;

export type RoomStatus =
  | "draft"
  | "open"
  | "analyzing"
  | "ready"
  | "published"
  | "failed";

export type GroupingPolicy = "teach" | "explore";
export type AnalysisPhase = "semantic" | "grouping";
export type GenerationMode = "placeholder" | "engine";

export interface GroupSize {
  minimum: number;
  preferred: number;
  maximum: number;
}

/**
 * Timing is server-authoritative. All fields are optional while the backend
 * prototype is being brought up, so an older response remains consumable.
 */
export interface ActivityTiming {
  durationSeconds?: number;
  serverTime?: IsoDateTime;
  startedAt?: IsoDateTime | null;
  deadlineAt?: IsoDateTime | null;
  remainingSeconds?: number | null;
  activityStarted?: boolean;
}

export type KnownRoomAction =
  | "edit"
  | "open"
  | "join"
  | "start"
  | "answer"
  | "submit"
  | "analyze"
  | "optimize"
  | "publish"
  | "viewGroups"
  | "viewMyGroup"
  | "removeParticipant";

/**
 * The server is the authority for permitted actions. Keeping the string
 * extension lets it add an action without making an otherwise readable room
 * response unusable by an older frontend.
 */
export type RoomAction = KnownRoomAction | (string & {});
