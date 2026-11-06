"""Real local inference, end to end. ``make local-eval``. Not a test: nothing here is offline.

A real model on this machine drives the agent and, in the second part, writes the investigation.
PASS, VIOLATION, INCONCLUSIVE and a bounded failure are all results, so none of them fails this. A
check fails only when the evidence does not show what it must: that a model really answered, that
the Oracle read state, that nothing paid was touched, and that nothing was left behind.

It compares nothing. ``NO_DEMONSTRATED_ADVANTAGE`` stands, and these runs are too few to say
anything about a rate. Repeats at temperature 0 are repetitions, not independent samples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from typing import Any

import httpx2

from moody_blues.config import Settings, get_settings
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.inference import ChatMessage, InferenceRequest
from moody_blues.contracts.investigation import (
    InvestigationReport,
    TargetKind,
)
from moody_blues.explorer.paths import REPO_ROOT, artifacts_dir
from moody_blues.external import commands
from moody_blues.external.bundle import build_bundle
from moody_blues.external.local import (
    LOCAL_ADAPTER_LIMITS,
    LOCAL_INVESTIGATION_LIMITS,
    LocalSession,
    open_local,
)
from moody_blues.external.selection import external_provenance
from moody_blues.external.target import LiveInference
from moody_blues.investigator.preflight import generated_code_runner, run_preflight
from moody_blues.investigator.workspace import verify_investigation

SCENARIOS = (
    ("A", "none"),
    ("B", "phantom_failure"),
    ("C", "phantom_success"),
    ("A", "none"),
    ("B", "phantom_failure"),
    ("C", "phantom_success"),
)
INVESTIGATION_WORLDS = ("normal-success", "phantom-failure")
CANONICAL_LEDGERS = REPO_ROOT / ".artifacts" / "live-spend"


@dataclass(slots=True)
class MemorySampler:
    """Peak resident memory of Ollama's processes. Sampled, so a brief peak can be missed."""

    peak_kb: int = 0
    _stop: Event = field(default_factory=Event)
    _thread: Thread | None = None

    def _sample(self) -> int:
        out = subprocess.run(
            ["/bin/ps", "-axo", "rss=,comm="], capture_output=True, text=True, check=True
        ).stdout
        return sum(int(line.split()[0]) for line in out.splitlines() if "ollama" in line)

    def _loop(self) -> None:
        while not self._stop.wait(0.5):
            self.peak_kb = max(self.peak_kb, self._sample())

    def start(self) -> None:
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


def _ledger_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(CANONICAL_LEDGERS.rglob("*")) if CANONICAL_LEDGERS.exists() else []:
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


def _cold_load(session: LocalSession) -> dict[str, Any]:
    """Unload the model, then time one tiny generation: the real startup cost."""
    httpx2.post(
        f"{session.client.base_url}/api/generate",
        json={"model": session.identity.model, "keep_alive": 0},
        timeout=30,
    )
    time.sleep(2)
    started = time.perf_counter()
    result = session.client.complete(
        InferenceRequest(messages=[ChatMessage(role="user", content="Say: ready")], max_tokens=16)
    )
    return {
        "wall_ms": int((time.perf_counter() - started) * 1000),
        "load_ms": result.timings.load_ms if result.timings else None,
    }


def _run_view(run: TargetRunEvidence, experiment_dir: Path) -> dict[str, Any]:
    report = json.loads((experiment_dir / run.report_path).read_text("utf-8"))
    agent = report["agent"]
    record = run.external
    assert record is not None
    return {
        "run_id": run.run_id,
        "evidence_source": run.evidence_source,
        "provider": run.provider,
        "requested_model": run.requested_model,
        "reported_models": run.reported_models,
        "sandbox": record.environment.execution_mode if record.environment else None,
        "network_enabled": record.environment.network_enabled if record.environment else None,
        "faults_selected": [f.kind.value for f in run.authorized.faults],
        "faults_delivered": run.target_observed.faults_delivered,
        "termination": run.target_observed.termination,
        "claim": run.target_observed.claim.model_dump(mode="json")
        if run.target_observed.claim
        else None,
        "oracle_verdict": run.oracle.verdict.value,
        "oracle_findings": [f.code.value for f in run.oracle.findings],
        "run_outcome": run.run_outcome,
        "committed_new": [c for c in run.committed.new_customer_ids],
        "tool_calls": [
            {"name": c["name"], "disposition": c["disposition"], "arguments": c["arguments_json"]}
            for c in agent["tool_calls"]
        ],
        "model_steps": [
            {
                "index": s["index"],
                "finish_reason": s["finish_reason"],
                "content": s["content"],
                "tool_call_ids": s["tool_call_ids"],
            }
            for s in agent["steps"]
        ],
        "model_requests": [r.model_dump(mode="json") for r in record.model_requests],
        "report_sha256": run.report_sha256,
        "transcript_sha256": record.transcript_sha256,
        "wall_ms": run.wall_ms,
    }


