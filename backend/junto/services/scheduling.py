from __future__ import annotations

from collections.abc import Callable
from threading import Timer
from typing import Protocol


class Scheduler(Protocol):
    def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> None: ...


class ThreadingScheduler:
    """Small, intentionally non-durable scheduler for the hackathon runtime."""

    def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> None:
        timer = Timer(max(0.0, delay_seconds), callback)
        timer.daemon = True
        timer.start()

