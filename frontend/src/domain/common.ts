export type EntityId = string;
export type IsoDateTime = string;

export type RoomStatus = "draft" | "lobby" | "answering" | "analyzing" | "published" | "failed";

export type GroupingPolicy = "teach" | "explore";
export type AnalysisPhase = "not_started" | "analyzing_responses" | "forming_groups" | "complete" | "failed";

export interface GroupSize {
  minimum: number;
  preferred: number;
  maximum: number;
}

export type KnownRoomAction =
  | "editRoom"
  | "editQuestions"
  | "uploadMaterials"
  | "openLobby"
  | "startActivity"
  | "answer"
  | "submit"
  | "startAnalysis"
  | "viewProgress"
  | "viewAnalysisProgress"
  | "viewGroups"
  | "viewMyGroup"
  | "removeParticipant"
  | "waitForStart"
  | "waitForAnalysis"
  | "waitForGroups"
  | "viewFailure"
  | "retryAnalysis";

/**
 * The server is the authority for permitted actions. Keeping the string
 * extension lets it add an action without making an otherwise readable room
 * response unusable by an older frontend.
 */
export type RoomAction = KnownRoomAction | (string & {});