def _evidence(
    report: InvestigationReport, artifacts: Path
) -> list[tuple[ExperimentEvidence, Path]]:
    found: list[tuple[ExperimentEvidence, Path]] = []
    for ref in report.experiments:
        directory = artifacts / "experiments" / ref.experiment_id
        text = (directory / "evidence.json").read_text("utf-8")
        found.append((ExperimentEvidence.model_validate_json(text), directory))
    return found


def _investigation_view(report: InvestigationReport, artifacts: Path) -> dict[str, Any]:
    directory = artifacts / "investigations" / report.investigation_id
    programs: list[dict[str, Any]] = []
    for call in sorted((directory / "calls").glob("call-*.json")):
        artifact = json.loads(call.read_text("utf-8"))
        response = json.loads(artifact.get("response") or "{}")
        programs.append(
            {
                "call": call.name,
                "content": response.get("content"),
                "tool_calls": response.get("tool_calls"),
            }
        )
    return {
        "investigation_id": report.investigation_id,
        "world": report.request.world_ids[0],
        "state": report.state.value,
        "termination": report.termination,
        "model_evidence_source": report.model_evidence_source,
        "investigator_identity": report.request.investigator_identity.model_dump(mode="json")
        if report.request.investigator_identity
        else None,
        "hypotheses": [h.model_dump(mode="json") for h in report.hypotheses],
        "proposals": [p.model_dump(mode="json") for p in report.proposals],
        "decisions": [d.model_dump(mode="json") for d in report.decisions],
        "model_calls": [c.model_dump(mode="json") for c in report.model_calls],
        "model_answers": programs,
        "model_conclusion": report.model_conclusion.model_dump(mode="json")
        if report.model_conclusion
        else None,
        "findings": [f.model_dump(mode="json") for f in report.findings],
        "claim_checks": [c.model_dump(mode="json") for c in report.claim_checks],
        "statement": report.statement,
        "usage": report.usage.model_dump(mode="json"),
        "runs": [_run_view(r, d) for e, d in _evidence(report, artifacts) for r in e.target_runs],
        "evidence_problems": verify_investigation(directory, artifacts / "experiments"),
    }


def _investigate(
    settings: Settings, session: LocalSession, manifest: Path, world: str, artifacts: Path
) -> tuple[InvestigationReport, str]:
    bundle = build_bundle(manifest)
    broker = session.broker()
    limits = LOCAL_INVESTIGATION_LIMITS
    report = commands.external_workflow(
        settings,
        bundle,
        artifacts=artifacts,
        world=world,
        live=LiveInference(broker=broker, ledger=None),
        provenance=external_provenance(TargetKind.EXTERNAL_LLM, bundle, broker),
        investigator=session.investigator(limits),
        investigator_identity=session.identity,
        limits=limits,
        adapter_limits=LOCAL_ADAPTER_LIMITS,
    ).run()
    return report, commands.publish_run(report, artifacts, settings)


