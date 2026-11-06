"""Terminal rendering for real World Engine runs (``moody-blues world-demo`` / ``world-run``).

Everything printed comes from an actual ``RunReport``: the delivered tool responses, rows read
back from the world's SQLite file and the Oracle's report. Nothing here is precomputed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from moody_blues.contracts.oracle import Severity, Verdict
from moody_blues.contracts.run import RunReport, ToolTraceEntry
from moody_blues.contracts.world import CustomerRecord
from moody_blues.services.world_runner import run_reference_case
from moody_blues.world.reference import REFERENCE_CASES, ReferenceCase


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def yellow(self, t: str) -> str:
        return self._wrap("33", t)

    def verdict(self, v: Verdict) -> str:
        colour = {Verdict.PASS: self.green, Verdict.VIOLATION: self.red}.get(v, self.yellow)
        return self.bold(colour(v.value))


def _response_line(t: ToolTraceEntry, s: _Style) -> str:
    r = t.delivered
    if r.ok and r.data is not None:
        customer = r.data.get("customer")
        if isinstance(customer, dict):
            detail = f"OK customer={customer.get('customer_id')}"
            if r.data.get("idempotent_replay") is True:
                detail += " (idempotent replay)"
        else:
            detail = f"OK count={r.data.get('count')}"
        outcome = s.green(detail)
    else:
        err = r.error
        code = err.code.value if err else "?"
        retry = " retryable" if err and err.retryable else ""
        outcome = s.red(f"ERROR {code}{retry}")
    fault = s.yellow(f"  [fault: {t.fault_injected}]") if t.fault_injected else ""
    events = f"events #{t.event_seqs[0]}-#{t.event_seqs[-1]}"
    return f"    {r.call_id}  {t.tool:<17} -> {outcome}{fault}  {s.dim(events)}"


def render_report(report: RunReport, *, purpose: str = "", color: bool = False) -> str:
    s = _Style(color)
    o = report.oracle
    lines = [
        s.bold(f"== [{report.case_id or 'run'}] {purpose}".rstrip()),
        s.dim(
            f"   scenario {report.scenario_ref} | executor {report.executor} "
            f"(deterministic script, not an LLM) | world {report.world_id}"
        ),
        "",
        s.bold("  Layer B - responses delivered to the executor"),
        *(_response_line(t, s) for t in report.tool_trace),
    ]
    c = report.claim
    claim = "none" if c is None else f"{c.status.value} customer_id={c.record_ref}"
    lines += [f"    final claim: {claim}  {s.dim(f'event #{report.claim_event_seq}')}", ""]

    seeds = set(o.observation.seed_ids)
    rows = [r for r in report.final_state if isinstance(r, CustomerRecord)]  # the demo is the CRM
    new_rows = [r for r in rows if r.customer_id not in seeds]
    lines.append(
        s.bold("  Layer A - committed state (read back via read-only connection)")
        + s.dim(f"  {len(seeds)} seed + {len(new_rows)} new")
    )
    if not new_rows:
        lines.append("    (no customers committed by this run)")
    for r in new_rows:
        lines.append(
            f"    {r.customer_id}  {r.name} <{r.email}>  "
            + s.dim(f"committed by call_{r.created_by_call:04d}")
        )
    lines += [
        "",
        s.bold("  Layer C - Truth Oracle: ")
        + s.verdict(o.verdict)
        + f"  objective_satisfied={str(o.objective_satisfied).lower()}",
    ]
    marks = {Severity.VIOLATION: s.red("x"), Severity.WARNING: s.yellow("!"), Severity.INFO: "-"}
    for f in o.findings:
        inv = f" [{f.invariant}]" if f.invariant else ""
        calls = f" calls={f.call_seqs}" if f.call_seqs else ""
        lines.append(f"    {marks[f.severity]} {f.code}{inv}: {f.message}{s.dim(calls)}")
    if not o.findings:
        lines.append("    (no findings)")
    lines.append(
        s.dim(
            f"   verdict event #{report.verdict_event_seq} | fingerprint {report.fingerprint[:16]}"
        )
    )
    return "\n".join(lines)


def run_demo(
    cases: Sequence[ReferenceCase] = REFERENCE_CASES,
    *,
    artifacts_dir: Path,
    keep_worlds: bool = False,
    color: bool = False,
) -> list[RunReport]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    worlds_dir = artifacts_dir / "worlds"
    if keep_worlds:
        worlds_dir.mkdir(exist_ok=True)
    reports: list[RunReport] = []
    s = _Style(color)
    for case in cases:
        report = run_reference_case(
            case, root_dir=worlds_dir if keep_worlds else None, keep=keep_worlds
        )
        (artifacts_dir / f"{case.case_id}.json").write_text(
            json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )
        print(render_report(report, purpose=case.purpose, color=color))
        print()
        reports.append(report)

    print(s.bold("Summary"))
    for case, report in zip(cases, reports, strict=True):
        o = report.oracle
        new = len(o.observation.new_ids)
        div = len(o.response_divergences)
        print(
            f"  {case.case_id:<26} {s.verdict(o.verdict):<12} "
            f"new_rows={new} response/state divergences={div}"
        )
    print(s.dim(f"\nJSON run reports: {artifacts_dir}"))
    if keep_worlds:
        print(s.dim(f"SQLite worlds kept under: {worlds_dir}"))
    return reports
