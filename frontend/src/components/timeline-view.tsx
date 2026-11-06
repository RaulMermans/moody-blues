import Link from "next/link";

import {
  categoryOf,
  eventTitle,
  explainEvent,
  holdsRun,
  isMilestone,
  timelineNodes,
  traceLine,
} from "@/design/journey";
import type { InvestigationDetail, TimelineEntry, TimelinePage, Verdict } from "@/lib/evidence-types";
import { AUTHOR_LABEL, AUTHOR_NOTE, FINDING_CLASS_LABEL, formatClock, humanize, inRehearsal } from "@/lib/labels";

import { Chevron, Fact, VerdictTag } from "./ui";

// The recorded detail is worth a line in these stages. Elsewhere it is empty or a repeat of the title.
const PREVIEW_STAGES = new Set([
  "hypothesis_created",
  "hypothesis_revised",
  "hypothesis_assessed",
  "experiment_generated",
  "conclusion",
  "investigation_finished",
]);

type Focus = "exact" | "run" | null;

function authorLabel(entry: TimelineEntry, fixture: boolean): string {
  return fixture ? inRehearsal(AUTHOR_LABEL[entry.authorship]) : AUTHOR_LABEL[entry.authorship];
}

/** How trusted code classified the verdict's run: a recovery, a shortfall, a violation. */
function verdictNote(entry: TimelineEntry, detail: InvestigationDetail): string | null {
  const finding = detail.findings.find((f) => f.run_id === entry.evidence.run_id);
  const label = finding ? (FINDING_CLASS_LABEL[finding.finding_class] ?? humanize(finding.finding_class)) : null;
  const codes = Array.isArray(entry.facts.finding_codes)
    ? entry.facts.finding_codes.map((c) => humanize(String(c)).toLowerCase())
    : [];
  if (entry.facts.verdict === "VIOLATION" && codes.length) return codes.join(", ");
  return label;
}

function comparisonLabel(entry: TimelineEntry): string {
  return entry.evidence.call_seq !== null
    ? `Open call ${entry.evidence.call_seq} in the Reality Comparison`
    : "Open this run in the Reality Comparison";
}

function Entry({
  id,
  entry,
  detail,
  fixture,
  focus,
  anchor,
  runId,
}: {
  id: string;
  entry: TimelineEntry;
  detail: InvestigationDetail;
  fixture: boolean;
  focus: Focus;
  anchor: boolean;
  runId?: string;
}) {
  const verdict = entry.stage === "oracle_verdict" ? (entry.facts.verdict as Verdict) : null;
  const facts = Object.entries(entry.facts).filter(([, value]) => value !== null);
  const line =
    verdict !== null
      ? verdictNote(entry, detail)
      : entry.detail && PREVIEW_STAGES.has(entry.stage)
        ? entry.detail
        : null;
  const run = runId ? `&run=${runId}` : "";
  const hypothesis = entry.evidence.hypothesis_id;
  return (
    <li
      data-testid={`step-${entry.seq}`}
      data-stage={entry.stage}
      data-authorship={entry.authorship}
      data-verdict={verdict ?? undefined}
      data-focus={focus ?? undefined}
      data-tier={isMilestone(entry) ? "milestone" : "detail"}
      id={anchor ? "trace" : undefined}
      className="rf-step"
    >
      <span id={`event-${entry.seq}`} className="rf-anchor" />
      <details open={focus === "exact"}>
        <summary>
          <span className="rf-step-meta">
            <Chevron />
            <span className="rf-step-category">{fixture ? inRehearsal(categoryOf(entry)) : categoryOf(entry)}</span>
            <time dateTime={entry.at}>{formatClock(entry.at)}</time>
          </span>
          <span className="rf-step-main">
            <span className="rf-step-title">
              {verdict === "VIOLATION" ? (
                <span aria-hidden className="rf-step-mark" data-testid="discrepancy-mark">
                  ≠{" "}
                </span>
              ) : null}
              {fixture ? inRehearsal(eventTitle(entry)) : eventTitle(entry)}
            </span>
            {line ? <span className="rf-step-line">{line}</span> : null}
          </span>
          {verdict ? (
            <span className="rf-step-tag">
              <VerdictTag verdict={verdict} />
            </span>
          ) : null}
        </summary>
        <div className="rf-step-detail">
          <p className="rf-body">{explainEvent(entry, fixture)}</p>
          {entry.detail ? <p className="rf-body rf-step-recorded">{entry.detail}</p> : null}
          <dl className="rf-step-facts">
            <Fact label="Recorded by">
              <span title={AUTHOR_NOTE[entry.authorship]}>
                {authorLabel(entry, fixture)}: {AUTHOR_NOTE[entry.authorship].toLowerCase()}
              </span>
            </Fact>
            <Fact label="Source record">
              {entry.evidence.journal} journal, seq {entry.evidence.journal_seq}
            </Fact>
            {entry.evidence.experiment_id ? <Fact label="Experiment">{entry.evidence.experiment_id}</Fact> : null}
            {facts.map(([key, value]) => (
              <Fact key={key} label={humanize(key)}>
                {typeof value === "string" ? value : JSON.stringify(value)}
              </Fact>
            ))}
            <Fact label="Record hash" className="rf-step-hash">
              <span className="break-all text-xs">{entry.evidence.record_sha256}</span>
            </Fact>
          </dl>
          {entry.at_precision === "run_report" ? (
            <p className="rf-data">
              Tool calls are ordered by call number. The time shown is when the run report was recorded.
            </p>
          ) : null}
          <p className="rf-step-links">
            {entry.evidence.run_id ? (
              <Link
                href={`/investigations/${id}?view=reality&run=${entry.evidence.run_id}${
                  entry.evidence.call_seq !== null ? `#call-${entry.evidence.call_seq}` : ""
                }`}
                className="rf-link"
                data-testid="open-comparison"
              >
                {comparisonLabel(entry)}
              </Link>
            ) : null}
            {hypothesis ? (
              <Link
                href={`/investigations/${id}?view=investigator${run}&cycle=${hypothesis}#${hypothesis}`}
                className="rf-link"
                data-testid="open-hypothesis"
              >
                Open {hypothesis} in the Investigator
              </Link>
            ) : null}
            <Link
              href={`/investigations/${id}?view=timeline${run}&event=${entry.seq}#event-${entry.seq}`}
              className="rf-link"
              data-testid="event-link"
            >
              Link to this event
            </Link>
          </p>
        </div>
      </details>
    </li>
  );
}

