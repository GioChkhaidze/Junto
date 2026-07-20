from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from threading import RLock
from uuid import UUID

from junto.domain.entities import AnalysisPhase, Room, RoomStatus
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

  def ping(self) -> bool:
    return True

  def delete(self, room_id: UUID) -> bool:
    with self._lock:
      room = self._rooms.pop(room_id, None)
      if room is None:
        return False
      self._join_codes.pop(room.join_code, None)
      return True

  def delete_expired(self, *, before: datetime, answering_before: datetime) -> int:
    with self._lock:
      expired = [
        room_id
        for room_id, room in self._rooms.items()
        if room.updated_at < before
        and (
          room.status
          in {
            RoomStatus.DRAFT,
            RoomStatus.LOBBY,
            RoomStatus.PUBLISHED,
            RoomStatus.FAILED,
          }
          or (
            room.status == RoomStatus.ANSWERING and room.deadline_at is not None and room.deadline_at < answering_before
          )
        )
      ]
      for room_id in expired:
        room = self._rooms.pop(room_id)
        self._join_codes.pop(room.join_code, None)
      return len(expired)

  def recover_stale_analyses(self, *, before: datetime, failed_at: datetime) -> int:
    recovered = 0
    with self._lock:
      for room in self._rooms.values():
        started = room.analysis_started_at or room.updated_at
        if room.status != RoomStatus.ANALYZING or started >= before:
          continue
        room.status = RoomStatus.FAILED
        room.analysis_phase = AnalysisPhase.FAILED
        room.analysis_result = None
        room.grouping_result = None
        room.analysis_completed_at = failed_at
        room.last_error = "Analysis was interrupted. The host can retry once."
        room.updated_at = failed_at
        recovered += 1
    return recovered
