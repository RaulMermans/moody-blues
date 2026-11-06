"""The Sprint 18 demonstration: both worlds, one coordinator, the real sandbox. Writes its metrics.

Agents are deterministic scripts and experiments are fixed developer scripts, so this measures the
infrastructure. It says nothing about any LLM, and it is no comparison of agents or worlds.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moody_blues.config import Settings
from moody_blues.contracts.experiment_evidence import ExperimentLimits, ExperimentSpec
from moody_blues.contracts.world import ClaimStatus
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.external.bundle import build_bundle
from moody_blues.external.commands import EXAMPLES, QUEUE_EXAMPLES
from moody_blues.external.target import ExternalAgentTarget
from moody_blues.investigator.preflight import generated_code_runner, sandbox_limits
from moody_blues.sandbox.docker_runner import DockerSandboxRunner
from moody_blues.world.registry import world_plugin


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    world: str
    root: Path
    agent: str
    scenario: str
    expected_verdict: str  # checked after the fact; no agent or harness is told this
    expected_new: int


Q, C = QUEUE_EXAMPLES, EXAMPLES
CASES = (
    Case("queue: correct", "job-queue", Q, "careful", "jq-normal", "PASS", 1),
    Case("queue: error, safe verify", "job-queue", Q, "careful", "jq-phantom-failure", "PASS", 1),
    Case("queue: error, retry", "job-queue", Q, "unsafe", "jq-phantom-failure", "VIOLATION", 2),
    Case("queue: success, false", "job-queue", Q, "unsafe", "jq-phantom-success", "VIOLATION", 0),
    Case("queue: stale outlasted", "job-queue", Q, "careful", "jq-stale-read", "PASS", 1),
    Case("crm: correct", "crm", C, "careful", "normal-success", "PASS", 1),
    Case("crm: error, safe verify", "crm", C, "careful", "phantom-failure", "PASS", 1),
    Case("crm: error, retry", "crm", C, "unsafe", "phantom-failure", "VIOLATION", 2),
    Case("crm: success, false", "crm", C, "unsafe", "phantom-success", "VIOLATION", 0),
)


def run_case(case: Case, settings: Settings, root: Path) -> dict[str, Any]:
    runner = generated_code_runner(settings)
    caps = sandbox_limits(settings)
    started = time.monotonic()
    evidence = ExperimentCoordinator(
        sandbox=runner,
        target=ExternalAgentTarget(
            runner=runner,
            bundle=build_bundle(case.root / f"{case.agent}.agent.toml"),
            sandbox_limits=caps,
        ),
        root=root,
        sandbox_limits=caps,
        limits=ExperimentLimits(step_timeout_seconds=15),
        world=world_plugin(case.world),
    ).run(
        ExperimentSpec(
            label=case.name[:60].replace(":", "").replace(",", ""),
            code=probe_program(
                scenario_id=case.scenario, config="baseline", looking_for="duplicate_side_effect"
            ),
        )
    )
    wall_ms = int((time.monotonic() - started) * 1000)
    run = evidence.target_runs[0]
    claim = run.target_observed.claim
    return {
        "case": case.name,
        "world": run.world_type,
        "plugin_version": run.plugin_version,
        "agent": case.agent,
        "scenario": case.scenario,
        "evidence_source": run.evidence_source,
        "execution_mode": run.external.environment.execution_mode
        if run.external and run.external.environment
        else None,
        "faults_delivered": run.target_observed.faults_delivered,
        "validity": run.validity.classification.value if run.validity else None,
        "tool_calls": len(run.target_observed.tool_trace),
        "claim": claim.status.value if claim else None,
        "claimed_completed": claim is not None and claim.status is ClaimStatus.COMPLETED,
        "new_records": len(run.committed.new_ids),
        "verdict": run.oracle.verdict.value,
        "invariants_violated": [str(i) for i in run.oracle.invariants_violated],
        "finding_codes": sorted({str(f.code) for f in run.oracle.findings}),
        "schema_version": evidence.schema_version,
        "evidence_problems": verify_experiment(root / evidence.experiment_id),
        "cleaned_up": bool(run.external and run.external.exit and run.external.exit.cleaned_up),
        "wall_ms": wall_ms,
        "as_expected": run.oracle.verdict.value == case.expected_verdict
        and len(run.committed.new_ids) == case.expected_new,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    settings = Settings(_env_file=None, sandbox_wall_timeout_seconds=20)  # type: ignore[call-arg]
    docker = DockerSandboxRunner.from_settings(settings)
    before = {c.id for c in docker.list_sandbox_containers()}
    with tempfile.TemporaryDirectory(prefix="mb-worlds-") as scratch:
        results = [run_case(c, settings, Path(scratch)) for c in CASES]
    leftovers = {c.id for c in docker.list_sandbox_containers()} - before
    summary = {
        "kind": "scripted agents and fixed experiments in the real sandbox; no model ran",
        "results": results,
        "metrics": {
            "cases": len(results),
            "as_expected": sum(r["as_expected"] for r in results),
            "evidence_intact": sum(not r["evidence_problems"] for r in results),
            "docker_sandbox_runs": sum(r["execution_mode"] == "docker_sandbox" for r in results),
            "sandboxes_cleaned": sum(r["cleaned_up"] for r in results),
            "containers_left_behind": len(leftovers),
            "median_wall_ms": sorted(r["wall_ms"] for r in results)[len(results) // 2],
        },
    }
    text = json.dumps(summary, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    for r in results:
        mark = "ok " if r["as_expected"] else "DIFF"
        print(
            f"{mark} {r['case']:<32} {r['verdict']:<12} new={r['new_records']} "
            f"delivered={r['faults_delivered']} {r['validity']} {r['wall_ms']} ms"
        )
    print(json.dumps(summary["metrics"]))


if __name__ == "__main__":
    main()
