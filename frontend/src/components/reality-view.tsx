import Link from "next/link";
import type { ReactNode } from "react";

import { ComparisonRow } from "@/design/components/comparison-row";
import { DivergenceDivider } from "@/design/components/divergence-divider";
import { Headline } from "@/design/components/headline";
import { RecordSlab } from "@/design/components/record-slab";
import {
  claimRelation,
  divergenceFrom,
  firstDivergence,
  recordsFrom,
  seamFor,
  targetNoun,
} from "@/design/model";
import { relationLine, testedFrom } from "@/design/outcome";
import {
  disclosureLine,
  environmentLine,
  explanationFrom,
  scopeNote,
  stateLine,
  storyFrom,
} from "@/design/story";
import type {
  HypothesisView,
  InvestigationDetail,
  RealityRun,
  RunList,
  ToolEvent,
} from "@/lib/evidence-types";
import { DISCREPANCY_LABEL, FAULT_LABEL, FINDING_CLASS_LABEL, humanize, inRehearsal } from "@/lib/labels";

import { Chevron, Code, TableScroll, Tag, VerdictTag } from "./ui";
import { VerdictStrip } from "./verdict-strip";

const GLYPH = { PASS: "✓", VIOLATION: "✕", INCONCLUSIVE: "?" } as const;

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Where the page says what a verdict can and cannot show. */
export const METHOD_HREF = "/#method";

export function runHref(id: string, runId: string, hash = ""): string {
  return `/investigations/${id}?view=reality&run=${runId}${hash}`;
}

export function traceHref(id: string, runId: string, call: number): string {
  return `/investigations/${id}?view=timeline&show=all&run=${runId}&call=${call}#trace`;
}

