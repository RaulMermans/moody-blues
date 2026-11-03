"""Request-id propagation and request logging (pure ASGI middleware)."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from moody_blues.api.errors import internal_error_response
from moody_blues.logging import request_id_var

REQUEST_ID_HEADER = "x-request-id"
_VALID_INBOUND_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

log = logging.getLogger("moody_blues.http")


class RequestIdMiddleware:
    """Accepts a well-formed inbound ``X-Request-ID`` or generates one, binds it to the
    logging context, echoes it on the response and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = inbound if _VALID_INBOUND_ID.match(inbound) else f"req_{uuid.uuid4().hex}"
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if response_started:
                raise  # too late to send an envelope; let the server close the connection
            await internal_error_response(exc)(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)
