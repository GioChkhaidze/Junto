import type { EntityId, GroupingPolicy, IsoDateTime } from "./common";

export interface GroupMember {
  participantId: EntityId;
  displayName: string;
}

export interface GroupView {
  id: EntityId;
  members: GroupMember[];
}

export interface HostGroupsResponse {
  generationMode: "placeholder";
  policy?: GroupingPolicy;
  trigger?: string;
  generatedAt?: IsoDateTime;
  groups: GroupView[];
}

export interface MyGroupResponse {
  generationMode: "placeholder";
  policy?: GroupingPolicy;
  trigger?: string;
  generatedAt?: IsoDateTime;
  group: GroupView;
}
