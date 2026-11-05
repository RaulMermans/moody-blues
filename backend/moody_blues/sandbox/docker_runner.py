"""Disposable-container sandbox backed by a local Docker daemon.

Implemented restrictions (per run):
  * fresh container, removed (with anonymous volumes) in ``finally``
  * ``network_mode=none`` unless the request explicitly enables networking
  * unprivileged uid/gid 65534 (nobody), ``cap_drop=ALL``, ``no-new-privileges``
  * read-only root filesystem; only a small ``noexec`` tmpfs at /tmp
  * memory (swap disabled), CPU quota and PID limits
  * no host mounts, no Docker socket, no host environment variables
  * output captured from a stream attached before start: exact byte counts, bounded memory
  * wall-clock timeout enforced by the host, followed by SIGKILL
  * a second, later deadline enforced *inside* the container by ``timeout`` as PID 1, so a
    run stops even if the host process that started it has crashed
  * cancellation: trusted code can stop an active run through a ``threading.Event``

These are *configured restrictions*. Containment guarantees ultimately depend on the
host kernel, the container runtime and its seccomp/AppArmor profiles; see
docs/architecture/overview.md#sandbox-threat-model.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Iterable
from typing import Any, cast

import docker
import docker.errors
import requests.exceptions
from docker.models.containers import Container
from docker.types import LogConfig

from moody_blues.config import Settings
from moody_blues.contracts.common import ErrorCategory, ExecutionStatus
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest, SandboxResult
from moody_blues.sandbox.base import SandboxError, SandboxUnavailableError
from moody_blues.sandbox.docker_host import resolve_docker_host

log = logging.getLogger("moody_blues.sandbox")

SANDBOX_LABEL = "io.moody-blues.sandbox"
RUN_ID_LABEL = "io.moody-blues.run-id"
EXPIRES_AT_LABEL = "io.moody-blues.expires-at"
SANDBOX_UID = "65534:65534"

# The in-container deadline trails the host deadline so that the host normally decides (and
# reports TIMED_OUT). It only matters when the host process is gone.
HARD_DEADLINE_GRACE_SECONDS = 10
# A container past its in-container deadline plus this margin has no live owner.
ORPHAN_MARGIN_SECONDS = 30
_CANCEL_POLL_SECONDS = 0.25
_CAPTURE_JOIN_SECONDS = 5.0


class _OutputCapture:
    """Reads a container's attached output stream on a background thread.

    Attached before ``start``, so every byte the process writes is counted. The json-file
    log driver cannot provide this: once its ``max-size`` is reached it discards older output,
    and reading the logs back then shows a short, apparently complete stream. At most ``limit``
    bytes per channel are kept in memory; the rest is only counted.
    """

    def __init__(self, stream: Iterable[tuple[bytes | None, bytes | None]], limit: int) -> None:
        self._stream = stream
        self._limit = limit
        self.stdout = bytearray()
        self.stderr = bytearray()
        self.stdout_bytes = 0
        self.stderr_bytes = 0
        self.failed = False
        self._thread = threading.Thread(target=self._drain, name="sandbox-output", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _keep(self, buffer: bytearray, chunk: bytes) -> None:
        room = self._limit - len(buffer)
        if room > 0:
            buffer.extend(chunk[:room])

    def _drain(self) -> None:
        try:
            for out, err in self._stream:
                if out:
                    self.stdout_bytes += len(out)
                    self._keep(self.stdout, out)
                if err:
                    self.stderr_bytes += len(err)
                    self._keep(self.stderr, err)
        except (OSError, ValueError, docker.errors.DockerException):
            log.exception("sandbox_output_stream_failed")
            self.failed = True

    def finish(self) -> bool:
        """Wait for end of stream. True only if the whole stream was read."""
        self._thread.join(_CAPTURE_JOIN_SECONDS)
        return not self._thread.is_alive() and not self.failed


class DockerSandboxRunner:
    def __init__(
        self,
        *,
        image: str,
        default_limits: SandboxLimits,
        output_limit_bytes: int,
        docker_host: str | None = None,
        auto_pull: bool = True,
        api_timeout_seconds: float = 30.0,
    ) -> None:
        self.image = image
        self.default_limits = default_limits
        self.output_limit_bytes = output_limit_bytes
        self.docker_host, self.docker_host_source = resolve_docker_host(docker_host)
        self.auto_pull = auto_pull
        # Only a pinned image that can never be replaced by a pull may run generated code.
        self.approved_for_generated_code = "@sha256:" in image and not auto_pull
        self._api_timeout = api_timeout_seconds
        self._client: docker.DockerClient | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> DockerSandboxRunner:
        return cls(
            image=settings.sandbox_image,
            default_limits=SandboxLimits(
                wall_timeout_seconds=settings.sandbox_wall_timeout_seconds,
                memory_mb=settings.sandbox_memory_mb,
                cpus=settings.sandbox_cpus,
                pids_limit=settings.sandbox_pids_limit,
            ),
            output_limit_bytes=settings.sandbox_output_limit_bytes,
            docker_host=settings.docker_host,
        )

    # -- daemon -----------------------------------------------------------------

    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            try:
                self._client = docker.DockerClient(
                    base_url=self.docker_host, timeout=int(self._api_timeout)
                )
            except docker.errors.DockerException as exc:
                raise SandboxUnavailableError(
                    f"cannot create Docker client for {self.docker_host}: {exc}"
                ) from exc
        return self._client

    def ping(self) -> None:
        try:
            self._docker().ping()
        except (docker.errors.DockerException, requests.exceptions.RequestException) as exc:
            raise SandboxUnavailableError(
                f"Docker daemon unreachable at {self.docker_host} "
                f"(from {self.docker_host_source}): {exc}"
            ) from exc

    def ensure_image(self) -> None:
        client = self._docker()
        try:
            client.images.get(self.image)
        except docker.errors.ImageNotFound:
            if not self.auto_pull:
                raise SandboxError(
                    ErrorCategory.SANDBOX_IMAGE_UNAVAILABLE,
                    f"image {self.image} not present and auto_pull is disabled",
                ) from None
            log.info("pulling_sandbox_image", extra={"image": self.image})
            try:
                client.images.pull(self.image)
            except docker.errors.APIError as exc:
                raise SandboxError(
                    ErrorCategory.SANDBOX_IMAGE_UNAVAILABLE,
                    f"failed to pull {self.image}: {exc}",
                ) from exc
        except (docker.errors.DockerException, requests.exceptions.RequestException) as exc:
            raise SandboxUnavailableError(f"Docker daemon error: {exc}") from exc

    def runtime_info(self) -> tuple[str, list[str]]:
        """The default OCI runtime and every runtime this daemon offers."""
        info = self._docker().info()
        return str(info.get("DefaultRuntime")), sorted(info["Runtimes"])

    def image_digests(self) -> list[str]:
        """Repository digests of the configured image, as the daemon knows it."""
        image = self._docker().images.get(self.image)
        return list(image.attrs.get("RepoDigests") or [])

    def resolved_image_id(self) -> str | None:
        """What the daemon runs for the configured image. Its form depends on the image store."""
        return self._docker().images.get(self.image).id

    def list_sandbox_containers(self) -> list[Container]:
        """All containers (any state) created by this runner. Used to verify cleanup."""
        return self._docker().containers.list(all=True, filters={"label": SANDBOX_LABEL})

    # -- execution ----------------------------------------------------------------

    def reap_orphans(self, *, now: float | None = None) -> list[str]:
        """Remove containers whose in-container deadline has long passed.

        Such a container's owner died before its ``finally`` ran: a live owner removes its
        container well before this point. Returns the removed run ids.
        """
        current = time.time() if now is None else now
        removed: list[str] = []
        for container in self.list_sandbox_containers():
            labels = container.labels or {}
            expires = labels.get(EXPIRES_AT_LABEL)
            # An unlabeled container predates this field and cannot be judged; leave it.
            if expires is not None and float(expires) <= current and self._remove(container):
                removed.append(labels.get(RUN_ID_LABEL, container.name or "unknown"))
        return removed

    def _container_config(self, run_id: str, code: str, limits: SandboxLimits) -> dict[str, Any]:
        memory = f"{limits.memory_mb}m"
        hard_deadline = math.ceil(limits.wall_timeout_seconds) + HARD_DEADLINE_GRACE_SECONDS
        expires_at = int(time.time()) + hard_deadline + ORPHAN_MARGIN_SECONDS
        return {
            "image": self.image,
            # ``timeout`` runs as PID 1. The kernel ignores SIGKILL sent to a namespace's init
            # from inside that namespace, so the sandboxed code cannot remove this deadline.
            "command": ["timeout", "-s", "KILL", str(hard_deadline), "python", "-I", "-c", code],
            "name": f"moody-sbx-{run_id}",
            "labels": {
                SANDBOX_LABEL: "true",
                RUN_ID_LABEL: run_id,
                EXPIRES_AT_LABEL: str(expires_at),
            },
            "user": SANDBOX_UID,
            "working_dir": "/tmp",
            "environment": {"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
            "network_mode": "bridge" if limits.network_enabled else "none",
            "mem_limit": memory,
            "memswap_limit": memory,
            "nano_cpus": int(limits.cpus * 1_000_000_000),
            "pids_limit": limits.pids_limit,
            "read_only": True,
            "tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16m"},
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "ipc_mode": "private",
            "log_config": LogConfig(
                type="json-file",
                config={"max-size": str(self.output_limit_bytes * 2), "max-file": "1"},
            ),
            "detach": True,
            "stdin_open": False,
            "tty": False,
        }

    def _await_exit(
        self, container: Container, limits: SandboxLimits, cancel: threading.Event | None
    ) -> ExecutionStatus | None:
        """Block until exit, deadline or cancellation. Returns the forced status, if any."""
        deadline = time.monotonic() + limits.wall_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ExecutionStatus.TIMED_OUT
            if cancel is not None and cancel.is_set():
                return ExecutionStatus.CANCELLED
            wait = remaining if cancel is None else min(remaining, _CANCEL_POLL_SECONDS)
            try:
                container.wait(timeout=wait)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                # docker-py surfaces the wait deadline as a client-side read timeout.
                continue
            return None

    def run(
        self, request: SandboxRequest, *, cancel: threading.Event | None = None
    ) -> SandboxResult:
        limits = request.limits or self.default_limits
        run_id = f"sbx_{uuid.uuid4().hex[:16]}"
        self.ensure_image()
        client = self._docker()

        container: Container | None = None
        started = time.perf_counter()
        try:
            container = client.containers.create(
                **self._container_config(run_id, request.code, limits)
            )
            image_id = cast(str | None, container.attrs.get("Image"))
            stream = container.attach(stdout=True, stderr=True, stream=True, logs=False, demux=True)
            capture = _OutputCapture(
                cast(Iterable[tuple[bytes | None, bytes | None]], stream), self.output_limit_bytes
            )
            capture.start()
            container.start()
            forced = self._await_exit(container, limits, cancel)
            if forced is not None:
                self._kill(container)
                container.wait(timeout=self._api_timeout)
            duration_ms = int((time.perf_counter() - started) * 1000)

            container.reload()
            state: dict[str, Any] = container.attrs["State"]
            exit_code = int(state["ExitCode"])
            oom_killed = bool(state.get("OOMKilled", False))
            output_complete = capture.finish()
        except (docker.errors.DockerException, requests.exceptions.RequestException) as exc:
            raise SandboxError(
                ErrorCategory.SANDBOX_RUNTIME, f"sandbox run {run_id} failed: {exc}"
            ) from exc
        finally:
            cleaned_up = self._remove(container) if container is not None else True

        if forced is not None:
            status = forced
        elif exit_code == 0:
            status = ExecutionStatus.SUCCEEDED
        else:
            status = ExecutionStatus.FAILED

        result = SandboxResult(
            run_id=run_id,
            status=status,
            exit_code=exit_code,
            stdout=bytes(capture.stdout).decode("utf-8", errors="replace"),
            stderr=bytes(capture.stderr).decode("utf-8", errors="replace"),
            stdout_truncated=capture.stdout_bytes > self.output_limit_bytes,
            stderr_truncated=capture.stderr_bytes > self.output_limit_bytes,
            stdout_bytes=capture.stdout_bytes,
            stderr_bytes=capture.stderr_bytes,
            output_complete=output_complete,
            duration_ms=duration_ms,
            timed_out=status is ExecutionStatus.TIMED_OUT,
            oom_killed=oom_killed,
            image=self.image,
            image_id=image_id,
            limits=limits,
            cleaned_up=cleaned_up,
        )
        log.info(
            "sandbox_run",
            extra={
                "run_id": run_id,
                "status": status,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "cleaned_up": cleaned_up,
            },
        )
        return result

    @staticmethod
    def _kill(container: Container) -> None:
        try:
            container.kill()
        except docker.errors.APIError as exc:
            # 409: container already exited between the deadline and the kill.
            if exc.status_code != 409:
                raise

    @staticmethod
    def _remove(container: Container) -> bool:
        try:
            container.remove(force=True, v=True)
        except docker.errors.NotFound:
            return True
        except (docker.errors.DockerException, requests.exceptions.RequestException):
            log.exception("sandbox_cleanup_failed", extra={"container": container.name})
            return False
        return True
