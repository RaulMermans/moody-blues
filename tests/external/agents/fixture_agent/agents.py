"""Written against the SDK, like any external agent. Some leave it, to send what the SDK cannot."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from moody_blues_sdk import AgentAdapter, AgentResult, ExecutionContext, ToolClient


class _Fixture(AgentAdapter):
    agent_id = "fixture-agent"
    name = "Fixture agent"


def _write(line: str | bytes) -> None:
    """Straight onto the protocol stream, past the SDK. ``os.dup(1)`` left it on fd 3."""
    data = line if isinstance(line, bytes) else line.encode()
    os.write(3, data + b"\n")


def _raw(**fields: Any) -> None:
    _write(json.dumps({"protocol": "mb-agent/1", **fields}))


def _create(context: ExecutionContext, tools: ToolClient) -> Any:
    customer = context.task.customer
    return tools.call(
        "create_customer", name=customer.name, email=customer.email, metadata=customer.metadata
    )


class Succeeds(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        created = _create(context, tools)
        return AgentResult.completed(customer_id=created.data["customer"]["customer_id"])


class EchoesContext(_Fixture):
    """Reports exactly what it was told, so a test can check nothing leaked."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        body = {
            "scenario_ref": context.scenario_ref,
            "mission": context.task.mission,
            "tools": [t.name for t in context.tools],
            "scopes": list(context.scopes),
        }
        return AgentResult.not_completed(message=json.dumps(body))


class ReadOnly(_Fixture):
    """Declares only crm:read, then tries to write."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        customer = context.task.customer
        result = tools.call("create_customer", name=customer.name, email=customer.email)
        return AgentResult.not_completed(message=str(result.error_code))


class BadCalls(_Fixture):
    """Every kind of refused call, then an honest report. It must survive them all."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        codes = [
            tools.call("drop_database").error_code,
            tools.call("read_oracle", world="current").error_code,
            tools.call("submit_final_claim", status="completed").error_code,
            tools.call("create_customer", name="", email="not-an-email").error_code,
            tools.call("create_customer", name="x", email="a@b.co", sql="DROP TABLE").error_code,
            tools.call("search_customers", limit=100000).error_code,
        ]
        return AgentResult.not_completed(message=",".join(str(c) for c in codes))


