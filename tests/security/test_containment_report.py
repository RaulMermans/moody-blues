"""The containment report on real Docker. On a developer machine it must say it is local."""

from __future__ import annotations

import os

import pytest

from moody_blues.explorer.containment import report_hash, run_containment
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from tests.conftest import make_settings

pytestmark = pytest.mark.docker


def test_every_attempt_holds_on_this_host_and_is_labeled_local(
    docker_runner: DockerSandboxRunner,
) -> None:
    report = run_containment(
        make_settings(), git_commit=None, known_secrets=("a-configured-secret",)
    )

    assert report.status == "PASS", [a for a in report.attempts if not a.held]
    assert {a.attempt_id for a in report.attempts} == {
        "network_egress",
        "protected_filesystem_write",
        "memory_exhaustion",
        "process_flood",
        "wall_clock_timeout",
        "unauthorized_action",
        "secret_disclosure",
        "protected_oracle_and_crm_state",
    }
    assert all(a.cleaned_up and a.host_unaffected for a in report.attempts)
    assert report.leftover_containers == 0
    assert report.host.environment == "local_development"
    assert report.sha256 == report_hash(report)
    assert "MOODY_CONTAINMENT_CANARY" not in os.environ
    assert "a-configured-secret" not in report.model_dump_json()
