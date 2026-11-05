"""Operator access: one shared token, sent server to server by the Next.js layer.

A full identity system is out of scope. What matters is that spending is refused by default: with
no token configured every operator route answers 403, and the browser never sees the token because
only the server-side route handlers send it.
"""

from __future__ import annotations

import hmac
import time
from collections import deque
from threading import Lock

from fastapi import Request

from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory, MoodyBluesError

MAX_FAILURES = 10
WINDOW_SECONDS = 60.0
_BEARER = "bearer "


class OperatorGate:
    def __init__(self, settings: Settings) -> None:
        token = settings.operator_token.get_secret_value() if settings.operator_token else ""
        self._token = token.encode("utf-8")
        self._failures: deque[float] = deque()
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _presented(self, request: Request) -> bytes | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith(_BEARER):
            return None
        return header[len(_BEARER) :].encode("utf-8")

    def _throttled(self, now: float) -> bool:
        while self._failures and now - self._failures[0] > WINDOW_SECONDS:
            self._failures.popleft()
        return len(self._failures) >= MAX_FAILURES

    def is_operator(self, request: Request) -> bool:
        """For public routes that show more to an operator. Never raises, never counts a miss."""
        presented = self._presented(request)
        return (
            self.configured
            and presented is not None
            and hmac.compare_digest(presented, self._token)
        )

    def require(self, request: Request) -> None:
        if not self.configured:
            raise MoodyBluesError(ErrorCategory.FORBIDDEN, "operator access is not enabled")
        now = time.monotonic()
        with self._lock:
            if self._throttled(now):
                raise MoodyBluesError(ErrorCategory.RATE_LIMITED, "too many failed attempts")
            if self.is_operator(request):
                return
            self._failures.append(now)
        raise MoodyBluesError(ErrorCategory.UNAUTHORIZED, "operator token required")
