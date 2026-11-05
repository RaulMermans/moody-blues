import Link from "next/link";

import type { Authorship, TimelineEntry, TimelinePage } from "@/lib/evidence-types";
import { AUTHOR_LABEL, AUTHOR_NOTE, AUTHOR_TONE, formatClock } from "@/lib/labels";

import { Chevron, Code, Fact, Tag } from "./ui";

const KEY_STAGES = new Set([
  "investigation_created",
  "hypothesis_created",
  "hypothesis_revised",
  "hypothesis_assessed",
  "experiment_generated",
  "experiment_rejected",
  "fault_delivered",
  "target_run_finished",
  "oracle_verdict",
  "observation",
  "conclusion",
  "investigation_finished",
]);

const PREVIEW_STAGES = new Set([
  "hypothesis_created",
  "hypothesis_revised",
  "hypothesis_assessed",
  "experiment_generated",
  "conclusion",
]);

const RAIL: Record<Authorship, string> = {
  investigator_model: "bg-muted",
  coordinator: "bg-faint",
  sandbox: "bg-faint",
  gateway: "bg-warn",
  target_agent: "bg-agent",
  oracle: "bg-truth",
};

function authorLabel(authorship: Authorship, fixture: boolean): string {
  if (fixture && authorship === "investigator_model") return "Investigator fixture";
  return AUTHOR_LABEL[authorship];
}

function Entry({ id, entry, fixture }: { id: string; entry: TimelineEntry; fixture: boolean }) {
  const verdict = entry.stage === "oracle_verdict" ? String(entry.facts.verdict) : null;
  const facts = Object.entries(entry.facts).filter(([, value]) => value !== null);
  return (
    <li
      data-testid={`step-${entry.seq}`}
      data-stage={entry.stage}
      data-authorship={entry.authorship}
      data-verdict={verdict ?? undefined}
      className="relative pl-6"
    >
      <span aria-hidden className={`absolute left-0 top-2 h-2 w-2 rounded-full ${RAIL[entry.authorship]}`} />
      <details className="rounded border border-transparent hover:border-line">
        <summary className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-2 py-1.5">
          <Chevron />
          <span className="font-mono text-xs text-faint">{formatClock(entry.at)}</span>
          <span
            className={`min-w-0 text-sm ${
              verdict === "VIOLATION" ? "font-semibold text-bad" : "text-foreground"
            }`}
          >
            {entry.title}
          </span>
          <Tag tone={AUTHOR_TONE[entry.authorship]} title={AUTHOR_NOTE[entry.authorship]}>
            {authorLabel(entry.authorship, fixture)}
          </Tag>
          {entry.detail && PREVIEW_STAGES.has(entry.stage) ? (
            <span className="w-full truncate pl-5 text-xs text-faint">{entry.detail}</span>
          ) : null}
        </summary>
        <div className="flex flex-col gap-3 px-2 pb-3 pl-6">
          {entry.detail ? <p className="max-w-3xl text-sm leading-6 text-muted">{entry.detail}</p> : null}
          {facts.length ? <Code>{JSON.stringify(Object.fromEntries(facts), null, 2)}</Code> : null}
          <dl className="grid gap-2 sm:grid-cols-2">
            <Fact label="Source record">
              {entry.evidence.journal} journal, seq {entry.evidence.journal_seq}
            </Fact>
            {entry.evidence.experiment_id ? (
              <Fact label="Experiment">{entry.evidence.experiment_id}</Fact>
            ) : null}
            <div className="sm:col-span-2">
              <Fact label="Record hash">
                <span className="break-all text-xs">{entry.evidence.record_sha256}</span>
              </Fact>
            </div>
          </dl>
          {entry.at_precision === "run_report" ? (
            <p className="text-xs text-faint">
              Tool calls are ordered by call number. The time shown is when the run report was recorded.
            </p>
          ) : null}
          {entry.evidence.run_id ? (
            <Link
              href={`/investigations/${id}?view=reality&run=${entry.evidence.run_id}`}
              className="text-sm text-truth hover:underline"
            >
              Open this run in the Reality Comparison
            </Link>
          ) : null}
        </div>
      </details>
    </li>
  );
}

export function TimelineView({
  id,
  page,
  showAll,
  fixture,
}: {
  id: string;
  page: TimelinePage;
  showAll: boolean;
  fixture: boolean;
}) {
  const entries = showAll ? page.entries : page.entries.filter((e) => KEY_STAGES.has(e.stage));
  return (
    <div className="flex flex-col gap-4" data-testid="timeline-view">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Each entry comes from one journal record of this investigation.{" "}
          <span className="text-faint">Showing {entries.length} of {page.total}.</span>
        </p>
        <Link
          href={`/investigations/${id}?view=timeline${showAll ? "" : "&show=all"}`}
          className="rounded border border-line px-2.5 py-1 text-sm text-muted hover:text-foreground"
        >
          {showAll ? "Key steps only" : `Show all ${page.total} records`}
        </Link>
      </div>
      <ol aria-label="Investigation timeline" className="relative flex flex-col gap-0.5 before:absolute before:bottom-2 before:left-[3px] before:top-2 before:w-px before:bg-line">
        {entries.map((entry) => (
          <Entry key={entry.seq} id={id} entry={entry} fixture={fixture} />
        ))}
      </ol>
    </div>
  );
}
