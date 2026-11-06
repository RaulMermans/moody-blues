"""Runs your adapter inside the sandbox. Started for you; you never call this."""

from __future__ import annotations

import importlib
import os
import sys
import threading
import traceback
from typing import Any, BinaryIO, cast

from moody_blues_sdk.agent import (
    AgentAdapter,
    AgentResult,
    CustomerTask,
    ExecutionContext,
    Task,
    ToolDefinition,
)
from moody_blues_sdk.client import Cancelled, Exchange, HostGone, ModelClient, ToolClient
from moody_blues_sdk.protocol import SDK_VERSION, Channel, Message

EXIT_REFUSED = 3
EXIT_NO_RESULT = 4


def _load(entrypoint: str) -> AgentAdapter:
    module, _, name = entrypoint.partition(":")
    return getattr(importlib.import_module(module), name)()


def _hello(adapter: AgentAdapter) -> Message:
    return {
        "type": "hello",
        "agent": {
            "agent_id": adapter.agent_id,
            "name": adapter.name,
            "version": adapter.version,
            "target_type": adapter.target_type,
            "capabilities": list(adapter.capabilities),
            "config_refs": list(adapter.config_refs),
            "sdk_version": SDK_VERSION,
        },
    }


def _context(raw: dict[str, Any], exchange: Exchange, cancel: threading.Event) -> ExecutionContext:
    task = raw["task"]
    objective = task["objective"]
    customer = objective.get("customer")
    granted = tuple(raw["capabilities"])
    return ExecutionContext(
        run_id=raw["run_id"],
        correlation_id=raw["correlation_id"],
        scenario_ref=raw["scenario_ref"],
        task=Task(
            mission=task["mission"],
            instructions=objective["instructions"],
            objective=objective,
            _customer=None
            if customer is None
            else CustomerTask(
                name=customer["name"],
                email=customer["email"],
                metadata=dict(customer.get("metadata") or {}),
            ),
        ),
        tools=tuple(
            ToolDefinition(t["name"], t["description"], t["parameters"], t["access"])
            for t in raw["tools"]
        ),
        scopes=tuple(raw["scopes"]),
        deadline_seconds=raw["deadline_seconds"],
        max_tool_calls=raw["max_tool_calls"],
        capabilities=granted,
        model=ModelClient(exchange) if "model" in granted else None,
        _cancel=cancel,
    )


def _execute(adapter: AgentAdapter, context: ExecutionContext, tools: ToolClient) -> AgentResult:
    try:
        result = adapter.run(context, tools)
    except Cancelled:
        return AgentResult("cancelled", error_class="cancelled")
    except HostGone:
        raise
    except Exception as exc:  # noqa: BLE001 - any agent failure must reach the host as a report
        traceback.print_exc()
        return AgentResult.failed("agent_error", message=type(exc).__name__)
    if not isinstance(cast(object, result), AgentResult):
        return AgentResult.failed("agent_error", message="run() did not return an AgentResult")
    return result


def main(entrypoint: str, stdin: BinaryIO) -> None:
    # The protocol keeps a private copy of stdout; anything printed from here on goes to stderr.
    write_fd = os.dup(1)
    os.dup2(2, 1)
    channel = Channel(stdin, write_fd)
    adapter = _load(entrypoint)
    channel.send(_hello(adapter))
    welcome = channel.read()
    if welcome is None or welcome.get("type") != "welcome":
        print(f"refused by host: {welcome}", file=sys.stderr)
        sys.exit(EXIT_REFUSED)
    cancel = threading.Event()
    exchange = Exchange(channel, cancel)
    channel.listen(exchange.deliver)
    context = _context(welcome["context"], exchange, cancel)
    try:
        result = _execute(adapter, context, ToolClient(exchange))
    except HostGone:
        sys.exit(EXIT_NO_RESULT)
    channel.send(result.to_message())
    sys.stdout.flush()
    sys.stderr.flush()
    # The reader thread is blocked on stdin, and interpreter shutdown would wait on that lock.
    os._exit(0)
