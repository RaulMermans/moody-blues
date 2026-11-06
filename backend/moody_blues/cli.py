"""Developer CLI: ``uv run moody-blues <command>``.

Commands:
  doctor        Check local prerequisites and configuration (no chargeable calls).
  docker-smoke  Run the fixed smoke program in a real disposable container.
  vultr-smoke   LIVE: basic inference + tool calling against Vultr (chargeable).
  vultr-models  LIVE: list models visible to the configured key.
  world-demo    Run the reference World Engine cases against real SQLite worlds.
  world-run     Run one scenario with one deterministic reference executor.
  agent-run     LIVE: one LLM Target Agent run against one scenario (chargeable).
  agent-eval    LIVE: bounded scenarios x configs x trials evaluation (chargeable; needs
                --confirm-billable).
  experiment-demo     Real sandbox + coordinator + world + Oracle with reference executors.
  experiment-live     LIVE: one sandboxed experiment driving the real Target Agent (chargeable;
                      needs --confirm-billable).
  experiment-recover  Remove orphan sandboxes; close experiments whose coordinator died.
  live-budget   Show the application-side spend ledger (no calls).
  investigator-preflight  Verify the generated-code sandbox on this host (free).
  investigator-demo       Fixture model, real sandboxes and worlds (free).
  investigator-live       One live investigation (chargeable; --confirm-billable).
  investigator-eval       Paired tests and strategy comparison (chargeable; --confirm-billable).
  recorded-export         Rebuild the curated recorded investigations from local records (free).
  recorded-verify         Check the recorded investigations against manifest and source (free).
  containment-report      Attempt harmless escapes on this host and write the evidence (free).
  ledger-verify           Print the ledger's hash and totals, or fail if it is corrupt (free).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from moody_blues.config import Settings
from moody_blues.contracts.sandbox import SandboxLimits, SandboxRequest
from moody_blues.explorer.paths import default_artifacts
from moody_blues.inference import smoke as vultr_smoke
from moody_blues.sandbox.base import SandboxError
from moody_blues.sandbox.docker_runner import DockerSandboxRunner

if TYPE_CHECKING:
    from moody_blues.contracts.agent import AgentBudget, AgentRunReport, TokenTotals
    from moody_blues.contracts.common import ErrorDetail
    from moody_blues.experiments.budget import SpendLedger
    from moody_blues.inference.vultr import VultrInferenceClient

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = default_artifacts()

OK, WARN, FAIL = "PASS", "WARN", "FAIL"

# Generous bound for the fixed smoke checks, which use about 800 tokens in total.
SMOKE_MAX_TOKENS = 4_000


def _version(cmd: Sequence[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0] if out.returncode == 0 and text else None


def doctor(settings: Settings) -> int:
    rows: list[tuple[str, str, str]] = []

    def check(name: str, status: str, detail: str) -> None:
        rows.append((status, name, detail))

    py = sys.version_info
    check(
        "python",
        OK if py >= (3, 12) else FAIL,
        f"{platform.python_version()} (>=3.12 required)",
    )
    for tool, args, required in [
        ("uv", ["uv", "--version"], True),
        ("node", ["node", "--version"], True),
        ("pnpm", ["pnpm", "--version"], True),
        ("docker-cli", ["docker", "--version"], True),
        ("git", ["git", "--version"], False),
    ]:
        v = _version(args)
        check(tool, OK if v else (FAIL if required else WARN), v or "not found on PATH")

    node_v = _version(["node", "--version"])
    if node_v and int(node_v.lstrip("v").split(".")[0]) < 20:
        check("node-version", FAIL, f"{node_v} (>=20 required by Next.js)")

    runner = DockerSandboxRunner.from_settings(settings)
    try:
        runner.ping()
        check(
            "docker-daemon",
            OK,
            f"reachable at {runner.docker_host} (via {runner.docker_host_source})",
        )
        try:
            runner._docker().images.get(settings.sandbox_image)  # pyright: ignore[reportPrivateUsage]
            check("sandbox-image", OK, f"{settings.sandbox_image} present")
        except Exception:  # noqa: BLE001 - diagnostic only, reported as WARN
            check("sandbox-image", WARN, f"{settings.sandbox_image} not pulled (auto-pulled)")
        leftovers = runner.list_sandbox_containers()
        check(
            "sandbox-cleanup",
            OK if not leftovers else WARN,
            f"{len(leftovers)} leftover sandbox containers",
        )
    except SandboxError as exc:
        check("docker-daemon", FAIL, exc.detail.message)

    fe = REPO_ROOT / "frontend"
    check(
        "frontend-deps",
        OK if (fe / "node_modules").is_dir() else WARN,
        "installed" if (fe / "node_modules").is_dir() else "run `make setup`",
    )
    pw = _version(["pnpm", "--dir", str(fe), "exec", "playwright", "--version"])
    check("playwright", OK if pw else WARN, pw or "not installed (`make setup`)")

    env_file = REPO_ROOT / ".env"
    check(
        "env-file",
        OK if env_file.exists() else WARN,
        ".env present" if env_file.exists() else "no .env (defaults used; see .env.example)",
    )
    if settings.vultr_configured:
        check(
            "vultr-config",
            OK,
            f"key set, model={settings.vultr_model}, base={settings.vultr_base_url} "
            "-- NOT live-verified; run `make vultr-smoke`",
        )
    else:
        check("vultr-config", WARN, "BLOCKED_BY_CREDENTIALS: MOODY_VULTR_API_KEY not set")

    width = max(len(n) for _, n, _ in rows)
    for status, name, detail in rows:
        print(f"[{status:<4}] {name:<{width}}  {detail}")
    failed = [n for s, n, _ in rows if s == FAIL]
    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'All required checks passed.'}")
    return 1 if failed else 0


def docker_smoke(settings: Settings) -> int:
    from moody_blues.api.routes.sandbox import SMOKE_PROGRAM

    runner = DockerSandboxRunner.from_settings(settings)
    try:
        result = runner.run(SandboxRequest(code=SMOKE_PROGRAM))
    except SandboxError as exc:
        print(json.dumps({"status": "BLOCKED_BY_LOCAL_DEPENDENCY", "error": exc.detail.message}))
        return 2
    print(result.model_dump_json(indent=2))
    return 0 if result.exit_code == 0 and result.cleaned_up else 1


def _ledger(settings: Settings) -> SpendLedger:
    from moody_blues.experiments.budget import SpendLedger as Ledger
    from moody_blues.experiments.budget import ledger_path

    return Ledger.from_settings(settings, ledger_path(settings, ARTIFACTS))


def _budget_blocked(message: str) -> int:
    print(json.dumps({"status": "BLOCKED_BY_BUDGET", "reason": message}, indent=2))
    return 3


def _smoke_tokens(report: dict[str, Any]) -> TokenTotals:
    """Sum provider-reported usage over a smoke report; incomplete if any call lacks it."""
    from moody_blues.contracts.agent import TokenTotals as Totals
    from moody_blues.contracts.inference import InferenceResult

    prompt = completion = total = 0
    complete = True
    checks = cast(dict[str, dict[str, Any]], report["checks"])
    for check in checks.values():
        if "error" in check:
            complete = False  # a failed call may still have been billed
        for key in ("result", "first", "second"):
            if key not in check:
                continue
            usage = InferenceResult.model_validate(check[key]).usage
            if usage is None or usage.total_tokens is None:
                complete = False
                continue
            prompt += usage.prompt_tokens or 0
            completion += usage.completion_tokens or 0
            total += usage.total_tokens
    return Totals(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=total, complete=complete
    )


def _vultr(settings: Settings, checks: list[str], artifact: str) -> int:
    from moody_blues.experiments.budget import BudgetExceededError

    billable = settings.vultr_configured and any(c in vultr_smoke.CHECKS for c in checks)
    entry = None
    if billable:
        try:
            entry = _ledger(settings).reserve("vultr-smoke", worst_case_tokens=SMOKE_MAX_TOKENS)
        except BudgetExceededError as exc:
            return _budget_blocked(exc.detail.message)
    code, report = vultr_smoke.run(checks, settings)
    if entry is not None:
        _ledger(settings).settle(entry, _smoke_tokens(report))
    text = vultr_smoke.render(report)
    print(text)
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / artifact).write_text(text + "\n")
    return code


def world_demo(case_ids: list[str] | None, *, keep: bool, color: bool) -> int:
    from moody_blues.services.world_demo import run_demo
    from moody_blues.services.world_runner import reference_case
    from moody_blues.world.reference import REFERENCE_CASES

    cases = [reference_case(c) for c in case_ids] if case_ids else list(REFERENCE_CASES)
    run_demo(cases, artifacts_dir=ARTIFACTS / "world-demo", keep_worlds=keep, color=color)
    return 0


def world_run(scenario_id: str, executor: str, *, as_json: bool, color: bool) -> int:
    from moody_blues.services.world_demo import render_report
    from moody_blues.services.world_runner import run_scenario
    from moody_blues.world.scenarios import load_scenario

    report = run_scenario(load_scenario(scenario_id), executor)
    if as_json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(render_report(report, color=color))
    return 0


def _agent_preflight(
    settings: Settings, model: str, artifact: Path
) -> tuple[int, VultrInferenceClient | None]:
    """Credentials, then the (unauthenticated, free) catalog. Returns (exit_code, client)."""
    from moody_blues.inference.vultr import InferenceError, VultrInferenceClient

    def blocked(
        code: int, status: str, reason: str, **extra: object
    ) -> tuple[int, VultrInferenceClient | None]:
        body = {"status": status, "reason": reason, "requested_model": model, **extra}
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(body, indent=2) + "\n")
        print(json.dumps(body, indent=2))
        return code, None

    if not settings.vultr_configured:
        return blocked(2, "BLOCKED_BY_CREDENTIALS", "MOODY_VULTR_API_KEY not set")
    client = VultrInferenceClient.from_settings(settings)
    try:
        catalog = client.list_models()
    except InferenceError as exc:
        return blocked(1, "FAIL", f"catalog unavailable: {exc.detail.message}")
    if model not in catalog:
        return blocked(1, "FAIL", "model not in the live catalog", catalog=catalog)
    return 0, client


def _auth_blocked(error: ErrorDetail | None) -> bool:
    from moody_blues.contracts.common import ErrorCategory

    return error is not None and error.category is ErrorCategory.PROVIDER_AUTH


def _budget(args: argparse.Namespace) -> AgentBudget:
    from moody_blues.contracts.agent import AgentBudget as Budget

    return Budget(
        max_steps=args.max_steps,
        max_tool_calls=args.max_tool_calls,
        max_total_tokens=args.max_run_tokens,
    )


def agent_run(settings: Settings, args: argparse.Namespace) -> int:
    from moody_blues.contracts.agent import AgentConfigName
    from moody_blues.experiments.budget import BudgetExceededError, worst_case_run_tokens
    from moody_blues.services.agent_render import render_agent_report
    from moody_blues.services.agent_world_runner import run_agent_scenario, write_report
    from moody_blues.world.scenarios import load_scenario

    model = args.model or settings.vultr_model
    out = ARTIFACTS / "agent-runs"
    code, client = _agent_preflight(settings, model, out / "preflight.json")
    if client is None:
        return code
    budget = _budget(args)
    ledger = _ledger(settings)
    try:
        entry = ledger.reserve(
            f"agent-run:{args.scenario}:{args.config}",
            worst_case_tokens=worst_case_run_tokens(budget),
        )
    except BudgetExceededError as exc:
        return _budget_blocked(exc.detail.message)
    report = run_agent_scenario(
        load_scenario(args.scenario),
        config=AgentConfigName(args.config),
        inference=client,
        evidence="live_provider",
        provider="vultr",
        model=model,
        budget=budget,
        price_per_million_tokens_usd=settings.vultr_price_per_million_tokens_usd,
        keep=False,
    )
    ledger.settle(entry, report.agent.tokens)
    path = write_report(report, out)
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(render_agent_report(report))
        print(f"\nrun report: {path}")
    if _auth_blocked(report.agent.error):
        print("BLOCKED_BY_CREDENTIALS: the provider rejected the API key (401)")
        return 2
    return 0


def agent_eval(settings: Settings, args: argparse.Namespace) -> int:
    from moody_blues.contracts.agent import AgentConfigName
    from moody_blues.contracts.agent import TokenTotals as Totals
    from moody_blues.experiments.budget import BudgetExceededError, worst_case_run_tokens
    from moody_blues.services.agent_eval import EVAL_SCENARIOS, EvalStatus, run_eval

    model = args.model or settings.vultr_model
    out = ARTIFACTS / "agent-eval" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    code, client = _agent_preflight(settings, model, out / "preflight.json")
    if client is None:
        return code
    budget = _budget(args)
    if not args.confirm_billable:
        print(
            json.dumps(
                {
                    "status": "NOT_RUN",
                    "reason": "agent-eval is a billable batch; pass --confirm-billable "
                    "(make agent-eval CONFIRM=1)",
                },
                indent=2,
            )
        )
        return 2
    ledger = _ledger(settings)
    try:
        entry = ledger.reserve(
            "agent-eval",
            worst_case_tokens=args.max_eval_tokens + worst_case_run_tokens(budget),
        )
    except BudgetExceededError as exc:
        return _budget_blocked(exc.detail.message)

    def progress(r: AgentRunReport) -> None:
        print(
            f"  {r.scenario_id:<24} {r.agent.config.value:<9} {r.assessment.outcome.value:<28}"
            f" {r.assessment.recovery.value:<20} steps={len(r.agent.steps)} "
            f"tokens={r.agent.tokens.total_tokens} {r.run_id}",
            flush=True,
        )

    summary, reports = run_eval(
        inference=client,
        evidence="live_provider",
        provider="vultr",
        model=model,
        out_dir=out,
        scenarios=args.scenario or [s.scenario_id for s in EVAL_SCENARIOS],
        configs=[AgentConfigName(c) for c in (args.config or [c.value for c in AgentConfigName])],
        trials=args.trials,
        budget=budget,
        max_eval_tokens=args.max_eval_tokens,
        price_per_million_tokens_usd=settings.vultr_price_per_million_tokens_usd,
        on_run=progress,
    )
    tokens = [r.agent.tokens for r in reports]
    ledger.settle(
        entry,
        Totals(
            prompt_tokens=sum(t.prompt_tokens for t in tokens),
            completion_tokens=sum(t.completion_tokens for t in tokens),
            total_tokens=sum(t.total_tokens for t in tokens),
            complete=all(t.complete for t in tokens),
        ),
    )
    print((out / "summary.md").read_text())
    print(f"evidence: {out}")
    return {
        EvalStatus.COMPLETED: 0,
        EvalStatus.PARTIAL_BUDGET: 0,
        EvalStatus.BLOCKED_BY_CREDENTIALS: 2,
        EvalStatus.ABORTED_PROVIDER: 1,
    }[summary.status]


def _experiment_root() -> Path:
    return ARTIFACTS / "experiments"


def _sandbox_limits(settings: Settings) -> SandboxLimits:
    return SandboxLimits(
        wall_timeout_seconds=settings.sandbox_wall_timeout_seconds,
        memory_mb=settings.sandbox_memory_mb,
        cpus=settings.sandbox_cpus,
        pids_limit=settings.sandbox_pids_limit,
    )


def _ready_sandbox(settings: Settings) -> DockerSandboxRunner | None:
    runner = DockerSandboxRunner.from_settings(settings)
    try:
        runner.ping()
        runner.ensure_image()
    except SandboxError as exc:
        print(json.dumps({"status": "BLOCKED_BY_LOCAL_DEPENDENCY", "error": exc.detail.message}))
        return None
    return runner


def experiment_demo(settings: Settings, case_ids: list[str] | None) -> int:
    from moody_blues.experiments.demo import DEMO_CASES, demo_case, render_evidence, run_case
    from moody_blues.experiments.recovery import verify_experiment

    runner = _ready_sandbox(settings)
    if runner is None:
        return 2
    root = _experiment_root()
    print(
        "Deterministic demonstration: real Docker sandboxes, real SQLite worlds, the real Oracle,"
    )
    print("and scripted reference executors in place of an LLM. No model is called.\n")
    failed: list[str] = []
    for case in [demo_case(c) for c in case_ids] if case_ids else list(DEMO_CASES):
        evidence = run_case(
            case, sandbox=runner, root=root, sandbox_limits=_sandbox_limits(settings)
        )
        print(render_evidence(evidence, title=case.title, root=root) + "\n")
        intact = not verify_experiment(root / evidence.experiment_id)
        if evidence.status is not case.expected_status or not intact:
            failed.append(case.case_id)
    print(f"FAILED: {', '.join(failed)}" if failed else "All demonstration paths behaved.")
    return 1 if failed else 0


def experiment_live(settings: Settings, args: argparse.Namespace) -> int:
    from moody_blues.contracts.agent import AgentBudget as Budget
    from moody_blues.experiments.demo import demo_case, render_evidence, run_case
    from moody_blues.experiments.target import AgentTarget

    if not args.confirm_billable:
        print(
            json.dumps(
                {
                    "status": "NOT_RUN",
                    "reason": "experiment-live is billable; pass --confirm-billable "
                    "(make experiment-live CONFIRM=1)",
                },
                indent=2,
            )
        )
        return 2
    model = args.model or settings.vultr_model
    root = _experiment_root()
    code, client = _agent_preflight(settings, model, root / "live-preflight.json")
    if client is None:
        return code
    runner = _ready_sandbox(settings)
    if runner is None:
        return 2
    target = AgentTarget(
        inference=client,
        evidence="live_provider",
        provider="vultr",
        model=model,
        budget=Budget(
            max_steps=args.max_steps,
            max_tool_calls=args.max_tool_calls,
            max_total_tokens=args.max_run_tokens,
            max_wall_seconds=120,
        ),
        ledger=_ledger(settings),
    )
    case = demo_case(args.case)
    evidence = run_case(
        case,
        sandbox=runner,
        root=root,
        sandbox_limits=_sandbox_limits(settings),
        target=target,
        config=args.config,
    )
    print(render_evidence(evidence, title=f"LIVE: {case.title}", root=root))
    status = _ledger(settings).status()
    print(
        f"\nspend ledger: ${status.settled_usd:.4f} settled, ${status.remaining_usd:.4f} of "
        f"${status.limit_usd:.2f} left (estimate at assumed ceiling prices)"
    )
    return 3 if evidence.status.value == "budget_exhausted" else 0


def experiment_recover(settings: Settings) -> int:
    from moody_blues.experiments.recovery import recover_interrupted
    from moody_blues.investigator.workspace import recover_investigations

    runner = _ready_sandbox(settings)
    if runner is None:
        return 2
    removed = runner.reap_orphans()
    recovered = recover_interrupted(_experiment_root())
    for investigation in recover_investigations(ARTIFACTS / "investigations"):
        print(f"{investigation}: marked interrupted; reservations stay open in the ledger")
    print(f"orphan sandboxes removed: {len(removed)}")
    for e in recovered:
        print(f"{e.experiment_id}: closed as {e.status.value} ({e.termination.value})")
    if not recovered:
        print("no interrupted experiments")
    return 0


def _known_secrets(settings: Settings) -> tuple[str, ...]:
    held = (settings.vultr_api_key, settings.operator_token)
    return tuple(s.get_secret_value() for s in held if s is not None)


def recorded_export(settings: Settings) -> int:
    from moody_blues.explorer.paths import artifacts_dir, recorded_dir
    from moody_blues.explorer.recorded import export

    manifest = export(
        artifacts_dir(settings), recorded_dir(settings), secrets=_known_secrets(settings)
    )
    print(manifest.model_dump_json(indent=2))
    return 0


def recorded_verify(settings: Settings) -> int:
    from moody_blues.explorer.paths import artifacts_dir, recorded_dir
    from moody_blues.explorer.recorded import verify_export

    artifacts = artifacts_dir(settings)
    problems = verify_export(
        recorded_dir(settings),
        artifacts if (artifacts / "investigations").is_dir() else None,
        secrets=_known_secrets(settings),
    )
    status = "FAIL" if problems else "PASS"
    print(json.dumps({"status": status, "problems": problems}, indent=2))
    return 1 if problems else 0


def _git_commit() -> str | None:
    """The release id on a host, where there is no ``.git``; the checkout's HEAD otherwise."""
    release = os.environ.get("MOODY_RELEASE")
    if release:
        return release
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - a developer checkout, for labeling only
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else None


