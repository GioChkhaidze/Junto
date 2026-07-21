from __future__ import annotations

import json
from base64 import b64decode, b64encode
from copy import deepcopy

from itsdangerous import BadSignature
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection
from starlette.types import Message, Receive, Scope, Send


class WriteOnChangeSessionMiddleware(SessionMiddleware):
  """Persist signed cookie sessions only when application state changes.

  Starlette's default middleware reissues the complete session cookie on every
  response. A slow read-only poll can therefore overwrite a newer grant written
  by a join response from another tab. Keeping reads cookie-free removes that
  stale-response race while preserving the existing signed-cookie format.
  """

  async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] not in ("http", "websocket"):  # pragma: no cover
      await self.app(scope, receive, send)
      return

    connection = HTTPConnection(scope)
    if self.session_cookie in connection.cookies:
      data = connection.cookies[self.session_cookie].encode("utf-8")
      try:
        data = self.signer.unsign(data, max_age=self.max_age)
        scope["session"] = json.loads(b64decode(data))
      except BadSignature:
        scope["session"] = {}
    else:
      scope["session"] = {}
    initial_session = deepcopy(scope["session"])

    async def send_wrapper(message: Message) -> None:
      if message["type"] == "http.response.start" and scope["session"] != initial_session:
        headers = MutableHeaders(scope=message)
        if scope["session"]:
          data = b64encode(json.dumps(scope["session"]).encode("utf-8"))
          signed = self.signer.sign(data).decode("utf-8")
          max_age = f"Max-Age={self.max_age}; " if self.max_age else ""
          headers.append(
            "Set-Cookie",
            f"{self.session_cookie}={signed}; path={self.path}; {max_age}{self.security_flags}",
          )
        elif initial_session:
          headers.append(
            "Set-Cookie",
            f"{self.session_cookie}=null; path={self.path}; "
            f"expires=Thu, 01 Jan 1970 00:00:00 GMT; {self.security_flags}",
          )
      await send(message)

    await self.app(scope, receive, send_wrapper)
