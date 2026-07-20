import pytest

from junto.domain.entities import GroupSize
from junto.domain.errors import DomainError
from junto.domain.grouping import balanced_capacities


@pytest.mark.parametrize(
  ("participants", "expected"),
  [(6, (3, 3)), (8, (4, 4)), (11, (4, 4, 3))],
)
def test_balanced_capacities(participants: int, expected: tuple[int, ...]) -> None:
  assert balanced_capacities(participants, GroupSize(3, 4, 5)) == expected


def test_infeasible_capacity_is_rejected() -> None:
  with pytest.raises(DomainError) as captured:
    balanced_capacities(2, GroupSize(3, 4, 5))
  assert captured.value.code == "GROUP_SIZE_INFEASIBLE"
