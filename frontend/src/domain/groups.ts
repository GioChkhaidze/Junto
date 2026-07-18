import type { EntityId, GenerationMode, GroupingPolicy } from "./common";

export type SolverStatus = "optimal" | "feasible";
export type FullCoverageStatus = "feasible" | "infeasible" | "unknown";

export interface GroupMember {
  participantId: EntityId;
  displayName: string;
}

export interface GroupUnit {
  unitId: EntityId;
  text: string;
  covered: boolean;
  carriers: EntityId[];
}

export interface GroupFamily {
  familyId: EntityId;
  label: string;
  members: EntityId[];
}

export interface GroupAnswer {
  participantId: EntityId;
  text: string;
}

export interface GroupQuestionView {
  questionId: EntityId;
  prompt: string;
  units: GroupUnit[];
  families: GroupFamily[];
  answers?: GroupAnswer[];
}

export interface GroupView {
  id: EntityId;
  members: GroupMember[];
  questions: GroupQuestionView[];
}

export interface HostGroupsResponse {
  generationMode: GenerationMode;
  policy?: GroupingPolicy;
  solverStatus?: SolverStatus;
  fullCoverageStatus?: FullCoverageStatus;
  groups: GroupView[];
}

export interface MyGroupResponse {
  generationMode: GenerationMode;
  policy?: GroupingPolicy;
  group: GroupView;
}
