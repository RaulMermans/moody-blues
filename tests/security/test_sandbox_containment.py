"""Verify the configured sandbox restrictions are actually in effect inside the container.

These observe *configured* restrictions; they do not prove the absence of kernel or
runtime escapes. All probes are read-only or self-contained and non-destructive.
"""

from __future__ import annotations

import pytest

from moody_blues.contracts.sandbox import SandboxRequest, SandboxResult
from moody_blues.sandbox.docker_runner import DockerSandboxRunner

pytestmark = pytest.mark.docker


def _run(runner: DockerSandboxRunner, code: str) -> SandboxResult:
    r = runner.run(SandboxRequest(code=code))
    assert r.cleaned_up
    return r


def test_runs_as_unprivileged_user(docker_runner: DockerSandboxRunner) -> None:
    r = _run(docker_runner, "import os; print(os.getuid(), os.getgid(), os.geteuid())")
    assert r.stdout.split() == ["65534", "65534", "65534"]


def test_no_capabilities_and_no_new_privs(docker_runner: DockerSandboxRunner) -> None:
    r = _run(docker_runner, "print(open('/proc/self/status').read())")
    fields = dict(line.split(":\t", 1) for line in r.stdout.splitlines() if ":\t" in line)
    assert int(fields["CapEff"].strip(), 16) == 0
    assert int(fields["CapPrm"].strip(), 16) == 0
    assert int(fields["CapBnd"].strip(), 16) == 0
    assert fields["NoNewPrivs"].strip() == "1"


def test_network_is_disabled(docker_runner: DockerSandboxRunner) -> None:
    code = """
import socket
ifaces = [name for _, name in socket.if_nameindex()]
print("ifaces", ifaces)
for host, port in [("1.1.1.1", 53), ("8.8.8.8", 443)]:
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((host, port)); print("CONNECTED", host)
    except OSError as e:
        print("blocked", host, type(e).__name__)
    finally:
        s.close()
"""
    r = _run(docker_runner, code)
    assert "CONNECTED" not in r.stdout
    assert "ifaces ['lo']" in r.stdout


def test_root_filesystem_is_read_only(docker_runner: DockerSandboxRunner) -> None:
    code = """
for path in ["/usr/local/lib/probe", "/probe", "/etc/probe"]:
    try:
        open(path, "w").write("x"); print("WROTE", path)
    except OSError as e:
        print("denied", path, e.errno)
"""
    r = _run(docker_runner, code)
    assert "WROTE" not in r.stdout
    assert r.stdout.count("denied") == 3


def test_tmp_is_writable_but_noexec(docker_runner: DockerSandboxRunner) -> None:
    code = """
import os, subprocess
p = "/tmp/probe.sh"
open(p, "w").write("#!/bin/sh\\necho EXECUTED\\n"); os.chmod(p, 0o755)
print("written")
try:
    print(subprocess.run([p], capture_output=True, text=True).stdout)
except PermissionError as e:
    print("noexec", e.errno)
"""
    r = _run(docker_runner, code)
    assert "written" in r.stdout
    assert "EXECUTED" not in r.stdout
    assert "noexec" in r.stdout


def test_host_environment_not_leaked(
    docker_runner: DockerSandboxRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    canary = "moody-canary-6f1c2e"
    monkeypatch.setenv("MOODY_VULTR_API_KEY", canary)
    monkeypatch.setenv("CANARY_SECRET", canary)
    r = _run(docker_runner, "import os; print(dict(os.environ))")
    assert canary not in r.stdout
    assert "VULTR" not in r.stdout


def test_docker_socket_and_host_mounts_absent(docker_runner: DockerSandboxRunner) -> None:
    code = """
import os
for p in ["/var/run/docker.sock", "/run/docker.sock"]:
    print(p, os.path.exists(p))
print(open("/proc/self/mountinfo").read())
"""
    r = _run(docker_runner, code)
    assert "docker.sock True" not in r.stdout
    assert "docker.sock" not in r.stdout.split("\n", 2)[2]
    mount_points = {line.split()[4] for line in r.stdout.splitlines() if line.count(" ") > 5}
    # No bind mounts beyond what Docker always provides.
    allowed = {
        "/",
        "/tmp",
        "/proc",
        "/dev",
        "/sys",
        "/etc/resolv.conf",
        "/etc/hostname",
        "/etc/hosts",
    }
    unexpected = {
        m for m in mount_points if not any(m == a or m.startswith(a + "/") for a in allowed)
    }
    assert unexpected == set(), unexpected