def containment_report(settings: Settings) -> int:
    from moody_blues.explorer.containment import run_containment, vultr_instance, write_report
    from moody_blues.explorer.paths import containment_report_path

    report = run_containment(
        settings,
        git_commit=_git_commit(),
        known_secrets=_known_secrets(settings),
        instance=vultr_instance(),
    )
    write_report(report, containment_report_path(settings))
    summary = {
        "status": report.status,
        "environment": report.host.environment,
        "attempts": {a.attempt_id: a.held for a in report.attempts},
        "effective_checks_failed": [c.name for c in report.effective_checks if c.status != "PASS"],
        "sha256": report.sha256,
    }
    print(json.dumps(summary, indent=2))
    return 0 if report.status == "PASS" else 1


def ledger_verify(settings: Settings) -> int:
    from moody_blues.experiments.budget import BudgetExceededError

    ledger = _ledger(settings)
    try:
        entries = ledger.export()  # no floor here: this is what a migration inspects
    except BudgetExceededError as exc:
        print(json.dumps({"status": "FAIL", "reason": exc.detail.message}, indent=2))
        return 1
    settled = sum(float(str(e["amount_usd"])) for e in entries if e["kind"] == "settle")
    closed = {e["entry_id"] for e in entries if e["kind"] == "settle"}
    open_entries = [e for e in entries if e["kind"] == "reserve" and e["entry_id"] not in closed]
    body = ledger.path.read_bytes() if ledger.path.is_file() else b""
    print(
        json.dumps(
            {
                "status": "PASS",
                "path": str(ledger.path),
                "sha256": hashlib.sha256(body).hexdigest(),
                "entries": len(entries),
                "settled_usd": round(settled, 6),
                "open_reservations": len(open_entries),
                "floor_usd": ledger.floor_usd,
                "above_floor": settled >= ledger.floor_usd,
            },
            indent=2,
        )
    )
    return 0