def _checks(
    runs: list[dict[str, Any]], investigations: list[dict[str, Any]], leftovers: int, ledgers: bool
) -> dict[str, bool]:
    every = runs + [r for i in investigations for r in i["runs"]]
    requests = [q for r in every for q in r["model_requests"]]
    proposed: list[dict[str, Any]] = []
    for investigation in investigations:
        for answer in investigation["model_answers"]:
            calls: list[dict[str, Any]] = answer["tool_calls"] or []
            proposed.extend(c for c in calls if c["name"] == "propose_experiment")
    return {
        "every_run_is_labeled_local": all(r["evidence_source"] == "local_ollama" for r in every),
        "every_run_used_the_sandbox_with_no_network": all(
            r["sandbox"] == "docker_sandbox" and r["network_enabled"] is False for r in every
        ),
        "model_calls_were_brokered": bool(requests)
        and all(q["provider"] == "ollama" and q["request_id"] for q in requests),
        "reported_model_matches_approved": all(
            q["reported_model"] == q["model"] for q in requests if q["status"] == "completed"
        ),
        "a_model_decided_a_tool_call": any(r["tool_calls"] for r in runs),
        "every_run_has_an_oracle_verdict": all(r["oracle_verdict"] for r in every),
        "hypotheses_came_from_model_answers": bool(proposed)
        and all(i["hypotheses"] for i in investigations),
        "experiments_ran_through_the_coordinator": all(i["runs"] for i in investigations),
        "investigator_records_identity": all(i["investigator_identity"] for i in investigations),
        "evidence_is_intact": all(not i["evidence_problems"] for i in investigations),
        "no_sandbox_left_behind": leftovers == 0,
        "paid_ledger_unchanged": ledgers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    artifacts = artifacts_dir(settings)
    if artifacts.resolve() == (REPO_ROOT / ".artifacts").resolve():
        print("set MOODY_ARTIFACTS_DIR: this must not write to the canonical artifacts")
        return 2
    session = open_local(settings)
    if session is None:
        return 2
    if run_preflight(settings).status != "PASS":
        print("the sandbox preflight did not pass")
        return 2
    runner = generated_code_runner(settings)
    before = {c.id for c in runner.list_sandbox_containers()}
    ledger_before = _ledger_digest()
    sampler = MemorySampler()
    sampler.start()
    started = time.perf_counter()
    cold = _cold_load(session)
    bundle = build_bundle(args.manifest)

    runs: list[dict[str, Any]] = []
    for label, fault in SCENARIOS:
        report, _ = commands._run_local(  # pyright: ignore[reportPrivateUsage]
            settings, bundle, "normal-success", session, fault
        )
        commands.publish_run(report, artifacts, settings)
        for evidence, directory in _evidence(report, artifacts):
            for run in evidence.target_runs:
                runs.append({"scenario": label, "fault": fault} | _run_view(run, directory))
        print(f"{label} {fault}: {runs[-1]['oracle_verdict']} ({runs[-1]['run_outcome']})")

    investigations: list[dict[str, Any]] = []
    for world in INVESTIGATION_WORLDS:
        report, job = _investigate(settings, session, args.manifest, world, artifacts)
        investigations.append({"job_id": job} | _investigation_view(report, artifacts))
        print(f"investigation {world}: {report.state.value}, {report.statement}")

    sampler.stop()
    leftovers = len({c.id for c in runner.list_sandbox_containers()} - before)
    every = runs + [r for i in investigations for r in i["runs"]]
    agent_calls = [q for r in every for q in r["model_requests"] if q.get("timings")]
    tokens = sum(q["completion_tokens"] or 0 for q in agent_calls)
    generating = sum(q["timings"]["generation_ms"] for q in agent_calls)
    investigator_calls = [c for i in investigations for c in i["model_calls"]]
    checks = _checks(runs, investigations, leftovers, ledger_before == _ledger_digest())
    results = {
        "kind": "real local model; not a comparison; not evidence of any rate",
        "identity": session.identity.model_dump(mode="json"),
        "agent_bundle_sha256": bundle.sha256,
        "performance": {
            "cold_load": cold,
            "agent_model_calls": len(agent_calls),
            "agent_tokens_out": tokens,
            "agent_generation_ms": generating,
            "agent_tokens_per_second": round(tokens / generating * 1000, 1) if generating else None,
            "agent_call_latency_ms": sorted(q["latency_ms"] or 0 for q in agent_calls),
            "investigator_model_calls": len(investigator_calls),
            "investigator_call_latency_ms": sorted(c["latency_ms"] for c in investigator_calls),
            "tool_calls": sum(len(r["tool_calls"]) for r in every),
            "experiments": sum(len(i["runs"]) for i in investigations) + len(runs),
            "run_wall_ms": sorted(r["wall_ms"] for r in every),
            "peak_ollama_rss_mb": sampler.peak_kb // 1024,
            "total_wall_seconds": round(time.perf_counter() - started, 1),
        },
        "scenarios": runs,
        "investigations": investigations,
        "checks": checks,
    }
    text = json.dumps(results, indent=1, default=str) + "\n"
    out = args.out or artifacts / "local-eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, "utf-8")
    print(json.dumps({"checks": checks, "performance": results["performance"]}, indent=1))
    print(f"wrote {out}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
