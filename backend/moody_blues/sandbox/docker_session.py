"""A disposable container that stays up, reachable only through its stdin and stdout.

It is built by ``DockerSandboxRunner._container_config``, so it has every restriction a sandbox
step has: no network, no mounts, no host environment, read-only root, dropped capabilities, memory,
CPU and PID limits, and an in-container deadline that survives the death of this process.

Docker multiplexes stdout and stderr onto one socket as framed chunks; stdin is written raw. The
socket is attached before the container starts, so no output is ever missed.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import socket
import struct
import threading
from typing import Any, cast

import docker.errors
import requests.exceptions
from docker.models.containers import Container

from moody_blues.contracts.common import ErrorCategory
from moody_blues.sandbox.base import SandboxError
from moody_blues.sandbox.session import (
    ReadStatus,
    SessionClosedError,
    SessionExit,
    SessionRead,
)

log = logging.getLogger("moody_blues.sandbox")

_FRAME_HEADER = 8
_STDOUT, _STDERR = 1, 2
_STDERR_TAIL_BYTES = 2_000
# A well-behaved agent has one message in flight. This bounds what a flooding one can queue.
_MAX_QUEUED_LINES = 8
_RECV_BYTES = 65_536
# An agent that stops reading must not be able to hold the host past its deadlines.
_SEND_TIMEOUT_SECONDS = 5


class _Demux:
    """Splits the framed stream into stdout lines and a bounded stderr tail."""

    def __init__(
        self, reads: queue.Queue[SessionRead], max_line_bytes: int, stop: threading.Event
    ) -> None:
        self._reads = reads
        self._stop = stop
        self._max_line = max_line_bytes
        self._pending = bytearray()
        self._line = bytearray()
        self.stdout_bytes = 0
        self.stderr_bytes = 0
        self.stderr_tail = bytearray()
        self.overflowed = False

    def _put(self, read: SessionRead) -> None:
        """Waits for room, which is how a flooding agent gets slowed. Gives up at close."""
        while not self._stop.is_set():
            try:
                self._reads.put(read, timeout=0.1)
            except queue.Full:
                continue
            return

    def feed(self, data: bytes) -> None:
        self._pending.extend(data)
        while len(self._pending) >= _FRAME_HEADER:
            length = struct.unpack(">I", self._pending[4:_FRAME_HEADER])[0]
            if len(self._pending) < _FRAME_HEADER + length:
                return
            stream = self._pending[0]
            payload = bytes(self._pending[_FRAME_HEADER : _FRAME_HEADER + length])
            del self._pending[: _FRAME_HEADER + length]
            if stream == _STDOUT:
                self._stdout(payload)
            elif stream == _STDERR:
                self.stderr_bytes += length
                self.stderr_tail.extend(payload)
                del self.stderr_tail[:-_STDERR_TAIL_BYTES]

    def _stdout(self, payload: bytes) -> None:
        self.stdout_bytes += len(payload)
        if self.overflowed:
            return
        self._line.extend(payload)
        while (end := self._line.find(b"\n")) != -1:
            if end > self._max_line:
                self._overflow()
                return
            self._put(SessionRead(status=ReadStatus.LINE, line=bytes(self._line[:end])))
            del self._line[: end + 1]
        if len(self._line) > self._max_line:
            self._overflow()

    def finish(self) -> None:
        self._put(SessionRead(status=ReadStatus.CLOSED))

    def _overflow(self) -> None:
        self.overflowed = True
        self._line.clear()
        self._put(SessionRead(status=ReadStatus.OVERSIZED))


class DockerSandboxSession:
    def __init__(
        self,
        *,
        client_timeout: float,
        container: Container,
        session_id: str,
        image: str,
        image_id: str | None,
        max_line_bytes: int,
    ) -> None:
        self._container = container
        self._session_id = session_id
        self._image = image
        self._image_id = image_id
        self._client_timeout = client_timeout
        self._reads: queue.Queue[SessionRead] = queue.Queue(maxsize=_MAX_QUEUED_LINES)
        self._closing = threading.Event()
        self._demux = _Demux(self._reads, max_line_bytes, self._closing)
        self._socket: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._ended = threading.Event()
        self._exit: SessionExit | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def execution_mode(self) -> str:
        return "docker_sandbox"

    @property
    def image(self) -> str:
        return self._image

    @property
    def image_id(self) -> str | None:
        return self._image_id

    def start(self) -> None:
        params = {"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1}
        attach = cast(Any, self._container).attach_socket
        # docker-py exposes no other handle on the raw socket.
        raw = cast(socket.socket, attach(params=params)._sock)
        raw.settimeout(None)
        raw.setsockopt(
            socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", _SEND_TIMEOUT_SECONDS, 0)
        )
        self._socket = raw
        self._reader = threading.Thread(target=self._pump, name="sandbox-session", daemon=True)
        self._reader.start()
        self._container.start()

    def _pump(self) -> None:
        sock = self._socket
        if sock is None:  # pragma: no cover - start() sets it first
            return
        try:
            while data := sock.recv(_RECV_BYTES):
                self._demux.feed(data)
        except OSError:
            pass  # close() shut the socket, or the daemon dropped it. Either way the stream ended.
        self._ended.set()
        self._demux.finish()

    def send(self, data: bytes) -> None:
        if self._socket is None or self._ended.is_set():
            raise SessionClosedError
        try:
            self._socket.sendall(data)
        except OSError as exc:
            raise SessionClosedError from exc

    def read_line(self, timeout: float) -> SessionRead:
        try:
            return self._reads.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return SessionRead(status=ReadStatus.TIMEOUT)

    def close(self, grace_seconds: float = 0.0) -> SessionExit:
        if self._exit is not None:
            return self._exit
        killed = False
        self._ended.wait(grace_seconds)
        self._closing.set()  # from here on, the reader drops what it reads
        exit_code: int | None = None
        oom = False
        try:
            self._container.reload()
            if self._container.status == "running":
                killed = True
                self._container.kill()
            self._container.wait(timeout=self._client_timeout)
            self._container.reload()
            state: dict[str, Any] = self._container.attrs["State"]
            exit_code = int(state["ExitCode"])
            oom = bool(state.get("OOMKilled", False))
        except docker.errors.NotFound:
            pass  # already gone: nothing left to read about it
        except (docker.errors.DockerException, requests.exceptions.RequestException):
            log.exception("sandbox_session_stop_failed", extra={"session": self._session_id})
        if self._socket is not None:
            with contextlib.suppress(OSError):  # already closed by the far end
                self._socket.shutdown(socket.SHUT_RDWR)
            self._socket.close()
        if self._reader is not None:
            self._reader.join(2.0)
        self._exit = SessionExit(
            exit_code=exit_code,
            oom_killed=oom,
            killed_by_host=killed,
            cleaned_up=self._remove(),
            stdout_bytes=self._demux.stdout_bytes,
            stderr_bytes=self._demux.stderr_bytes,
            stderr_tail=bytes(self._demux.stderr_tail),
        )
        return self._exit

    def _remove(self) -> bool:
        try:
            self._container.remove(force=True, v=True)
        except docker.errors.NotFound:
            return True
        except (docker.errors.DockerException, requests.exceptions.RequestException):
            log.exception("sandbox_session_cleanup_failed", extra={"session": self._session_id})
            return False
        return True


def start_failure(session_id: str, exc: Exception) -> SandboxError:
    return SandboxError(
        ErrorCategory.SANDBOX_RUNTIME, f"sandbox session {session_id} did not start: {exc}"
    )