def _investigator(settings: Settings, args: argparse.Namespace) -> int:
    from moody_blues.contracts.investigation import Strategy, WorldTier
    from moody_blues.investigator import commands

    match args.command:
        case "investigator-preflight":
            return commands.preflight(settings)
        case "investigator-demo":
            return commands.demo(settings)
        case "investigator-live":
            return commands.investigate_live(
                settings,
                confirmed=args.confirm_billable,
                tier=WorldTier(args.tier),
                strategy=Strategy(args.strategy),
            )
        case "investigator-repro":
            return commands.reproduce(
                settings,
                confirmed=args.confirm_billable,
                experiment_id=args.experiment,
                runs=args.runs,
            )
        case _:
            return commands.evaluate(
                settings,
                confirmed=args.confirm_billable,
                tier=WorldTier(args.tier),
                trials=args.trials,
                pairs=args.part in {"pairs", "both"},
                compare=args.part in {"comparison", "both"},
                repeats=args.repeats,
            )


def _evaluation(settings: Settings, args: argparse.Namespace) -> int:
    from moody_blues.evaluation import commands

    match args.command:
        case "evidence-audit":
            return commands.evidence_audit()
        case "eval-freeze":
            return commands.eval_freeze(settings)
        case "eval-freeze-followup":
            return commands.eval_freeze_followup()
        case "eval-verify":
            return commands.eval_verify(settings)
        case "eval-report":
            return commands.eval_report(settings)
        case "eval-repro":
            return commands.eval_repro(
                settings,
                experiment_id=args.experiment,
                runs=args.runs,
                confirmed=args.confirm_billable,
            )
        case _:
            return commands.eval_run(settings, suite=args.suite, confirmed=args.confirm_billable)


