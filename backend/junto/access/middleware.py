from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_logger = logging.getLogger("junto.request")
_uuid_pattern = re.compile(r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _origin(value: str) -> str | None:
  parsed = urlsplit(value)
  if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    return None
  return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


class TrustedOriginMiddleware(BaseHTTPMiddleware):
  """Reject browser mutations from origins outside the configured deployment."""

  def __init__(self, app: ASGIApp, *, trusted_origins: tuple[str, ...]) -> None:
    super().__init__(app)
    self._trusted = {item.rstrip("/") for item in trusted_origins}

  async def dispatch(
    self,
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
  ) -> Response:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
      supplied = request.headers.get("origin") or request.headers.get("referer")
      if supplied is not None and _origin(supplied) not in self._trusted:
        return JSONResponse(
          status_code=403,
          content={
            "error": {
              "code": "ORIGIN_NOT_TRUSTED",
              "message": "This request origin is not allowed.",
              "details": {},
            }
          },
        )
    return await call_next(request)


class SlidingWindowRateLimitMiddleware(BaseHTTPMiddleware):
  """Bound anonymous commands per source and, where applicable, per room."""

  def __init__(
    self,
    app: ASGIApp,
    *,
    join_per_minute: int,
    create_per_minute: int,
    authoring_per_minute: int,
    analysis_per_minute: int,
    answer_per_minute: int,
    status_per_minute: int,
    max_participants_per_room: int,
  ) -> None:
    super().__init__(app)
    self._source_limits = {
      "join": join_per_minute,
      "create": create_per_minute,
      "authoring": authoring_per_minute,
      "analysis": analysis_per_minute,
      "answer": answer_per_minute,
      "status": status_per_minute,
    }
    self._room_limits = {
      "join": max(join_per_minute, max_participants_per_room * 2),
      "analysis": max(analysis_per_minute * 2, 2),
      "answer": max(answer_per_minute, answer_per_minute * max_participants_per_room),
      "status": max(status_per_minute, status_per_minute * max_participants_per_room),
    }
    self._events: defaultdict[tuple[str, str, str], deque[float]] = defaultdict(deque)
    self._lock = threading.Lock()
    self._last_cleanup = time.monotonic()

  @staticmethod
  def _bucket(request: Request) -> tuple[str, str | None] | None:
    path = request.url.path
    segments = path.strip("/").split("/")
    if request.method == "POST" and len(segments) == 3 and segments[:2] == ["api", "join"]:
      return "join", segments[2].upper()
    if request.method == "POST" and path == "/api/rooms":
      return "create", None
    if request.method == "POST" and path == "/api/authoring/suggestions":
      return "authoring", None
    if (
      request.method == "POST"
      and len(segments) == 5
      and segments[:3] == ["api", "development", "rooms"]
      and segments[4] == "synthetic-responses"
    ):
      return "analysis", segments[3]
    if len(segments) < 3 or segments[:2] != ["api", "rooms"]:
      return None
    room_scope = segments[2]
    if request.method == "POST" and (path.endswith("/analysis") or path.endswith("/analysis/retry")):
      return "analysis", room_scope
    if request.method == "PUT" and len(segments) == 5 and segments[3] == "responses":
      return "answer", room_scope
    if request.method == "POST" and len(segments) == 4 and segments[3] == "submit":
      return "answer", room_scope
    if request.method == "GET" and len(segments) == 4 and segments[3] == "status":
      return "status", room_scope
    return None

  async def dispatch(
    self,
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
  ) -> Response:
    target = self._bucket(request)
    if target is None:
      return await call_next(request)
    bucket, room_scope = target
    client = request.client.host if request.client is not None else "unknown"
    now = time.monotonic()
    with self._lock:
      self._cleanup(now)
      checks = [
        ((bucket, "source", client), self._source_limits[bucket]),
      ]
      if room_scope is not None:
        checks.append(((bucket, "room", room_scope), self._room_limits[bucket]))
      exceeded = [(events, limit) for key, limit in checks if len(events := self._events[key]) >= limit]
      if exceeded:
        retry_after = max(max(1, round(60 - (now - events[0]))) for events, _limit in exceeded)
        return JSONResponse(
          status_code=429,
          headers={"Retry-After": str(retry_after)},
          content={
            "error": {
              "code": "RATE_LIMITED",
              "message": "Too many requests. Wait briefly and try again.",
              "details": {"retryAfterSeconds": retry_after},
            }
          },
        )
      for key, _limit in checks:
        self._events[key].append(now)
    return await call_next(request)

  def _cleanup(self, now: float) -> None:
    if now - self._last_cleanup < 60:
      return
    cutoff = now - 60
    for key, events in list(self._events.items()):
      while events and events[0] <= cutoff:
        events.popleft()
      if not events:
        del self._events[key]
    self._last_cleanup = now


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
  def __init__(self, app: ASGIApp, *, production: bool) -> None:
    super().__init__(app)
    self._production = production

  async def dispatch(
    self,
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
  ) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
      "Permissions-Policy",
      "camera=(), microphone=(), geolocation=(), payment=()",
    )
    if self._production:
      response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


class RequestTelemetryMiddleware(BaseHTTPMiddleware):
  """Emit bounded JSON request facts without room IDs, codes, prompts, or answers."""

  async def dispatch(
    self,
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
  ) -> Response:
    started = time.perf_counter()
    request_id = secrets.token_hex(8)
    try:
      response = await call_next(request)
    except Exception:
      _logger.exception(
        json.dumps(
          {
            "event": "request_failed",
            "requestId": request_id,
            "method": request.method,
            "route": _safe_route(request.url.path),
          }
        )
      )
      raise
    duration_ms = round((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    _logger.info(
      json.dumps(
        {
          "event": "request_complete",
          "requestId": request_id,
          "method": request.method,
          "route": _safe_route(request.url.path),
          "status": response.status_code,
          "durationMs": duration_ms,
        }
      )
    )
    return response


def _safe_route(path: str) -> str:
  safe = _uuid_pattern.sub("/{id}", path)
  if safe.startswith("/api/join/"):
    return "/api/join/{code}"
  return safe
