"""Resolve which Docker daemon to talk to.

docker-py only reads ``DOCKER_HOST``; it ignores the Docker CLI's *contexts*, which is how
Colima, OrbStack and Docker Desktop usually expose their sockets. Resolution order:

1. Explicit setting (``MOODY_DOCKER_HOST``)
2. ``DOCKER_HOST`` environment variable
3. Endpoint of the active Docker CLI context (``docker context inspect``)
4. docker-py default (``unix:///var/run/docker.sock``)
"""

from __future__ import annotations

import os
import shutil
import subprocess

DEFAULT_DOCKER_HOST = "unix:///var/run/docker.sock"


def _context_endpoint() -> str | None:
    docker_cli = shutil.which("docker")
    if docker_cli is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, resolved binary
            [docker_cli, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    endpoint = proc.stdout.strip()
    return endpoint if proc.returncode == 0 and endpoint else None


def resolve_docker_host(explicit: str | None = None) -> tuple[str, str]:
    """Return ``(host, source)`` where source explains where the value came from."""
    if explicit:
        return explicit, "MOODY_DOCKER_HOST"
    if env := os.environ.get("DOCKER_HOST"):
        return env, "DOCKER_HOST"
    if ctx := _context_endpoint():
        return ctx, "docker context"
    return DEFAULT_DOCKER_HOST, "default"
