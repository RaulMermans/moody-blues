from __future__ import annotations

import json
import logging

from moody_blues.logging import JsonFormatter, request_id_var


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": msg})
    record.__dict__.update(extra)
    return record


def test_json_log_includes_request_id_and_extras() -> None:
    token = request_id_var.set("req_abc")
    try:
        line = JsonFormatter().format(_record("hello", path="/health", status=200))
    finally:
        request_id_var.reset(token)
    data = json.loads(line)
    assert data["msg"] == "hello"
    assert data["request_id"] == "req_abc"
    assert data["path"] == "/health"
    assert data["status"] == 200


def test_json_log_without_request_context() -> None:
    data = json.loads(JsonFormatter().format(_record("x")))
    assert "request_id" not in data