export function RunPicker({
  id,
  runs,
  current,
  view = "reality",
}: {
  id: string;
  runs: RunList;
  current: string;
  view?: "reality" | "overview";
}) {
  if (runs.runs.length < 2) return null;
  const hrefOf = (runId: string) =>
    view === "reality" ? runHref(id, runId) : `/investigations/${id}?view=overview&run=${runId}`;
  return (
    <nav aria-label="Target runs" className="rf-runs">
      <ul>
        {runs.runs.map((run, index) => {
          const active = run.run_id === current;
          return (
            <li key={run.run_id}>
              <Link
                href={hrefOf(run.run_id)}
                aria-current={active ? "page" : undefined}
                data-testid={`run-${run.run_id}`}
                data-verdict={run.verdict}
                className="rf-run"
              >
                <span>Run {index + 1}</span>
                <span className="rf-run-world">{run.world_ref}</span>
                <span className="rf-run-verdict">
                  <span aria-hidden>{GLYPH[run.verdict]}</span> {run.verdict}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function faultLabel(kind: string, run: RealityRun): string {
  const label = FAULT_LABEL[kind] ?? humanize(kind);
  return targetNoun(run) === "agent" ? label : inRehearsal(label);
}

export function targetLabel(run: RealityRun): string {
  if (run.target_evidence === "live_provider") {
    return `Target: live model ${run.reported_models.join(", ")}`;
  }
  if (run.target_evidence === "reference_executor") return "Target: reference script, not a model";
  return "Target: offline fixture, not a model";
}

function Summary({
  id,
  detail,
  runs,
  run,
}: {
  id: string;
  detail: InvestigationDetail;
  runs: RunList;
  run: RealityRun;
}) {
  const story = storyFrom(run);
  const disclosure = disclosureLine(run);
  const scope = scopeNote(detail.summary, runs, run);
  const index = runs.runs.findIndex((r) => r.run_id === run.run_id) + 1;
  return (
    <header className="rf-summary" data-testid="outcome-summary">
      <div className="rf-context">
        <p data-testid="run-context">
          Run {index} of {runs.runs.length}
          <span className="rf-wide-only">
            {" "}
            · World {run.world_ref} · {run.config} policy
          </span>
        </p>
        <Tag testId="target-evidence" tone={run.target_evidence === "live_provider" ? "neutral" : "warn"}>
          {targetLabel(run)}
        </Tag>
      </div>
      <Headline
        first={story.reported}
        second={story.reality}
        outOfRegister={story.outOfRegister}
        size="compact"
      />
      <VerdictStrip run={run} tested={testedFrom(run, detail.summary)} />
      <div className="rf-notes">
        {disclosure ? (
          <p data-testid="disclosure" className="rf-note">
            <span className="rf-label">Disclosure</span> {disclosure}
          </p>
        ) : null}
        <p data-testid="environment" className="rf-note">
          <span className="rf-label">Environment</span> {environmentLine(run)}
        </p>
        {scope ? (
          <p data-testid="scope-note" className="rf-note">
            <span className="rf-label">Scope</span> {scope.text}{" "}
            {scope.link ? (
              <Link href={runHref(id, scope.link.runId)} className="rf-link" data-testid="scope-link">
                {scope.link.label}
              </Link>
            ) : null}
          </p>
        ) : null}
      </div>
    </header>
  );
}

function ClaimFacts({ run }: { run: RealityRun }) {
  const claim = run.agent.claim;
  const creates = run.agent.tool_events.filter((e) => e.tool === "create_customer").length;
  if (!claim) {
    return (
      <>
        <p className="rf-value">No valid final claim</p>
        <p className="rf-body">
          The run ended with {humanize(run.agent.termination).toLowerCase()}. A missing claim is never
          read as success.
        </p>
        <p className="rf-data">{plural(creates, "create_customer call", "create_customer calls")} attempted</p>
      </>
    );
  }
  return (
    <>
      <p data-testid="claim-status" className="rf-claim-status">
        status: {claim.status}
      </p>
      <div className="rf-slip">
        <p className="rf-slab-meta">
          {claim.customer_id ? "1 customer id in the structured claim" : "No customer id in the structured claim"}
        </p>
        {claim.customer_id ? <p className="rf-slab-id">{claim.customer_id}</p> : null}
      </div>
      <p className="rf-data">{plural(creates, "create_customer call", "create_customer calls")} attempted</p>
    </>
  );
}

function StateFacts({ run }: { run: RealityRun }) {
  const records = recordsFrom(run);
  const seeded = run.actual.customers.filter((c) => c.role === "seed").length;
  return (
    <>
      <p className="rf-count">
        <span data-testid="record-count" className="rf-count-number">
          {records.length}
        </span>{" "}
        new {records.length === 1 ? "record" : "records"} committed
      </p>
      {records.length ? (
        <div className="rf-slabs">
          {records.map((record) => (
            <RecordSlab
              key={record.customer.customer_id}
              record={record}
              noun={targetNoun(run)}
              callHref={`#call-${record.customer.created_by_call}`}
            />
          ))}
        </div>
      ) : null}
      <p className="rf-data" data-testid="seed-count">
        Plus {plural(seeded, "pre-existing seeded record", "pre-existing seeded records")}, not created
        in this run
      </p>
    </>
  );
}

function ClaimMessage({ run }: { run: RealityRun }) {
  const claim = run.agent.claim;
  if (!claim) return <p className="rf-body">The {targetNoun(run)} wrote no final message.</p>;
  return (
    <p data-testid="claim-message" className="rf-body rf-break">
      {claim.message.text}
      {claim.message.truncated ? " [cut for display]" : ""}
    </p>
  );
}

function OracleCard({ run }: { run: RealityRun }) {
  const violations = run.actual.findings.filter((f) => f.severity === "violation");
  const notes = run.actual.findings.filter((f) => f.severity !== "violation");
  const broken = run.actual.invariants_violated.length;
  const evaluated = run.actual.invariants_evaluated.length;
  return (
    <div id="oracle" data-testid="oracle-card" className="rf-stack">
      <p className="rf-oracle-line">
        <VerdictTag verdict={run.verdict} testId="oracle-verdict" />
        {run.run_outcome ? <span className="rf-data">run outcome: {humanize(run.run_outcome)}</span> : null}
      </p>
      {run.finding_class ? (
        <p className="rf-data">
          {FINDING_CLASS_LABEL[run.finding_class] ?? humanize(run.finding_class)}
          {run.impairments.length ? ` · impaired: ${run.impairments.join(", ")}` : ""}
        </p>
      ) : null}
      {violations.length ? (
        <ul className="rf-findings">
          {violations.map((f) => (
            <li key={f.code} data-testid={`oracle-finding-${f.code}`}>
              <code>{f.code}</code>
              <span>{f.message}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rf-body">No invariant was found broken in this run.</p>
      )}
      <p className="rf-data" data-testid="invariant-count">
        {plural(evaluated, "invariant", "invariants")} evaluated, {broken} broken
      </p>
      {notes.length ? (
        <details className="rf-disclose">
          <summary>
            <Chevron /> {plural(notes.length, "diagnostic note", "diagnostic notes")}
          </summary>
          <ul className="rf-notes-list">
            {notes.map((f, i) => (
              <li key={i} className="rf-break">
                {f.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

/**
 * The status-and-records row repeats the strip above unless it carries the finding. So it stays in view
 * for a violation, where the records are the evidence, and when no earlier row exists. Otherwise it folds.
 */
const outcomeLeads = (run: RealityRun) => run.verdict === "VIOLATION" || firstDivergence(run) === null;

function OutcomeRow({ run }: { run: RealityRun }) {
  const relation = claimRelation(run);
  const noun = targetNoun(run);
  return (
    <ComparisonRow
      title="Outcome"
      agentLabel={`${noun.charAt(0).toUpperCase() + noun.slice(1)}'s final status`}
      actualLabel="What committed"
      agentTestId="claim-card"
      relation={relation}
      tone={seamFor(run, relation)}
      agent={<ClaimFacts run={run} />}
      actual={<StateFacts run={run} />}
    />
  );
}

/** The most important moment first: a recorded mismatch if there is one, and the outcome after it. */
function Comparison({ id, run }: { id: string; run: RealityRun }) {
  const relation = claimRelation(run);
  const first = firstDivergence(run);
  const firstEvent = first ? run.agent.tool_events.find((e) => e.call_seq === first.call_seq) : null;
  const pointTone = seamFor(run, "differs");
  const noun = targetNoun(run);
  const Noun = noun.charAt(0).toUpperCase() + noun.slice(1);
  return (
    <section
      aria-labelledby="comparison-title"
      className="rf-comparison"
      data-divergence={divergenceFrom(run)}
      data-testid="comparison"
    >
      <h2 id="comparison-title" className="sr-only">
        Reality comparison
      </h2>
      <div aria-hidden className="rf-columns">
        <p data-reality="agent">
          {Noun}-reported reality
          <span>What it saw, and what it reported</span>
        </p>
        <p data-reality="actual">
          Authoritative reality
          <span>What actually happened</span>
        </p>
      </div>
      {first ? (
        <ComparisonRow
          title={`First divergence, call ${first.call_seq}`}
          agentLabel={`Tool response · call ${first.call_seq}`}
          actualLabel="Actual operation"
          relation="differs"
          tone={pointTone}
          agent={
            <>
              <p className="rf-value rf-mono rf-break" data-testid="first-told">
                {first.agent_saw}
              </p>
              <p className="rf-data">
                {firstEvent?.tool}
                {firstEvent?.fault_injected ? ` · ${faultLabel(firstEvent.fault_injected, run)}` : ""}
              </p>
            </>
          }
          actual={
            <>
              <p className="rf-value rf-mono rf-break" data-testid="first-actual">
                {first.actually}
              </p>
              <p className="rf-data">
                <Link href={runHref(id, run.run_id, `#call-${first.call_seq}`)} className="rf-link">
                  See this call in the ledger
                </Link>
              </p>
            </>
          }
        />
      ) : null}
      {outcomeLeads(run) ? <OutcomeRow run={run} /> : null}
      <ComparisonRow
        title="Final statement and verdict"
        agentLabel={`In the ${noun}'s words`}
        actualLabel="Oracle verdict"
        relation={relation}
        tone={seamFor(run, relation)}
        agent={<ClaimMessage run={run} />}
        actual={<OracleCard run={run} />}
      />
      <p className="rf-relation" data-testid="relation-line">
        {relationLine(run)}
      </p>
    </section>
  );
}

/** Level 3. Closed by default and reachable by link: a deep link into one opens it. */
function Fold({
  id,
  testId,
  title,
  meta,
  children,
}: {
  id: string;
  testId: string;
  title: string;
  meta: string;
  children: ReactNode;
}) {
  return (
    <details id={id} className="rf-fold" data-testid={testId}>
      <summary>
        <Chevron />
        <span className="rf-fold-title">{title}</span>
        <span className="rf-fold-meta">{meta}</span>
      </summary>
      <div className="rf-fold-body">{children}</div>
    </details>
  );
}

function Explanation({
  detail,
  run,
}: {
  detail: InvestigationDetail;
  run: RealityRun;
}) {
  const primary = detail.summary.case?.primary_run_id === run.run_id;
  const explanation = explanationFrom(run, detail.case_study, primary);
  const { causal } = explanation;
  return (
    <section aria-label="The evidence, explained" className="rf-explain" data-testid="explanation">
      <div className="rf-explain-grid">
        <div>
          <h3>What happened?</h3>
          <p data-testid="explain-happened">{explanation.happened}</p>
        </div>
        <div>
          <h3>Why did it happen?</h3>
          <p data-testid="explain-why">{explanation.why}</p>
        </div>
        <div>
          <h3>Why does it matter?</h3>
          <p data-testid="explain-matters">{explanation.matters}</p>
        </div>
      </div>
      <dl className="rf-causal" data-testid="causal-facts">
        <div>
          <dt className="rf-label">Fault delivered</dt>
          <dd data-testid="causal-fault">{causal.faultDelivered}</dd>
        </div>
        <div>
          <dt className="rf-label">Violation observed</dt>
          <dd data-testid="causal-violation">{causal.violationObserved}</dd>
        </div>
        <div className="rf-causal-wide">
          <dt className="rf-label">Causal evidence</dt>
          <dd data-testid="causal-evidence">{causal.causalEvidence}</dd>
          <dd className="rf-causal-note">
            <Link href={METHOD_HREF} className="rf-link" data-testid="method-link">
              How causal claims are evaluated
            </Link>
          </dd>
          {causal.reproduction ? (
            <dd data-testid="case-study" className="rf-causal-note">
              {causal.reproduction}
            </dd>
          ) : null}
        </div>
      </dl>
    </section>
  );
}

function actualFor(event: ToolEvent, run: RealityRun): string {
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
    return `True response: ${event.actual_summary}${suffix}`;
  }
  if (committed) return `Committed ${committed.customer_id}`;
  if (event.tool === "create_customer") return "Committed nothing";
  return "Delivered as it was";
}

function CallRow({ id, event, run }: { id: string; event: ToolEvent; run: RealityRun }) {
  const differs = event.fault_injected !== null;
  const tone = seamFor(run, differs ? "differs" : "equal");
  return (
    <li
      id={`call-${event.call_seq}`}
      data-testid={`call-${event.call_seq}`}
      data-fault={event.fault_injected ?? ""}
      data-tone={tone}
      className="rf-call"
    >
      <details>
        <summary>
          <span className="rf-call-side">
            <span className="rf-call-head">
              <Chevron />
              <span className="rf-call-seq">#{event.call_seq}</span>
              <span className="rf-call-tool">{event.tool}</span>
              {event.fault_injected ? (
                <span className="rf-call-fault" title={faultLabel(event.fault_injected, run)}>
                  {event.fault_injected}
                </span>
              ) : null}
            </span>
            <span className="rf-call-value">
              <span className="rf-call-label">Told</span> {event.delivered_summary}
            </span>
          </span>
          <DivergenceDivider relation={differs ? "differs" : "equal"} tone={tone} glyph={differs} />
          <span className="rf-call-side">
            <span data-testid={`actual-${event.call_seq}`} className="rf-call-value" data-actual>
              <span className="rf-call-label">Actually</span> {actualFor(event, run)}
            </span>
          </span>
        </summary>
        <div className="rf-call-detail">
          <div className="rf-stack">
            <p className="rf-label">Arguments</p>
            <Code>{event.arguments.text}</Code>
          </div>
          <div className="rf-stack">
            <p className="rf-label">Delivered response</p>
            <Code>{event.delivered.text}</Code>
          </div>
          {event.agent_note ? (
            <p className="rf-body rf-call-note">
              <span className="rf-label">Agent&apos;s note</span> {event.agent_note.text}
            </p>
          ) : null}
          <Link href={traceHref(id, run.run_id, event.call_seq)} className="rf-trace" data-testid="trace-link">
            See this call in the timeline
          </Link>
        </div>
      </details>
    </li>
  );
}

function Ledger({ id, run }: { id: string; run: RealityRun }) {
  const events = run.agent.tool_events;
  return (
    <section aria-label="Every tool call" className="rf-ledger" data-testid="ledger">
      <ol>
        {events.map((event) => (
          <CallRow key={event.call_seq} id={id} event={event} run={run} />
        ))}
        {events.length === 0 ? <li className="rf-body">The agent made no tool calls.</li> : null}
      </ol>
    </section>
  );
}

function discrepancyLine(run: RealityRun): string {
  const counts = new Map<string, number>();
  for (const d of run.discrepancies) counts.set(d.kind, (counts.get(d.kind) ?? 0) + 1);
  return [...counts.entries()]
    .map(([kind, count]) => `${count} ${(DISCREPANCY_LABEL[kind] ?? humanize(kind)).toLowerCase()}`)
    .join(", ");
}

function Discrepancies({ run }: { run: RealityRun }) {
  return (
    <TableScroll label="Discrepancies table">
      <table className="rf-table min-w-[36rem]" data-testid="discrepancies">
        <caption className="sr-only">
          Differences between what the target saw and authoritative state
        </caption>
        <thead>
          <tr>
            <th scope="col">Kind</th>
            <th scope="col">Saw</th>
            <th scope="col">Actually</th>
          </tr>
        </thead>
        <tbody>
          {run.discrepancies.map((d, i) => (
            <tr key={i} data-kind={d.kind}>
              <td>
                {DISCREPANCY_LABEL[d.kind]}
                {d.call_seq !== null ? <span className="block font-mono text-faint">call {d.call_seq}</span> : null}
              </td>
              <td className="font-mono">{d.agent_saw}</td>
              <td className="font-mono">{d.actually}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}

function Records({ run }: { run: RealityRun }) {
  return (
    <section aria-label="Authoritative records" className="rf-records">
      <TableScroll label="Records table">
        <table className="rf-table min-w-[34rem]">
          <caption className="sr-only">Authoritative customer records after the run</caption>
          <thead>
            <tr>
              <th scope="col">Record</th>
              <th scope="col">Name</th>
              <th scope="col">Created by</th>
              <th scope="col">Marks</th>
            </tr>
          </thead>
          <tbody>
            {run.actual.customers.map((c) => (
              <tr key={c.customer_id} data-testid={`record-${c.customer_id}`} data-duplicate={c.flagged_duplicate}>
                <td className="font-mono">{c.customer_id}</td>
                <td>
                  {c.name} <span className="text-faint">{c.email}</span>
                </td>
                <td className="font-mono">{c.role === "seed" ? "seed" : `call ${c.created_by_call}`}</td>
                <td>
                  <span className="flex flex-wrap gap-1">
                    {c.flagged_duplicate ? <Tag tone="bad">duplicate</Tag> : null}
                    {c.named_in_claim ? <Tag>named in claim</Tag> : null}
                    {c.role === "seed" ? <Tag>pre-existing</Tag> : null}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </section>
  );
}

function hypothesisFor(detail: InvestigationDetail, run: RealityRun): HypothesisView | null {
  const observation = detail.observations.find((o) => o.experiment_id === run.experiment_id);
  const proposal = detail.proposals.find((p) => p.proposal_id === observation?.proposal_id);
  return detail.hypotheses.find((h) => h.hypothesis_id === proposal?.hypothesis_id) ?? null;
}

function Deeper({ id, detail, run }: { id: string; detail: InvestigationDetail; run: RealityRun }) {
  const hypothesis = hypothesisFor(detail, run);
  const base = `/investigations/${id}`;
  return (
    <nav aria-label="Go deeper" className="rf-deeper" data-testid="deeper">
      <Link href={`${base}?view=timeline&run=${run.run_id}#trace`} data-testid="deeper-timeline">
        <span>Timeline</span>
        <small>This run in the journal, in order, with record hashes</small>
      </Link>
      <Link
        href={`${base}?view=investigator&run=${run.run_id}${hypothesis ? `#${hypothesis.hypothesis_id}` : ""}`}
        data-testid="deeper-investigator"
      >
        <span>Investigator</span>
        <small>
          {hypothesis ? `Hypothesis ${hypothesis.hypothesis_id}, the one behind this run` : "Hypotheses and generated experiments"}
        </small>
      </Link>
      <Link href={`${base}?view=evidence&run=${run.run_id}`} data-testid="deeper-evidence">
        <span>Raw evidence</span>
        <small>Run record, fault configuration, findings and full task text</small>
      </Link>
    </nav>
  );
}

export function RealityView({
  id,
  detail,
  runs,
  run,
}: {
  id: string;
  detail: InvestigationDetail;
  runs: RunList;
  run: RealityRun;
}) {
  const story = storyFrom(run);
  const events = run.agent.tool_events;
  const faulted = events.filter((e) => e.fault_injected).length;
  const count = run.discrepancies.length;
  return (
    <div className="rf-reality" data-testid="reality-view" data-run={run.run_id} data-story={story.kind}>
      <Summary id={id} detail={detail} runs={runs} run={run} />
      <RunPicker id={id} runs={runs} current={run.run_id} />
      <Comparison id={id} run={run} />
      <section aria-label="Evidence for this run" className="rf-folds">
        {outcomeLeads(run) ? null : (
          <Fold
            id="outcome"
            testId="outcome-panel"
            title="Final status and committed records"
            meta={stateLine(run)}
          >
            <OutcomeRow run={run} />
          </Fold>
        )}
        <Fold
          id="explain"
          testId="explain-panel"
          title="What the evidence does and does not show"
          meta="What happened, the recorded order, causal evidence"
        >
          <Explanation detail={detail} run={run} />
        </Fold>
        <Fold
          id="calls"
          testId="ledger-panel"
          title="Every tool call"
          meta={`${plural(events.length, "call", "calls")}, ${faulted} carrying a delivered fault`}
        >
          <Ledger id={id} run={run} />
        </Fold>
        {count ? (
          <Fold
            id="differences"
            testId="discrepancy-panel"
            title={`${count} discrepanc${count === 1 ? "y" : "ies"}`}
            meta={discrepancyLine(run)}
          >
            <Discrepancies run={run} />
          </Fold>
        ) : (
          <p data-testid="no-discrepancies" className="rf-body">
            No discrepancy between delivery and authoritative state was recorded in this run.
          </p>
        )}
        <Fold
          id="records"
          testId="records-panel"
          title="Authoritative records"
          meta={plural(run.actual.customers.length, "record in the CRM after the run", "records in the CRM after the run")}
        >
          <Records run={run} />
        </Fold>
      </section>
      <Deeper id={id} detail={detail} run={run} />
    </div>
  );
}
