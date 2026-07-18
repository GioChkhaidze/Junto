from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from junto.domain.entities import Room


class RoomRepository(Protocol):
    def add(self, room: Room) -> None: ...

    def get(self, room_id: UUID) -> Room | None: ...

    def get_by_join_code(self, join_code: str) -> Room | None: ...

    def transaction(self, room_id: UUID) -> AbstractContextManager[Room]: ...

