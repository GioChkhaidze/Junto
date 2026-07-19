from __future__ import annotations

from abc import ABC, abstractmethod
from math import ceil, floor

from junto.domain.entities import Group, GroupingResult, GroupSize, Room
from junto.domain.errors import conflict


class GroupingService(ABC):
    """Narrow seam that the real optimizer can replace later."""

    @abstractmethod
    def form_groups(self, room: Room, *, trigger: str) -> GroupingResult:
        raise NotImplementedError


class DeterministicPlaceholderGroupingService(GroupingService):
    """Balanced, deterministic partitioning with no semantic or optimality claims."""

    def form_groups(self, room: Room, *, trigger: str) -> GroupingResult:
        participant_ids = sorted(
            room.cohort_ids,
            key=lambda participant_id: (
                room.participants[participant_id].joined_at,
                str(participant_id),
            ),
        )
        capacities = balanced_capacities(len(participant_ids), room.group_size)
        groups: list[Group] = []
        offset = 0
        for index, capacity in enumerate(capacities, start=1):
            members = tuple(participant_ids[offset : offset + capacity])
            groups.append(Group(id=f"g{index}", participant_ids=members))
            offset += capacity
        return GroupingResult(
            generation_mode="placeholder",
            policy=room.policy,
            trigger=trigger,
            generated_at=room.updated_at,
            groups=tuple(groups),
        )


def balanced_capacities(participant_count: int, bounds: GroupSize) -> tuple[int, ...]:
    minimum = bounds.minimum
    preferred = bounds.preferred
    maximum = bounds.maximum
    if participant_count <= 0:
        raise conflict("EMPTY_COHORT", "At least one participant is required to form groups.")

    first_count = ceil(participant_count / maximum)
    last_count = floor(participant_count / minimum)
    candidates: list[tuple[tuple[int, int, int], tuple[int, ...]]] = []
    for group_count in range(first_count, last_count + 1):
        small, larger_groups = divmod(participant_count, group_count)
        capacities = tuple(
            [small + 1] * larger_groups + [small] * (group_count - larger_groups)
        )
        if not capacities or min(capacities) < minimum or max(capacities) > maximum:
            continue
        score = (
            sum(abs(capacity - preferred) for capacity in capacities),
            max(capacities) - min(capacities),
            group_count,
        )
        candidates.append((score, capacities))
    if not candidates:
        raise conflict(
            "GROUP_SIZE_INFEASIBLE",
            "The current participant count cannot satisfy the configured group sizes.",
        )
    return min(candidates, key=lambda item: item[0])[1]