def _external(settings: Settings, args: argparse.Namespace) -> int:
    from moody_blues.contracts.investigation import TargetKind
    from moody_blues.external import commands

    match args.command:
        case "external-preflight":
            return commands.preflight(settings, args.manifest)
        case "external-run":
            return commands.run(
                settings,
                args.manifest,
                world=args.world,
                live_inference=args.live_inference,
                confirm_billable=args.confirm_billable,
                approved_spend_usd=args.approved_spend_usd,
            )
        case "external-investigate":
            return commands.investigate(
                settings,
                kind=TargetKind(args.target),
                manifest=args.manifest,
                world=args.world,
                live=commands.LiveRequest(
                    target=args.live_inference,
                    investigator=args.live_investigator,
                    confirmed=args.confirm_billable,
                    approved_spend_usd=args.approved_spend_usd,
                ),
            )
        case _:
            return commands.demo(settings)


def live_budget(settings: Settings, reports: list[Path]) -> int:
    from moody_blues.contracts.agent import AgentRunReport as Report

    ledger = _ledger(settings)
    for path in reports:
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
        ledger.record_measured(f"imported:{report.run_id}", report.agent.tokens)
    print(ledger.status().model_dump_json(indent=2))
    return 0


def _add_agent_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", help="model id from the live catalog (default MOODY_VULTR_MODEL)")
    p.add_argument("--max-steps", type=int, default=10)
    p.add_argument("--max-tool-calls", type=int, default=16)
    p.add_argument("--max-run-tokens", type=int, default=60_000)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="moody-blues")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("docker-smoke")
    vs = sub.add_parser("vultr-smoke")
    vs.add_argument(
        "--check",
        action="append",
        choices=sorted(vultr_smoke.CHECKS),
        help="run only this check (repeatable); default: all",
    )
    sub.add_parser("vultr-models")
    from moody_blues.services.world_runner import EXECUTORS_AVAILABLE
    from moody_blues.world.reference import REFERENCE_CASES
    from moody_blues.world.scenarios import scenario_ids

    wd = sub.add_parser("world-demo")
    wd.add_argument(
        "--case",
        action="append",
        choices=[c.case_id for c in REFERENCE_CASES],
        help="run only this reference case (repeatable); default: all",
    )
    wd.add_argument("--keep", action="store_true", help="keep SQLite worlds under .artifacts/")
    wd.add_argument("--no-color", action="store_true")
    wr = sub.add_parser("world-run")
    wr.add_argument("--scenario", required=True, choices=scenario_ids())
    wr.add_argument("--executor", required=True, choices=EXECUTORS_AVAILABLE)
    wr.add_argument("--json", action="store_true", help="print the full RunReport as JSON")
    wr.add_argument("--no-color", action="store_true")
    from moody_blues.contracts.agent import AgentConfigName

    configs = [c.value for c in AgentConfigName]
    ar = sub.add_parser("agent-run")
    ar.add_argument("--scenario", required=True, choices=scenario_ids())
    ar.add_argument("--config", required=True, choices=configs)
    ar.add_argument("--json", action="store_true")
    _add_agent_args(ar)
    ae = sub.add_parser("agent-eval")
    ae.add_argument("--scenario", action="append", choices=scenario_ids())
    ae.add_argument("--config", action="append", choices=configs)
    ae.add_argument("--trials", type=int, default=3)
    ae.add_argument("--max-eval-tokens", type=int, default=400_000)
    ae.add_argument("--confirm-billable", action="store_true", help="required: this is billable")
    _add_agent_args(ae)
    from moody_blues.experiments.demo import DEMO_CASES, LIVE_CASE_IDS

    ed = sub.add_parser("experiment-demo")
    ed.add_argument("--case", action="append", choices=[c.case_id for c in DEMO_CASES])
    el = sub.add_parser("experiment-live")
    el.add_argument("--case", required=True, choices=LIVE_CASE_IDS)
    el.add_argument("--config", default="baseline", choices=configs)
    el.add_argument("--model", help="model id from the live catalog (default MOODY_VULTR_MODEL)")
    el.add_argument("--confirm-billable", action="store_true", help="required: this is billable")
    # Same step and tool limits as agent-run, so results stay comparable: a tighter step cap
    # cut a correct run off one step before its claim. The token cap is what bounds spend.
    el.add_argument("--max-steps", type=int, default=10)
    el.add_argument("--max-tool-calls", type=int, default=16)
    el.add_argument("--max-run-tokens", type=int, default=20_000)
    sub.add_parser("experiment-recover")
    xp = sub.add_parser("external-preflight")
    xp.add_argument("--manifest", type=Path, required=True)
    xr = sub.add_parser("external-run")
    xr.add_argument("--manifest", type=Path, required=True)
    xr.add_argument("--world", default="normal-success")
    xr.add_argument("--live-inference", action="store_true")
    xr.add_argument("--confirm-billable", action="store_true")
    xr.add_argument("--approved-spend-usd", type=float)
    xi = sub.add_parser("external-investigate")
    xi.add_argument(
        "--target", required=True, choices=["internal_llm", "external_scripted", "external_llm"]
    )
    xi.add_argument("--manifest", type=Path)
    xi.add_argument("--world", default="normal-success")
    xi.add_argument("--live-inference", action="store_true")
    xi.add_argument("--live-investigator", action="store_true")
    xi.add_argument("--confirm-billable", action="store_true")
    xi.add_argument("--approved-spend-usd", type=float)
    sub.add_parser("external-demo")
    sub.add_parser("recorded-export")
    sub.add_parser("recorded-verify")
    sub.add_parser("containment-report")
    sub.add_parser("ledger-verify")
    sub.add_parser("investigator-preflight")
    sub.add_parser("investigator-demo")
    il = sub.add_parser("investigator-live")
    il.add_argument(
        "--tier", choices=["development", "validation", "evaluation"], default="validation"
    )
    il.add_argument("--strategy", choices=["adaptive", "one_shot", "fixed"], default="adaptive")
    il.add_argument("--confirm-billable", action="store_true")
    ir = sub.add_parser("investigator-repro")
    ir.add_argument("--experiment", required=True)
    ir.add_argument("--runs", type=int, default=6)
    ir.add_argument("--confirm-billable", action="store_true")
    ie = sub.add_parser("investigator-eval")
    ie.add_argument("--tier", choices=["validation", "evaluation"], default="validation")
    ie.add_argument("--trials", type=int, default=1)
    ie.add_argument("--repeats", type=int, default=2, choices=[2, 3, 4])
    ie.add_argument("--part", choices=["pairs", "comparison", "both"], default="both")
    ie.add_argument("--confirm-billable", action="store_true")
    lb = sub.add_parser("live-budget")
    lb.add_argument(
        "--import-report",
        action="append",
        type=Path,
        default=[],
        help="book a saved agent run report made outside the ledger",
    )
    sub.add_parser("evidence-audit")
    sub.add_parser("eval-freeze")
    sub.add_parser("eval-freeze-followup")
    sub.add_parser("eval-verify")
    sub.add_parser("eval-report")
    er = sub.add_parser("eval-run")
    er.add_argument(
        "--suite", choices=("causal", "strategies", "adaptation", "followup"), required=True
    )
    er.add_argument("--confirm-billable", action="store_true")
    rp = sub.add_parser("eval-repro")
    rp.add_argument("--experiment", required=True)
    rp.add_argument("--runs", type=int, default=5)
    rp.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args(argv)
    color = sys.stdout.isatty() and not getattr(args, "no_color", False)

    settings = Settings()
    match args.command:
        case "doctor":
            return doctor(settings)
        case "docker-smoke":
            return docker_smoke(settings)
        case "vultr-smoke":
            return _vultr(settings, args.check or list(vultr_smoke.CHECKS), "vultr-smoke.json")
        case "vultr-models":
            return _vultr(settings, ["list_models"], "vultr-models.json")
        case "world-demo":
            return world_demo(args.case, keep=args.keep, color=color)
        case "world-run":
            return world_run(args.scenario, args.executor, as_json=args.json, color=color)
        case "agent-run":
            return agent_run(settings, args)
        case "agent-eval":
            return agent_eval(settings, args)
        case "experiment-demo":
            return experiment_demo(settings, args.case)
        case "experiment-live":
            return experiment_live(settings, args)
        case "experiment-recover":
            return experiment_recover(settings)
        case "external-preflight" | "external-run" | "external-investigate" | "external-demo":
            return _external(settings, args)
        case "recorded-export":
            return recorded_export(settings)
        case "recorded-verify":
            return recorded_verify(settings)
        case "containment-report":
            return containment_report(settings)
        case "ledger-verify":
            return ledger_verify(settings)
        case "live-budget":
            return live_budget(settings, args.import_report)
        case "investigator-preflight" | "investigator-demo" | "investigator-live":
            return _investigator(settings, args)
        case "investigator-eval" | "investigator-repro":
            return _investigator(settings, args)
        case (
            "evidence-audit"
            | "eval-freeze"
            | "eval-verify"
            | "eval-report"
            | "eval-run"
            | "eval-repro"
            | "eval-freeze-followup"
        ):
            return _evaluation(settings, args)
        case _:
            parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