export function TimelineView({
  id,
  page,
  detail,
  showAll,
  fixture,
  runId,
  call,
  event,
}: {
  id: string;
  page: TimelinePage;
  detail: InvestigationDetail;
  showAll: boolean;
  fixture: boolean;
  runId?: string;
  call?: number | null;
  event?: number | null;
}) {
  const focusOf = (entry: TimelineEntry): Focus => {
    if (event === entry.seq) return "exact";
    if (!runId || entry.evidence.run_id !== runId) return null;
    return call !== null && call !== undefined && entry.evidence.call_seq === call ? "exact" : "run";
  };
  const anchor =
    page.entries.find((e) => focusOf(e) === "exact") ?? page.entries.find((e) => focusOf(e) === "run");
  const run = runId ? `&run=${runId}` : "";
  const step = (entry: TimelineEntry) => (
    <Entry
      key={entry.seq}
      id={id}
      entry={entry}
      detail={detail}
      fixture={fixture}
      focus={focusOf(entry)}
      anchor={entry === anchor}
      runId={runId}
    />
  );
  const milestones = page.entries.filter(isMilestone).length;
  return (
    <div className="rf-timeline" data-testid="timeline-view">
      {page.entries.length ? (
      <div className="rf-timeline-head">
        <p className="rf-body">
          {showAll
            ? `All ${page.total} records, in the order they were journaled.`
            : `The ${milestones} milestones of ${page.total} records, in recorded order. Open one to see what it means and the record behind it.`}
        </p>
        <Link
          href={`/investigations/${id}?view=timeline${showAll ? "" : "&show=all"}${run}`}
          className="rf-cta rf-cta-quiet"
          data-testid="timeline-scope"
        >
          {showAll ? "Milestones only" : `Show all ${page.total} records`}
        </Link>
      </div>
      ) : (
        <p className="rf-body" data-testid="timeline-empty">
          No event is on record for this investigation.
        </p>
      )}
      <ol aria-label="Investigation timeline" className="rf-steps">
        {showAll
          ? page.entries.map(step)
          : timelineNodes(page.entries).map((node) => {
              if (node.kind === "step") return step(node.entry);
              const focused = node.entries.some((e) => focusOf(e) !== null);
              // Bookkeeping between milestones stays behind "Show all" unless a link points into it.
              if (!holdsRun(node.entries) && !focused) return null;
              return (
                <li key={node.entries[0].seq} className="rf-trace-group" data-testid={`trace-${node.entries[0].seq}`}>
                  <details open={focused}>
                    <summary>
                      <Chevron />
                      <span>{fixture ? inRehearsal(traceLine(node.entries)) : traceLine(node.entries)}</span>
                    </summary>
                    <ol aria-label="Records of this run" className="rf-steps">
                      {node.entries.map(step)}
                    </ol>
                  </details>
                </li>
              );
            })}
      </ol>
    </div>
  );
}
