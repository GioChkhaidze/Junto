from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send


class RequestBodyTooLarge(Exception):
    pass


class MaterialUploadLimitMiddleware:
    """Bound multipart material requests before Starlette spools the upload."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, maximum_bytes: int) -> None:
        self._app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_material_upload(scope):
            await self._app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self._maximum_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._maximum_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self._app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._reject(scope, receive, send)

    @staticmethod
    def _is_material_upload(scope: Scope) -> bool:
        if scope.get("type") != "http" or scope.get("method") != "POST":
            return False
        path = str(scope.get("path", "")).rstrip("/")
        return path.startswith("/api/rooms/") and path.endswith("/materials")

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "REFERENCE_REQUEST_TOO_LARGE",
                    "message": "Reference uploads must be at most 5 MB.",
                    "details": {},
                }
            },
        )
        await response(scope, receive, send)