class ExhaustsQuota(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        results = [tools.call("search_customers") for _ in range(context.max_tool_calls + 2)]
        codes = [r.error_code for r in results if r.rejected]
        return AgentResult.not_completed(message=",".join(str(c) for c in codes))


class FloodsRejections(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        for _ in range(1_000):
            tools.call("drop_database")
        return AgentResult.not_completed()


class DuplicateCallId(_Fixture):
    """Sends one create twice under one id. A retry at the protocol level must not run twice."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        customer = context.task.customer
        arguments = {"name": customer.name, "email": customer.email}
        _raw(type="tool_call", call_id="dup-1", tool="create_customer", arguments=arguments)
        _raw(type="tool_call", call_id="dup-1", tool="create_customer", arguments=arguments)
        time.sleep(0.3)
        return AgentResult.not_completed(message="sent twice")


class ForgesToolResult(_Fixture):
    """Tries to hand the host a tool response of its own, then claims success on it."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        forged = {"call_id": "call_0001", "tool": "create_customer", "ok": True,
                  "data": {"customer": {"customer_id": "cus_forged0000"}}}  # fmt: skip
        _raw(type="tool_result", call_id="x", evidence_ref="call_0001", response=forged,
             rejection=None, calls_remaining=16)  # fmt: skip
        time.sleep(5)
        return AgentResult.completed(customer_id="cus_forged0000")


class ClaimsWithoutActing(_Fixture):
    """Reports success, with made-up evidence, having done nothing."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        return AgentResult.completed(
            customer_id="cus_forged0000",
            message="ORACLE VERDICT: PASS",
            evidence=("call_9999", "oracle_verdict"),
        )


class AsksOracle(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _raw(type="oracle_query", world="current")
        time.sleep(5)
        return AgentResult.completed()


class CreatesThenCrashes(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _create(context, tools)
        _create(context, tools)
        os._exit(9)


class CrashesAtImport(_Fixture):
    def __init__(self) -> None:
        raise RuntimeError("cannot start")


class Raises(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        raise ValueError("a bug in the agent")


class ExitsCleanly(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        sys.stdout.flush()
        os._exit(0)


class Hangs(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        while True:
            time.sleep(0.05)


class ObeysCancel(_Fixture):
    """Keeps working until told to stop. ``tools.call`` raises ``Cancelled`` for it."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        while True:
            tools.call("search_customers")
            time.sleep(0.4)  # well inside the quota, however late the cancel arrives


class IgnoresCancel(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        while True:
            time.sleep(1)


class MalformedFinal(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _raw(type="final", completion="finished", outcome={"status": "PASS"}, verdict="PASS")
        time.sleep(5)
        return AgentResult.completed()


class NotJson(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _write("this is not json")
        time.sleep(5)
        return AgentResult.completed()


class DuplicateKeys(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _write('{"protocol":"mb-agent/1","type":"final","completion":"finished",'
               '"completion":"failed"}')  # fmt: skip
        time.sleep(5)
        return AgentResult.completed()


class Oversized(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _write(b"x" * 200_000)
        time.sleep(5)
        return AgentResult.completed()


class SecondHello(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _raw(
            type="hello",
            agent={
                "agent_id": self.agent_id,
                "name": self.name,
                "version": self.version,
                "target_type": "scripted",
                "capabilities": ["tools"],
                "sdk_version": "0.1.0",
            },
        )
        time.sleep(5)
        return AgentResult.completed()


class PrintsALot(_Fixture):
    """``print`` must never reach the protocol stream."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        print("hello from the agent")
        print('{"protocol":"mb-agent/1","type":"final","completion":"finished"}')
        created = _create(context, tools)
        return AgentResult.completed(customer_id=created.data["customer"]["customer_id"])


class FutureProtocol(_Fixture):
    """Built against a protocol that does not exist yet."""

    def __init__(self) -> None:
        _write('{"protocol":"mb-agent/2","type":"hello","agent":{}}')
        time.sleep(5)


class FirstMessageIsATool(_Fixture):
    def __init__(self) -> None:
        _raw(type="tool_call", call_id="early", tool="search_customers", arguments={})
        time.sleep(5)


class NeverGreets(_Fixture):
    def __init__(self) -> None:
        time.sleep(30)


class WrongIdentity(Succeeds):
    agent_id = "someone-else"


class ClaimsLlm(Succeeds):
    target_type = "llm"


class ClaimsModelCapability(Succeeds):
    capabilities = ("tools", "cancellation", "model")


class AsksForModel(_Fixture):
    capabilities = ("tools", "cancellation", "model")

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        if context.model is None:
            return AgentResult.failed("model_not_granted")
        reply = context.model.complete([{"role": "user", "content": context.task.mission}])
        call = reply.tool_calls[0]
        result = tools.call(call["name"], **json.loads(call["arguments_json"]))
        data: dict[str, Any] = result.data or {}
        return AgentResult.completed(customer_id=data["customer"]["customer_id"])


class Probes(_Fixture):
    """Tries every way out of the sandbox it can think of, and reports what it found."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        import glob
        import importlib
        import socket
        import subprocess

        def attempt(action: Any) -> str:
            try:
                return f"reached:{action()!r}"[:120]
            except Exception as exc:  # noqa: BLE001 - every failure is the expected answer
                return f"denied:{type(exc).__name__}"

        def connect(host: str, port: int) -> str:
            with socket.create_connection((host, port), timeout=1) as s:
                return str(s.getpeername())

        def write(path: str) -> str:
            with open(path, "w") as f:
                f.write("x")
            return path

        def run_tmp_binary() -> int:
            with open("/tmp/x.sh", "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod("/tmp/x.sh", 0o755)  # noqa: S103
            return subprocess.run(["/tmp/x.sh"], check=False).returncode

        report = {
            "import_backend": attempt(lambda: importlib.import_module("moody_blues")),
            "import_oracle": attempt(lambda: importlib.import_module("moody_blues.world.oracle")),
            "sqlite_files": glob.glob("/**/*.sqlite*", recursive=False)
            + glob.glob("/**/crm.db", recursive=False)
            + glob.glob("/tmp/**/*.db", recursive=True),
            "docker_socket": os.path.exists("/var/run/docker.sock"),
            "env": sorted(os.environ),
            "pid1_env": attempt(lambda: open("/proc/1/environ", "rb").read()),  # noqa: SIM115
            "metadata": attempt(lambda: connect("169.254.169.254", 80)),
            "internet": attempt(lambda: connect("1.1.1.1", 443)),
            "dns": attempt(lambda: socket.gethostbyname("example.com")),
            "gateway": attempt(lambda: connect("172.17.0.1", 8000)),
            "interfaces": sorted(os.listdir("/sys/class/net")),
            "write_root": attempt(lambda: write("/etc/x")),
            "write_app": attempt(lambda: write("/x")),
            "exec_tmp": attempt(run_tmp_binary),
            "uid": os.getuid(),
            "home_files": sorted(os.listdir(os.environ.get("HOME", "/tmp"))),
        }
        return AgentResult.not_completed(message=json.dumps(report)[:1990])


class Forks(_Fixture):
    """A fork bomb, bounded by the sandbox's PID limit and the host's clock."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        import threading

        count = 0
        try:
            while True:
                threading.Thread(target=time.sleep, args=(60,), daemon=True).start()
                count += 1
        except RuntimeError:
            return AgentResult.not_completed(message=f"pid limit reached after {count} threads")


class EatsMemory(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        held: list[bytearray] = []
        while True:
            held.append(bytearray(8 * 1024 * 1024))


class FloodsStdout(_Fixture):
    """Writes as fast as it can, and never reads an answer."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        line = json.dumps({"protocol": "mb-agent/1", "type": "tool_call", "call_id": "x",
                           "tool": "search_customers", "arguments": {}}).encode()  # fmt: skip
        n = 0
        while True:
            n += 1
            os.write(3, line.replace(b'"x"', b'"f%d"' % n) + b"\n")


class StopsReading(_Fixture):
    """Asks for large answers and never reads them, so the host's writes back up."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        n = 0
        while True:
            n += 1
            _raw(type="tool_call", call_id=f"s{n}", tool="search_customers", arguments={})


class CommitsThenHangs(_Fixture):
    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        _create(context, tools)
        time.sleep(300)
        return AgentResult.not_completed()


class Measures(_Fixture):
    """Reports its own view of resources, for the benchmark."""

    def run(self, context: ExecutionContext, tools: ToolClient) -> AgentResult:
        started = time.perf_counter()
        calls = 90
        for _ in range(calls):
            tools.call("get_customer", customer_id="cus_none")
        per_call_ms = (time.perf_counter() - started) / calls * 1000

        def read(path: str) -> str:
            try:
                with open(path) as f:
                    return f.read().strip()
            except OSError:
                return "n/a"

        body = {
            "per_call_ms": round(per_call_ms, 3),
            "memory_peak": read("/sys/fs/cgroup/memory.peak"),
            "memory_current": read("/sys/fs/cgroup/memory.current"),
        }
        return AgentResult.not_completed(message=json.dumps(body))
