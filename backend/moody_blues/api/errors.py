"""Consistent error envelopes for every failure path."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from moody_blues.contracts.common import (
    ErrorCategory,
    ErrorDetail,
    ErrorResponse,
    MoodyBluesError,
)
from moody_blues.logging import request_id_var

log = logging.getLogger("moody_blues.errors")

_DOMAIN_STATUS: dict[ErrorCategory, int] = {
    ErrorCategory.VALIDATION: 422,
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.PROVIDER_NOT_CONFIGURED: 503,
    ErrorCategory.SANDBOX_UNAVAILABLE: 503,
    ErrorCategory.SANDBOX_IMAGE_UNAVAILABLE: 503,
    ErrorCategory.PROVIDER_RATE_LIMITED: 503,
    ErrorCategory.PROVIDER_TIMEOUT: 504,
}


def _expect[E: Exception](exc: Exception, kind: type[E]) -> E:
    """Narrow the handler argument; Starlette dispatches by type so this always holds."""
    if not isinstance(exc, kind):
        raise TypeError(f"handler for {kind.__name__} received {type(exc).__name__}")
    return exc


def _respond(status: int, detail: ErrorDetail) -> JSONResponse:
    body = ErrorResponse(error=detail, request_id=request_id_var.get())
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    exc = _expect(exc, MoodyBluesError)
    status = _DOMAIN_STATUS.get(exc.detail.category, 502)
    log.warning("domain_error", extra={"category": exc.detail.category, "status": status})
    return _respond(status, exc.detail)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    exc = _expect(exc, RequestValidationError)
    parts = [
        f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}"
        for err in exc.errors()
    ]
    return _respond(422, ErrorDetail(category=ErrorCategory.VALIDATION, message="; ".join(parts)))


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    exc = _expect(exc, StarletteHTTPException)
    category = ErrorCategory.NOT_FOUND if exc.status_code == 404 else ErrorCategory.INTERNAL
    if 400 <= exc.status_code < 500 and exc.status_code != 404:
        category = ErrorCategory.VALIDATION
    return _respond(exc.status_code, ErrorDetail(category=category, message=str(exc.detail)))


def internal_error_response(exc: BaseException) -> JSONResponse:
    """Envelope for unhandled exceptions. Called from ``RequestIdMiddleware`` rather than
    registered as an ``Exception`` handler: Starlette routes catch-all handlers to
    ``ServerErrorMiddleware``, which sits *outside* user middleware, so the response would
    lose its request id. Logged with traceback; the client gets a generic message."""
    log.error("unhandled_exception", exc_info=exc)
    return _respond(
        500, ErrorDetail(category=ErrorCategory.INTERNAL, message="Internal server error")
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MoodyBluesError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
