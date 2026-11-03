"""Terminal rendering of a real ``AgentRunReport`` (``moody-blues agent-run``).

Everything printed comes from the report: the model's actual tool calls, what the gateway
delivered, committed rows read back read-only, and the Oracle's verdict. Fault labels are
shown here for the operator; the agent never saw them.
"""

from __future__ import annotations

from moody_blues.contracts.agent import AgentRunReport, ToolCallDisposition


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_agent_report(report: AgentRunReport) -> str:
    a = report.agent
    faults = {t.delivered.call_id: t for t in report.world_trace}
    lines = [
        f"== agent-run [{a.config.value} / {a.policy_version}] {report.scenario_ref} "
        f"| run {report.run_id} | world {report.world_id}",
        f"   evidence: {report.evidence_source} | provider {report.provider} | model "
        f"{report.requested_model} (reported: {', '.join(report.reported_models) or 'n/a'})",
        "",
        "  Agent trajectory (model-chosen tool calls -> what was delivered)",
    ]
    for step in a.steps:
        tok = step.usage.total_tokens if step.usage else None
        lines.append(
            f"   step {step.index}: {step.latency_ms} ms, {tok} tokens, finish={step.finish_reason}"
        )
        if step.content:
            lines.append(f"      says: {_short(step.content)}")
        for c in (
            c for c in a.tool_calls if c.tool_call_id in step.tool_call_ids and c.step == step.index
        ):
            lines.append(f"      {c.name} {_short(c.arguments_json, 110)}  [{c.tool_call_id}]")
            if c.disposition is ToolCallDisposition.EXECUTED and c.delivered is not None:
                d = c.delivered
                res = "OK" if d.ok else f"ERROR {d.error.code.value if d.error else '?'}"
                t = faults.get(d.call_id)
                fault = (
                    f"  <fault: {t.fault_injected} / {t.fault_effect}>"
                    if t and (t.fault_injected or t.fault_effect)
                    else ""
                )
                lines.append(
                    f"        -> {d.call_id} {res}: {_short(c.result_content, 100)}{fault}"
                )
            else:
                lines.append(f"        -> {c.disposition.value}: {_short(c.result_content, 100)}")
        if step.claim_reminder_sent:
            lines.append("      (no tool call; claim reminder sent)")
    lines += [
        f"   termination: {a.termination.value}"
        + (f" ({a.error.category.value}: {_short(a.error.message, 100)})" if a.error else ""),
        f"   final claim: {_claim(report)} ({a.claim_outcome.value})",
        f"   tokens {a.tokens.total_tokens}{'' if a.tokens.complete else ' (partly estimated)'} | "
        f"inference {a.inference_latency_ms} ms | wall {a.wall_ms} ms | cost "
        f"{report.estimated_cost_usd if report.estimated_cost_usd is not None else 'n/a'}",
        "",
        "  Committed state (read-only)",
    ]
    seeds = set(report.oracle.observation.seed_customer_ids)
    new = [r for r in report.final_state if r.customer_id not in seeds]
    lines += [
        f"   {r.customer_id} {r.name} <{r.email}> {r.metadata} key={r.client_request_id} "
        f"(call_{r.created_by_call:04d})"
        for r in new
    ] or ["   (no new customers)"]
    o, s = report.oracle, report.assessment
    lines += [
        "",
        f"  Truth Oracle: {o.verdict.value}  objective_satisfied="
        f"{str(o.objective_satisfied).lower()}",
    ]
    lines += [f"   - {f.severity.value} {f.code.value}: {f.message}" for f in o.findings]
    lines.append(
        f"  Assessment: outcome={s.outcome.value} recovery={s.recovery.value} "
        f"attribution={s.attribution} distortions={s.distortions_delivered} "
        f"creates={s.behavior.create_calls} keyed={s.behavior.creates_with_client_request_id} "
        f"verified_claim={s.behavior.verified_claimed_id}"
    )
    return "\n".join(lines)


def _claim(report: AgentRunReport) -> str:
    c = report.agent.claim
    return "none" if c is None else f"{c.status.value} {c.customer_id}"
