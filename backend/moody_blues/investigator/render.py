"""Plain-text reports. Model-written text is shown inert and always labeled as interpretation."""

from __future__ import annotations

from moody_blues.contracts.investigation import InvestigationReport
from moody_blues.experiments.demo import safe_text


def _basis(report: InvestigationReport) -> str:
    if report.model_evidence_source is None:
        return "no model (fixed developer programs)"
    if report.model_evidence_source == "offline_fixture":
        return "OFFLINE FIXTURE: scripted stand-in, not model behavior"
    return f"LIVE model {report.request.investigator_model}"


def render_report(report: InvestigationReport) -> str:
    r = report
    lines = [
        f"# Investigation {r.investigation_id}",
        "",
        f"- Strategy: {r.request.strategy.value}. Investigator: {_basis(r)}",
        f"- Objective: {safe_text(r.request.objective, 300)}",
        f"- Worlds ({r.request.tier.value}): {', '.join(r.request.world_ids)}",
        f"- State: {r.state.value} ({r.termination})",
        f"- **Result: {r.statement}**",
        "",
        "## Hypotheses (model interpretation, not evidence)",
    ]
    for record in r.hypotheses:
        h = record.hypothesis
        revises = f" revises {h.revises}" if h.revises else ""
        cited = ", ".join(h.motivating_observations) or "capability description"
        lines.append(f"- **{h.hypothesis_id}** [{record.status}]{revises}, from {cited}")
        lines.append(f"  - Mechanism: {safe_text(h.suspected_mechanism, 300)}")
        lines.append(f"  - Predicts: {safe_text(h.predicted_observation, 300)}")
        lines.append(f"  - Distinguished by: {safe_text(h.failure_discriminator, 300)}")
        if record.assessment is not None:
            lines.append(f"  - Assessment: {safe_text(record.assessment.reasoning, 300)}")
    lines += ["", "## Generated programs"]
    for p in r.proposals:
        sha = (p.source_sha256 or "none")[:16]
        extra = f", replaces {p.replaces_proposal_id}" if p.replaces_proposal_id else ""
        problem = f" ({p.rejection.problem})" if p.rejection is not None else ""
        lines.append(
            f"- {p.proposal_id} {p.authorship.value}: {p.status.value}{problem}, "
            f"sha256 {sha}, motivated by {', '.join(p.motivated_by) or 'nothing yet'}{extra}"
        )
    lines += ["", "## Experiments and observations"]
    observations = {o.observation_id: o for o in r.observations}
    for e in r.experiments:
        kind = f" reproduction of {e.reproduction_of}" if e.reproduction_of else ""
        lines.append(f"- {e.experiment_id}{kind}: {e.status.value} -> {e.result_class.value}")
        observation = observations.get(e.observation_id)
        for run in observation.runs if observation is not None else []:
            faults = (
                ", ".join(f"{f.kind}#{f.occurrence}x{f.span}" for f in run.selected_faults)
                or run.fault_source
            )
            lines.append(
                f"  - {run.world_ref} {run.config.value} faults[{faults}]: "
                f"Oracle {run.oracle.verdict.value}, outcome {run.oracle.run_outcome}, "
                f"{run.delivered.tool_calls} calls, {run.delivered.faults_delivered} faults "
                f"delivered, codes {', '.join(run.oracle.finding_codes) or 'none'}"
            )
    lines += ["", "## Decisions"]
    lines += [
        f"- {d.seq}. {d.kind.value}: {d.reason}"
        + (f" (cites {', '.join(d.cited_observations)})" if d.cited_observations else "")
        for d in r.decisions
    ]
    lines += ["", "## Findings (trusted code, from Oracle reports)"]
    for f in r.findings:
        lines.append(
            f"- {f.finding_class.value}: {f.world_ref} {f.config.value}, run {f.run_id}, "
            f"Oracle {f.oracle_verdict.value}, outcome {f.run_outcome}, "
            f"violations {', '.join(f.violation_codes) or 'none'}, "
            f"faults delivered {f.faults_delivered}, source {f.target_evidence_source}, "
            f"reproduction {f.reproduction.value}"
        )
        lines += [f"  - {safe_text(n, 200)}" for n in f.notes]
    if not r.findings:
        lines.append("- none: no target run completed")
    if r.model_conclusion is not None:
        lines += [
            "",
            "## Model's conclusion (interpretation, checked below)",
            f"{r.model_conclusion.conclusion}: {safe_text(r.model_conclusion.reasoning, 600)}",
        ]
    for check in r.claim_checks:
        verdict = "supported" if check.supported else "UNSUPPORTED"
        cause = "" if check.fault_was_delivered else "; no fault was delivered in that run"
        lines.append(
            f"- Claim {safe_text(check.claim.finding_code, 60)} on "
            f"{safe_text(check.claim.experiment_id, 40)}: {verdict} "
            f"({check.reason}{cause})"
        )
    u = r.usage
    lines += [
        "",
        "## Usage",
        f"- Investigator: {u.model_calls} calls, {u.investigator_prompt_tokens} prompt + "
        f"{u.investigator_completion_tokens} completion tokens, "
        f"{u.investigator_latency_ms} ms, est. ${u.investigator_cost_usd:.4f}",
        f"- Target: {u.target_runs} runs, {u.target_tokens} tokens, est. ${u.target_cost_usd:.4f}",
        f"- Sandbox: {u.sandbox_executions} executions, {u.sandbox_ms} ms. Wall: {u.wall_ms} ms",
        f"- {u.note}",
        "",
        "## Limitations",
        *[f"- {item}" for item in r.limitations],
    ]
    return "\n".join(lines) + "\n"
