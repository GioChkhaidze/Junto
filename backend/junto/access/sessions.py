from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from fastapi import Request

from junto.domain.errors import DomainError, not_found


def ensure_session(request: Request) -> tuple[str, list[dict[str, Any]]]:
  nonce = request.session.get("nonce")
  if not isinstance(nonce, str) or not nonce:
    request.session["nonce"] = secrets.token_urlsafe(24)
  csrf = request.session.get("csrf")
  if not isinstance(csrf, str) or not csrf:
    csrf = secrets.token_urlsafe(24)
    request.session["csrf"] = csrf
  grants = request.session.get("grants")
  if not isinstance(grants, list):
    grants = []
    request.session["grants"] = grants
  return csrf, grants


def browser_session_nonce(request: Request) -> str:
  ensure_session(request)
  nonce = request.session.get("nonce")
  if not isinstance(nonce, str) or not nonce:  # defensive: ensure_session establishes it
    raise RuntimeError("Room session nonce was not initialized.")
  return nonce


def require_csrf(request: Request) -> None:
  csrf, _ = ensure_session(request)
  supplied = request.headers.get("X-CSRF-Token")
  if supplied is None or not secrets.compare_digest(supplied, csrf):
    raise DomainError(
      "CSRF_INVALID",
      "The request could not be verified. Refresh the page and try again.",
      403,
    )


def grant_host(request: Request, room_id: UUID, *, maximum: int) -> None:
  _upsert_grant(request, room_id, host=True, participant_id=None, maximum=maximum)


def grant_participant(
  request: Request,
  room_id: UUID,
  participant_id: UUID,
  *,
  maximum: int,
) -> None:
  _upsert_grant(
    request,
    room_id,
    host=False,
    participant_id=participant_id,
    maximum=maximum,
  )


def require_host(request: Request, room_id: UUID) -> None:
  _, grants = ensure_session(request)
  if not any(grant.get("roomId") == str(room_id) and grant.get("host") is True for grant in grants):
    raise not_found()


def participant_grant(request: Request, room_id: UUID) -> UUID:
  _, grants = ensure_session(request)
  for grant in grants:
    if grant.get("roomId") != str(room_id):
      continue
    participant_id = grant.get("participantId")
    if isinstance(participant_id, str):
      try:
        return UUID(participant_id)
      except ValueError:
        break
  raise not_found()


def optional_participant_grant(request: Request, room_id: UUID) -> UUID | None:
  try:
    return participant_grant(request, room_id)
  except DomainError:
    return None


def room_grants(request: Request) -> tuple[list[UUID], list[UUID]]:
  _, grants = ensure_session(request)
  hosts: list[UUID] = []
  participants: list[UUID] = []
  for grant in grants:
    try:
      room_id = UUID(str(grant.get("roomId")))
    except ValueError:
      continue
    if grant.get("host") is True:
      hosts.append(room_id)
    if isinstance(grant.get("participantId"), str):
      participants.append(room_id)
  return hosts, participants


def revoke_room_grant(request: Request, room_id: UUID) -> None:
  _, existing = ensure_session(request)
  request.session["grants"] = [grant for grant in existing if grant.get("roomId") != str(room_id)]


def _upsert_grant(
  request: Request,
  room_id: UUID,
  *,
  host: bool,
  participant_id: UUID | None,
  maximum: int,
) -> None:
  _, existing = ensure_session(request)
  grants = [grant for grant in existing if grant.get("roomId") != str(room_id)]
  current = next(
    (grant for grant in existing if grant.get("roomId") == str(room_id)),
    {"roomId": str(room_id)},
  )
  updated = {
    "roomId": str(room_id),
    "host": bool(current.get("host")) or host,
  }
  current_participant = current.get("participantId")
  if participant_id is not None:
    updated["participantId"] = str(participant_id)
  elif isinstance(current_participant, str):
    updated["participantId"] = current_participant
  grants.append(updated)
  request.session["grants"] = grants[-maximum:]
