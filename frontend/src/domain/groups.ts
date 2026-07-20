import type { EntityId, GroupingPolicy, IsoDateTime } from "./common";

export interface GroupMember {
  participantId: EntityId;
  displayName: string;
}

export interface GroupView {
  id: EntityId;
  members: GroupMember[];
}

export interface PlaceholderHostGroupsResponse {
  generationMode: "placeholder";
  policy: GroupingPolicy;
  trigger: string;
  generatedAt: IsoDateTime;
  groups: GroupView[];
}

export interface PlaceholderMyGroupResponse {
  generationMode: "placeholder";
  policy: GroupingPolicy;
  generatedAt: IsoDateTime;
  group: GroupView;
}

export type SolverStatus = "optimal" | "feasible" | "fallback";
export type CompleteCoverageStatus = "feasible" | "infeasible" | "unknown";

export interface SolverObjective {
  name: string;
  value: number;
  provenOptimal: boolean;
}

export interface SolverSummary {
  status: SolverStatus;
  completeCoverageStatus: CompleteCoverageStatus;
  timedOut: boolean;
  solveMilliseconds: number;
  objectives: SolverObjective[];
}

export interface CoverageUnitResult {
  id: string;
  text: string;
  covered: boolean;
  carriers: GroupMember[];
}

export interface RepresentedFamily {
  id: string;
  label: string;
  members: GroupMember[];
}

export interface ResponseFamily {
  id: string;
  label: string;
}

export interface ResponseAudit {
  participant: GroupMember;
  answer: string | null;
  coveredUnitIds: string[];
  family: ResponseFamily | null;
}

export interface GroupQuestionResult {
  questionId: EntityId;
  position: number;
  prompt: string;
  fullyCovered: boolean;
  units: CoverageUnitResult[];
  representedFamilies: RepresentedFamily[];
  responseAudit?: ResponseAudit[];
}

export interface CoverageGroupView extends GroupView {
  questions: GroupQuestionResult[];
}

export interface CoverageAwareHostGroupsResponse {
  generationMode: "coverage_aware";
  policy: GroupingPolicy;
  trigger: string;
  generatedAt: IsoDateTime;
  solver: SolverSummary;
  coverageReport: { fullyCoveredGroupQuestions: number; totalGroupQuestions: number };
  groups: CoverageGroupView[];
}

export interface CoverageAwareMyGroupResponse {
  generationMode: "coverage_aware";
  policy: GroupingPolicy;
  generatedAt: IsoDateTime;
  completeCoverageStatus: CompleteCoverageStatus;
  group: CoverageGroupView;
}

export type HostGroupsResponse = PlaceholderHostGroupsResponse | CoverageAwareHostGroupsResponse;

export type MyGroupResponse = PlaceholderMyGroupResponse | CoverageAwareMyGroupResponse;
