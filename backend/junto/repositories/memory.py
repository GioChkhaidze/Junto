from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from uuid import UUID

from junto.domain.entities import Room
from junto.domain.errors import conflict, not_found


class InMemoryRoomRepository:
    """Thread-safe aggregate repository used by the first shippable slice and tests."""

    def __init__(self) -> None:
        self._rooms: dict[UUID, Room] = {}
        self._join_codes: dict[str, UUID] = {}
        self._lock = RLock()

    def add(self, room: Room) -> None:
        with self._lock:
            if room.id in self._rooms:
                raise conflict("ROOM_ALREADY_EXISTS", "The room already exists.")
            if room.join_code in self._join_codes:
                raise conflict("JOIN_CODE_COLLISION", "The join code is already in use.")
            self._rooms[room.id] = deepcopy(room)
            self._join_codes[room.join_code] = room.id

    def get(self, room_id: UUID) -> Room | None:
        with self._lock:
            room = self._rooms.get(room_id)
            return deepcopy(room) if room is not None else None

    def get_by_join_code(self, join_code: str) -> Room | None:
        with self._lock:
            room_id = self._join_codes.get(join_code)
            if room_id is None:
                return None
            return deepcopy(self._rooms[room_id])

    @contextmanager
    def transaction(self, room_id: UUID) -> Iterator[Room]:
        with self._lock:
            stored = self._rooms.get(room_id)
            if stored is None:
                raise not_found()
            working = deepcopy(stored)
            yield working
            self._rooms[room_id] = deepcopy(working)
