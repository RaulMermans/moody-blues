import Link from "next/link";
import type { ReactNode } from "react";

import type { RealityRun, RunList, ToolEvent } from "@/lib/evidence-types";
import { DISCREPANCY_LABEL, FAULT_LABEL, FINDING_CLASS_LABEL, humanize } from "@/lib/labels";

import { Chevron, Code, Eyebrow, Tag, VerdictTag } from "./ui";
import { disclosureLine, VerdictStrip } from "./verdict-strip";

function RunPicker({ id, runs, current }: { id: string; runs: RunList; current: string }) {
  if (runs.runs.length < 2) return null;
  return (
    <nav aria-label="Target runs" className="flex flex-wrap gap-2">
      {runs.runs.map((run, index) => {
        const active = run.run_id === current;
        return (
          <Link
            key={run.run_id}
            href={`/investigations/${id}?view=reality&run=${run.run_id}`}
            aria-current={active ? "page" : undefined}
            data-testid={`run-${run.run_id}`}
            className={`flex items-center gap-2 rounded border px-2.5 py-1.5 font-mono text-xs ${
              active ? "border-truth/60 bg-raised text-foreground" : "border-line text-muted hover:text-foreground"
            }`}
          >
            <span>
              Run {index + 1} · {run.world_ref}
            </span>
            <VerdictTag verdict={run.verdict} />
          </Link>
        );
      })}
    </nav>
  );
}

function actualFor(event: ToolEvent, run: RealityRun): { text: string; tone: "bad" | "plain" } {
  const committed = run.actual.changes.find(
    (c) => c.created_by_call === event.call_seq && c.operation === "insert",
  );
  if (event.fault_injected && event.actual_summary) {
    const write = event.tool === "create_customer";
    const suffix = committed
      ? `; committed ${committed.customer_id}`
      : write
        ? "; committed nothing"
        : "";
    return { text: `True response: ${event.actual_summary}${suffix}`, tone: "bad" };
  }
  if (committed) return { text: `Committed ${committed.customer_id}`, tone: "plain" };
  if (event.tool === "create_customer") return { text: "Committed nothing", tone: "plain" };
  return { text: "Delivered as it was", tone: "plain" };
}

