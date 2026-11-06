"""OFFLINE harness for the external agent adapter.

``LocalProcessRunner`` is a TEST DOUBLE for the sandbox. It starts a real process and speaks to it
over real pipes, so the bootstrap, the bundle, the SDK, the agent and the driver are all exercised
for real, across a real process boundary, with real worlds and the real Oracle. It contains
nothing: its runs are labeled ``local_process_test_double``, and only trusted test agents go
through it. Containment evidence comes from tests/integration and tests/security, in real Docker.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest

from moody_blues.contracts.adapter import AdapterLimits
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest
from moody_blues.experiments.target import TargetRequest, TargetResult
from moody_blues.external.bundle import AgentBundle, build_bundle
from moody_blues.external.target import ExternalAgentTarget, LiveInference
from moody_blues.sandbox.session import (
    ReadStatus,
    SessionClosedError,
    SessionExit,
    SessionRead,
)
from moody_blues.world.scenarios import load_scenario

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples" / "external-agent"
FIXTURES = Path(__file__).parent / "agents"
LIMITS = SandboxLimits(wall_timeout_seconds=30, memory_mb=128, cpus=0.5, pids_limit=32)
FAST = AdapterLimits(
    startup_timeout_seconds=10,
    run_timeout_seconds=8,
    cancel_grace_seconds=0.5,
    exit_grace_seconds=0.5,
)


class LocalProcessSession:
    """TEST DOUBLE. A real process on real pipes, and no containment at all."""

    def __init__(self, code: str, cwd: Path, max_line_bytes: int) -> None:
        self.session_id = f"local_{uuid.uuid4().hex[:12]}"
        self.execution_mode = "local_process_test_double"
        self.image = "local-process"
        self.image_id = None
        self._max_line = max_line_bytes
        self._reads: queue.Queue[SessionRead] = queue.Queue()
        self._stderr = bytearray()
        self._stdout_bytes = 0
        self._process = subprocess.Popen(  # noqa: S603 - a fixed interpreter, trusted test agents
            [sys.executable, "-I", "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env={"HOME": str(cwd)},
        )
        threading.Thread(target=self._pump_out, daemon=True).start()
        self._err_thread = threading.Thread(target=self._pump_err, daemon=True)
        self._err_thread.start()

    def _pump_out(self) -> None:
        stream = self._process.stdout
        if stream is None:  # pragma: no cover - PIPE was requested
            return
        while line := stream.readline(self._max_line + 2):
            self._stdout_bytes += len(line)
            if not line.endswith(b"\n"):
                self._reads.put(SessionRead(status=ReadStatus.OVERSIZED))
                return
            self._reads.put(SessionRead(status=ReadStatus.LINE, line=line[:-1]))
        self._reads.put(SessionRead(status=ReadStatus.CLOSED))

    def _pump_err(self) -> None:
        stream = self._process.stderr
        if stream is None:  # pragma: no cover - PIPE was requested
            return
        while chunk := stream.read(4096):
            self._stderr.extend(chunk)

    def send(self, data: bytes) -> None:
        stdin = self._process.stdin
        if stdin is None:  # pragma: no cover - PIPE was requested
            raise SessionClosedError
        try:
            stdin.write(data)
            stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise SessionClosedError from exc

    def read_line(self, timeout: float) -> SessionRead:
        try:
            return self._reads.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return SessionRead(status=ReadStatus.TIMEOUT)

    def close(self, grace_seconds: float = 0.0) -> SessionExit:
        killed = False
        try:
            self._process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            killed = True
            self._process.kill()
            self._process.wait(timeout=5)
        self._err_thread.join(1.0)
        return SessionExit(
            exit_code=self._process.returncode,
            oom_killed=False,
            killed_by_host=killed,
            cleaned_up=True,
            stdout_bytes=self._stdout_bytes,
            stderr_bytes=len(self._stderr),
            stderr_tail=bytes(self._stderr[-2000:]),
        )


class LocalProcessRunner:
    """TEST DOUBLE for the sandbox. Never use it for code you did not write."""

    approved_for_generated_code = True

    def __init__(self, root: Path) -> None:
        self._root = root
        self.sessions: list[LocalProcessSession] = []

    def open_session(self, request: SandboxRequest, *, max_line_bytes: int) -> LocalProcessSession:
        cwd = self._root / f"proc-{uuid.uuid4().hex[:8]}"
        cwd.mkdir(parents=True)
        session = LocalProcessSession(request.code, cwd, max_line_bytes)
        self.sessions.append(session)
        return session

    def ping(self) -> None:
        return None


def fixture_manifest(
    tmp_path: Path,
    entry: str,
    *,
    scopes: tuple[str, ...] = ("crm:read", "crm:write"),
    target_type: str = "scripted",
    capabilities: tuple[str, ...] = ("tools", "cancellation"),
    module: str = "agents",
) -> Path:
    """A manifest beside a copy of the fixture package, as a developer's repository would be."""
    directory = tmp_path / "agent-repo"
    if not directory.exists():
        directory.mkdir()
        (directory / "fixture_agent").symlink_to(FIXTURES / "fixture_agent")
    path = directory / f"{entry}.agent.toml"
    path.write_text(
        f"""
protocol = "mb-agent/1"
agent_id = "fixture-agent"
name = "Fixture agent"
version = "0.1.0"
target_type = "{target_type}"
package = "fixture_agent"
entrypoint = "fixture_agent.{module}:{entry}"
capabilities = {list(capabilities)!r}
scopes = {list(scopes)!r}
""",
        encoding="utf-8",
    )
    return path


RunFn = Callable[..., TargetResult]


def run_agent(
    tmp_path: Path,
    bundle: AgentBundle,
    *,
    scenario: str = "normal-success",
    limits: AdapterLimits = FAST,
    cancel: Event | None = None,
    live: LiveInference | None = None,
) -> TargetResult:
    root = tmp_path / f"worlds-{uuid.uuid4().hex[:6]}"
    root.mkdir()
    target = ExternalAgentTarget(
        runner=LocalProcessRunner(tmp_path / f"procs-{uuid.uuid4().hex[:6]}"),
        bundle=bundle,
        sandbox_limits=LIMITS,
        limits=limits,
        live=live,
    )
    return target.run(
        TargetRequest(
            scenario=load_scenario(scenario),
            config=AgentConfigName.BASELINE,
            world_root=root,
            max_wall_seconds=30,
            cancel=cancel,
        )
    )


@pytest.fixture
def fixture_run(tmp_path: Path) -> RunFn:
    def go(entry: str, *, module: str = "agents", **options: object) -> TargetResult:
        manifest_keys = {"scopes", "target_type", "capabilities"}
        manifest = {k: v for k, v in options.items() if k in manifest_keys}
        run = {k: v for k, v in options.items() if k not in manifest_keys}
        path = fixture_manifest(tmp_path, entry, module=module, **manifest)  # pyright: ignore[reportArgumentType]
        return run_agent(tmp_path, build_bundle(path), **run)  # pyright: ignore[reportArgumentType]

    return go


@pytest.fixture
def example_run(tmp_path: Path) -> Callable[..., TargetResult]:
    def go(name: str, scenario: str = "normal-success") -> TargetResult:
        return run_agent(
            tmp_path,
            build_bundle(EXAMPLES / f"{name}.agent.toml"),
            scenario=scenario,
            limits=FAST,
        )

    return go
