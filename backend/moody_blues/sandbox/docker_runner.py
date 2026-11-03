"""Disposable-container sandbox backed by a local Docker daemon.

Implemented restrictions (per run):
  * fresh container, removed (with anonymous volumes) in ``finally``
  * ``network_mode=none`` unless the request explicitly enables networking
  * unprivileged uid/gid 65534 (nobody), ``cap_drop=ALL``, ``no-new-privileges``
  * read-only root filesystem; only a small ``noexec`` tmpfs at /tmp
  * memory (swap disabled), CPU quota and PID limits
  * no host mounts, no Docker socket, no host environment variables
  * bounded log capture (driver max-size + in-process truncation)
  * wall-clock timeout enforced by the host, followed by SIGKILL

These are *configured restrictions*. Containment guarantees ultimately depend on the
host kernel, the container runtime and its seccomp/AppArmor profiles; see
docs/architecture/overview.md#sandbox-threat-model.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

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
SANDBOX_UID = "65534:65534"


def _truncate(data: bytes, limit: int) -> tuple[str, bool]:
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace"), False
    return data[:limit].decode("utf-8", errors="replace"), True


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

    def list_sandbox_containers(self) -> list[Container]:
        """All containers (any state) created by this runner. Used to verify cleanup."""
        return self._docker().containers.list(all=True, filters={"label": SANDBOX_LABEL})

    # -- execution ----------------------------------------------------------------

    def _container_config(self, run_id: str, code: str, limits: SandboxLimits) -> dict[str, Any]:
        memory = f"{limits.memory_mb}m"
        return {
            "image": self.image,
            "command": ["python", "-I", "-c", code],
            "name": f"moody-sbx-{run_id}",
            "labels": {SANDBOX_LABEL: "true", RUN_ID_LABEL: run_id},
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

    def run(self, request: SandboxRequest) -> SandboxResult:
        limits = request.limits or self.default_limits
        run_id = f"sbx_{uuid.uuid4().hex[:16]}"
        self.ensure_image()
        client = self._docker()

        container: Container | None = None
        timed_out = False
        started = time.perf_counter()
        try:
            container = client.containers.create(
                **self._container_config(run_id, request.code, limits)
            )
            container.start()
            try:
                container.wait(timeout=limits.wall_timeout_seconds)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                # docker-py surfaces the wait deadline as a client-side read timeout.
                timed_out = True
                self._kill(container)
                container.wait(timeout=self._api_timeout)
            duration_ms = int((time.perf_counter() - started) * 1000)

            container.reload()
            state: dict[str, Any] = container.attrs["State"]
            exit_code = int(state["ExitCode"])
            oom_killed = bool(state.get("OOMKilled", False))
            stdout, out_trunc = _truncate(
                container.logs(stdout=True, stderr=False), self.output_limit_bytes
            )
            stderr, err_trunc = _truncate(
                container.logs(stdout=False, stderr=True), self.output_limit_bytes
            )
        except (docker.errors.DockerException, requests.exceptions.RequestException) as exc:
            raise SandboxError(
                ErrorCategory.SANDBOX_RUNTIME, f"sandbox run {run_id} failed: {exc}"
            ) from exc
        finally:
            cleaned_up = self._remove(container) if container is not None else True

        if timed_out:
            status = ExecutionStatus.TIMED_OUT
        elif exit_code == 0:
            status = ExecutionStatus.SUCCEEDED
        else:
            status = ExecutionStatus.FAILED

        result = SandboxResult(
            run_id=run_id,
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=out_trunc,
            stderr_truncated=err_trunc,
            duration_ms=duration_ms,
            timed_out=timed_out,
            oom_killed=oom_killed,
            image=self.image,
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