function CallRow({ event, run }: { event: ToolEvent; run: RealityRun }) {
  const actual = actualFor(event, run);
  return (
    <li
      data-testid={`call-${event.call_seq}`}
      data-fault={event.fault_injected ?? ""}
      className="grid gap-px bg-line md:grid-cols-2"
    >
      <div
        className={`min-w-0 bg-surface p-3 ${event.fault_injected ? "border-l-2 border-warn" : ""}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-faint">#{event.call_seq}</span>
          <span className="font-mono text-sm text-foreground">{event.tool}</span>
          {event.fault_injected ? (
            <Tag tone="warn" title={FAULT_LABEL[event.fault_injected]}>
              {event.fault_injected}
            </Tag>
          ) : null}
        </div>
        <p className={`mt-1 break-words font-mono text-xs ${event.ok ? "text-agent" : "text-warn"}`}>
          {event.delivered_summary}
        </p>
        {event.agent_note ? (
          <p className="mt-2 border-l-2 border-agent/30 pl-2 text-sm leading-6 text-muted">
            {event.agent_note.text}
          </p>
        ) : null}
        <details className="mt-2">
          <summary className="flex items-center gap-1 text-xs text-faint hover:text-foreground">
            <Chevron /> Arguments and response
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            <Code>{event.arguments.text}</Code>
            <Code>{event.delivered.text}</Code>
          </div>
        </details>
      </div>
      <div className={`min-w-0 p-3 ${actual.tone === "bad" ? "bg-[color-mix(in_srgb,var(--bad)_9%,var(--surface))]" : "bg-surface"}`}>
        <p className="text-xs text-faint md:hidden">Actually</p>
        <p
          data-testid={`actual-${event.call_seq}`}
          className={`break-words font-mono text-xs ${actual.tone === "bad" ? "text-bad" : "text-truth"}`}
        >
          {actual.text}
        </p>
      </div>
    </li>
  );
}

function targetLabel(run: RealityRun): string {
  if (run.target_evidence === "live_provider") {
    return `Target: live model ${run.reported_models.join(", ")}`;
  }
  if (run.target_evidence === "reference_executor") return "Target: reference script, not a model";
  return "Target: offline fixture, not a model";
}

function missionLine(text: string): string {
  return text.split("\n")[0].replace(/^Mission:\s*/, "");
}

function Discrepancies({ run }: { run: RealityRun }) {
  const counts = new Map<string, number>();
  for (const d of run.discrepancies) counts.set(d.kind, (counts.get(d.kind) ?? 0) + 1);
  const line = [...counts.entries()]
    .map(([kind, count]) => `${count} ${DISCREPANCY_LABEL[kind].toLowerCase()}`)
    .join(", ");
  return (
    <details className="rounded-lg border border-line bg-surface p-3" data-testid="discrepancy-panel">
      <summary className="flex items-center gap-2 text-sm text-foreground">
        <Chevron />
        <span>
          {run.discrepancies.length} discrepanc{run.discrepancies.length === 1 ? "y" : "ies"}:{" "}
          <span className="text-muted">{line}</span>
        </span>
      </summary>
      <div className="mt-3 overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[36rem] text-left text-sm" data-testid="discrepancies">
          <caption className="sr-only">
            Differences between what the agent saw and authoritative state
          </caption>
          <thead className="bg-raised text-xs text-faint">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Kind</th>
              <th scope="col" className="px-3 py-2 font-medium text-agent">Agent saw</th>
              <th scope="col" className="px-3 py-2 font-medium text-truth">Actually</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {run.discrepancies.map((d, i) => (
              <tr key={i} data-kind={d.kind}>
                <td className="px-3 py-2 align-top text-xs text-muted">
                  {DISCREPANCY_LABEL[d.kind]}
                  {d.call_seq !== null ? (
                    <span className="block font-mono text-faint">call {d.call_seq}</span>
                  ) : null}
                </td>
                <td className="break-words px-3 py-2 align-top font-mono text-xs text-agent">
                  {d.agent_saw}
                </td>
                <td className="break-words px-3 py-2 align-top font-mono text-xs text-truth">
                  {d.actually}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Column({ tone, title, note }: { tone: "agent" | "truth"; title: string; note: string }) {
  return (
    <div className="bg-raised p-3">
      <h3 className={`text-sm font-semibold ${tone === "agent" ? "text-agent" : "text-truth"}`}>
        {title}
      </h3>
      <p className="text-xs text-faint">{note}</p>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <Eyebrow>{title}</Eyebrow>
      {children}
    </section>
  );
}

function ClaimCard({ run }: { run: RealityRun }) {
  const claim = run.agent.claim;
  if (!claim) {
    return (
      <div data-testid="claim-card" className="bg-surface p-3">
        <p className="font-mono text-sm text-warn">No valid final claim</p>
        <p className="mt-1 text-sm text-muted">
          The run ended with {humanize(run.agent.termination).toLowerCase()}. A missing claim is
          never read as success.
        </p>
      </div>
    );
  }
  const disclosure = disclosureLine(run);
  return (
    <div data-testid="claim-card" className="min-w-0 bg-surface p-3">
      <p className="text-xs text-faint">Structured final claim</p>
      <p data-testid="claim-status" className="mt-1 font-mono text-sm text-agent">
        status: {claim.status}
      </p>
      {claim.customer_id ? (
        <p className="break-all font-mono text-xs text-muted">customer_id: {claim.customer_id}</p>
      ) : null}
      <p className="mt-3 text-xs text-faint">Free-text message, written by the agent</p>
      <p data-testid="claim-message" className="mt-1 text-sm leading-6 text-muted">
        {claim.message.text}
        {claim.message.truncated ? " [cut for display]" : ""}
      </p>
      {disclosure ? (
        <p
          data-testid="disclosure"
          className="mt-3 rounded border border-agent/30 bg-agent/5 p-2 text-sm leading-6 text-foreground"
        >
          {disclosure}
        </p>
      ) : null}
    </div>
  );
}

function OracleCard({ run }: { run: RealityRun }) {
  const violations = run.actual.findings.filter((f) => f.severity === "violation");
  const notes = run.actual.findings.filter((f) => f.severity !== "violation");
  return (
    <div data-testid="oracle-card" className="min-w-0 bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <VerdictTag verdict={run.verdict} testId="oracle-verdict" />
        <span className="font-mono text-xs text-muted">
          run outcome: {humanize(run.run_outcome)}
        </span>
      </div>
      {run.finding_class ? (
        <p className="mt-1 text-xs text-faint">
          {FINDING_CLASS_LABEL[run.finding_class] ?? humanize(run.finding_class)}
          {run.impairments.length ? ` · impaired: ${run.impairments.join(", ")}` : ""}
        </p>
      ) : null}
      {violations.length ? (
        <ul className="mt-3 flex flex-col gap-2">
          {violations.map((f) => (
            <li key={f.code} data-testid={`oracle-finding-${f.code}`} className="text-sm leading-6">
              <span className="font-mono text-xs text-bad">{f.code}</span>
              <span className="block text-muted">{f.message}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted">No invariant was found broken in this run.</p>
      )}
      {notes.length ? (
        <details className="mt-3">
          <summary className="flex items-center gap-1 text-xs text-faint hover:text-foreground">
            <Chevron /> {notes.length} diagnostic note{notes.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 flex flex-col gap-1 text-xs text-muted">
            {notes.map((f, i) => (
              <li key={i} className="break-words">
                {f.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function Records({ run }: { run: RealityRun }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full min-w-[34rem] text-left text-sm">
        <caption className="sr-only">Authoritative customer records after the run</caption>
        <thead className="bg-raised text-xs text-faint">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Record</th>
            <th scope="col" className="px-3 py-2 font-medium">Name</th>
            <th scope="col" className="px-3 py-2 font-medium">Created by</th>
            <th scope="col" className="px-3 py-2 font-medium">Marks</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          {run.actual.customers.map((c) => (
            <tr key={c.customer_id} data-testid={`record-${c.customer_id}`} data-duplicate={c.flagged_duplicate}>
              <td className="px-3 py-2 font-mono text-xs text-truth">{c.customer_id}</td>
              <td className="px-3 py-2 text-muted">
                {c.name} <span className="text-faint">{c.email}</span>
              </td>
              <td className="px-3 py-2 font-mono text-xs text-muted">
                {c.role === "seed" ? "seed" : `call ${c.created_by_call}`}
              </td>
              <td className="px-3 py-2">
                <span className="flex flex-wrap gap-1">
                  {c.flagged_duplicate ? <Tag tone="bad">duplicate</Tag> : null}
                  {c.named_in_claim ? <Tag tone="agent">named in claim</Tag> : null}
                  {c.role === "seed" ? <Tag>pre-existing</Tag> : null}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RealityView({ id, runs, run }: { id: string; runs: RunList; run: RealityRun }) {
  return (
    <div className="flex flex-col gap-6" data-testid="reality-view" data-run={run.run_id}>
      <RunPicker id={id} runs={runs} current={run.run_id} />
      <div className="flex flex-wrap items-center gap-2">
        <Tag testId="target-evidence" tone={run.target_evidence === "live_provider" ? "truth" : "warn"}>
          {targetLabel(run)}
        </Tag>
        <span className="font-mono text-xs text-faint">
          {run.world_ref} · {run.config} policy
          {run.agent.recovery_pattern ? ` · recovery: ${humanize(run.agent.recovery_pattern).toLowerCase()}` : ""}
        </span>
      </div>
      <VerdictStrip run={run} />

      <div className="grid gap-4 md:grid-cols-2">
        {run.agent.mission ? (
          <Panel title="The task it was given">
            <p data-testid="mission" className="text-sm leading-6 text-muted">
              {missionLine(run.agent.mission.text)}
            </p>
            <details>
              <summary className="flex items-center gap-1 text-xs text-faint hover:text-foreground">
                <Chevron /> Full task text
              </summary>
              <div className="mt-2">
                <Code>{run.agent.mission.text}</Code>
              </div>
            </details>
          </Panel>
        ) : null}
        <Panel title={`Conditions changed · ${run.faults_delivered} fault(s) delivered`}>
          {run.faults.length ? (
            <ul className="flex flex-col gap-1 text-sm leading-6 text-muted">
              {run.faults.map((f, i) => (
                <li key={i}>
                  {FAULT_LABEL[f.kind] ?? humanize(f.kind)}{" "}
                  <span className="font-mono text-xs text-faint">
                    ({f.operation}, occurrence {f.occurrence}
                    {f.span > 1 ? `, span ${f.span}` : ""})
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">No fault was selected for this run.</p>
          )}
        </Panel>
      </div>

      <section aria-label="Reality comparison" className="overflow-hidden rounded-lg border border-line">
        <div className="grid gap-px bg-line md:grid-cols-2">
          <Column tone="agent" title="Agent Reality" note="What the target agent was told" />
          <div className="hidden md:block">
            <Column tone="truth" title="Actual Reality" note="What authoritative state recorded" />
          </div>
        </div>
        <ol className="flex flex-col gap-px bg-line">
          {run.agent.tool_events.map((event) => (
            <CallRow key={event.call_seq} event={event} run={run} />
          ))}
          {run.agent.tool_events.length === 0 ? (
            <li className="bg-surface p-3 text-sm text-muted">The agent made no tool calls.</li>
          ) : null}
        </ol>
        <div className="grid gap-px border-t border-line bg-line md:grid-cols-2">
          <ClaimCard run={run} />
          <OracleCard run={run} />
        </div>
      </section>

      {run.discrepancies.length ? (
        <Discrepancies run={run} />
      ) : (
        <p data-testid="no-discrepancies" className="text-sm text-muted">
          No discrepancy between delivery and authoritative state was recorded in this run.
        </p>
      )}

      <Panel title="Authoritative records">
        <Records run={run} />
      </Panel>
    </div>
  );
}
