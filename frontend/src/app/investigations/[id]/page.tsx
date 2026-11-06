import Link from "next/link";
import { type ReactNode, Suspense } from "react";

import { CopyButton } from "@/components/copy-button";
import { EvidencePanel } from "@/components/evidence-panel";
import { FailurePanel } from "@/components/failure-panel";
import { HashFocus } from "@/components/hash-focus";
import { InvestigatorView } from "@/components/investigator-view";
import { OverviewView } from "@/components/overview-view";
import { RawEvidence } from "@/components/raw-evidence";
import { RealityView } from "@/components/reality-view";
import { TimelineView } from "@/components/timeline-view";
import { Chevron, Fact, LoadingPanel, ModeTag, OutcomeTag, Tag, VerdictTag } from "@/components/ui";
import { OracleSeal } from "@/design/components/oracle-seal";
import { cyclesFrom, openCycle } from "@/design/journey";
import { sealWithoutRun } from "@/design/model";
import {
  getExperiments,
  getInvestigation,
  getRun,
  getRuns,
  getTimeline,
} from "@/lib/evidence";
import type { InvestigationDetail, RealityRun, RunList } from "@/lib/evidence-types";
import { referenceTest } from "@/lib/test-catalog";
import {
  CASE_LABEL,
  externalAgent,
  formatDuration,
  formatUsd,
  formatWhen,
  modeNote,
  OUTCOME_LABEL,
  STRATEGY_LABEL,
} from "@/lib/labels";

// Four places a reader moves between, named for what they answer. The URLs are the published contract
// and stay exactly as they were: a label changes here, a `?view=` never does.
const TABS = [
  { key: "overview", label: "Result", views: ["overview"] },
  { key: "reality", label: "What happened", views: ["reality"] },
  { key: "investigator", label: "Investigation", views: ["investigator"] },
  { key: "evidence", label: "Evidence", views: ["evidence", "timeline"] },
] as const;
type View = (typeof TABS)[number]["views"][number];
const ALL_VIEWS: readonly View[] = TABS.flatMap((t) => t.views);

function asView(value: string | string[] | undefined): View {
  return ALL_VIEWS.find((v) => v === value) ?? "overview";
}

function titleOf(detail: InvestigationDetail): string {
  const { summary } = detail;
  const external = externalAgent(summary);
  return (
    summary.case?.title ??
    referenceTest(summary.target_model)?.label ??
    (external ? `Test of external agent ${external}` : `${STRATEGY_LABEL[summary.strategy]} investigation`)
  );
}

/** Where the reader is. The investigation's name is always here; Result and What happened own the h1. */
function Header({ detail, view }: { detail: InvestigationDetail; view: View }) {
  const { summary } = detail;
  return (
    <header className="flex flex-col gap-1 sm:gap-3">
      <div className="rf-crumbs">
        <span className="rf-crumb-lead">
          <Link href="/" className="rf-crumb-back">
            <span aria-hidden>←</span> Investigations
          </Link>
          <span className="rf-crumb-id">
            <span data-testid="investigation-id">{summary.investigation_id}</span>
            <CopyButton value={summary.investigation_id} label="Copy investigation id" />
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-2">
          <OutcomeTag outcome={summary.outcome} testId="outcome" />
          {summary.case && CASE_LABEL[summary.case.kind] !== OUTCOME_LABEL[summary.outcome] ? (
            <span className="flex max-sm:hidden">
              <Tag>{CASE_LABEL[summary.case.kind]}</Tag>
            </span>
          ) : null}
          <ModeTag mode={summary.mode} note={modeNote(summary)} />
        </span>
      </div>
      {view === "reality" || view === "overview" ? (
        <p className="rf-crumb-title" data-testid="investigation-title">
          {titleOf(detail)}
        </p>
      ) : (
        <h1 className="rf-page-title">{titleOf(detail)}</h1>
      )}
    </header>
  );
}

function About({ detail, note = true }: { detail: InvestigationDetail; note?: boolean }) {
  const { summary } = detail;
  const study = detail.case_study;
  return (
    <section aria-label="About this investigation" className="flex flex-col gap-4 border-t border-line pt-6">
      <h2 className="rf-section-title">About this investigation</h2>
      {note ? (
        <p data-testid="case-title" className="max-w-3xl text-base font-medium text-foreground">
          {titleOf(detail)}
        </p>
      ) : null}
      {summary.case && note ? (
        <p className="max-w-3xl text-sm leading-6 text-muted">
          <span className="text-faint">Case note, editorial: </span>
          {summary.case.summary}
        </p>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-xs text-faint">Objective given to the Investigator</p>
          <p className="mt-1 text-sm leading-6 text-muted">{detail.objective}</p>
        </div>
        <div>
          <p className="text-xs text-faint">Result statement, written by trusted code at the time</p>
          <p data-testid="statement" className="mt-1 text-sm leading-6 text-muted">
            {detail.statement}
          </p>
        </div>
      </div>
      {study ? (
        <p className="text-sm leading-6 text-muted">
          {study.eligible_reproduced} of {study.eligible_runs} eligible reruns reproduced it
          {study.impaired_runs ? `; ${study.impaired_runs} impaired run was not counted` : ""}.{" "}
          {study.note}
        </p>
      ) : null}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
        <Fact label="Target">{summary.target_model}</Fact>
        <Fact label="Strategy">{STRATEGY_LABEL[summary.strategy]}</Fact>
        <Fact label="Experiments">{summary.experiment_count}</Fact>
        <Fact label="Verified findings">
          <span data-testid="verified-count">{summary.verified_finding_count}</span>
        </Fact>
        <Fact label="Runtime">{formatDuration(summary.runtime_ms)}</Fact>
        <Fact label="Est. inference">{formatUsd(summary.estimated_cost_usd)}</Fact>
        <Fact label="Investigator">
          {summary.investigator_evidence === "offline_fixture"
            ? "labeled fixture, no model"
            : summary.investigator_evidence
              ? summary.investigator_model
              : "none (fixed programs)"}
        </Fact>
        <Fact label="Worlds">{summary.world_ids.join(", ")}</Fact>
        <Fact label="Started">{formatWhen(summary.started_at)}</Fact>
        <Fact label="Ended as">{summary.termination ?? summary.state}</Fact>
      </dl>
      <p className="text-xs text-faint">Cost: {summary.cost_note}.</p>
    </section>
  );
}

function Tabs({ id, view, runId }: { id: string; view: View; runId: string | undefined }) {
  const run = runId ? `&run=${runId}` : "";
  return (
    <nav aria-label="Investigation views" className="rf-tabs">
      {TABS.map((tab) => (
        <Link
          key={tab.key}
          href={`/investigations/${id}?view=${tab.key}${run}`}
          aria-current={(tab.views as readonly View[]).includes(view) ? "page" : undefined}
          data-testid={`tab-${tab.key}`}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}

/** The Evidence tab holds both exact forms of the record: its fields, and the journal in order. */
function EvidenceNav({ id, view, runId }: { id: string; view: View; runId: string | undefined }) {
  const run = runId ? `&run=${runId}` : "";
  const links = [
    { key: "evidence", label: "Raw evidence" },
    { key: "timeline", label: "Timeline" },
  ] as const;
  return (
    <nav aria-label="Evidence views" className="rf-subtabs">
      {links.map((link) => (
        <Link
          key={link.key}
          href={`/investigations/${id}?view=${link.key}${run}`}
          aria-current={view === link.key ? "page" : undefined}
          data-testid={link.key === "timeline" ? "tab-timeline" : "tab-raw"}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}

function NoRun({ detail }: { detail: InvestigationDetail }) {
  return (
    <div data-testid="no-runs" className="flex flex-col gap-4">
      <OracleSeal state={sealWithoutRun(detail.summary.outcome, detail.integrity)} />
      <p className="text-sm text-muted">
        No target run took place in this investigation, so there is nothing to compare.
      </p>
    </div>
  );
}

async function loadRun(id: string, runId: string | undefined) {
  const runs = await getRuns(id);
  if (!runs.ok) return { failure: runs };
  const chosen = runId ?? runs.data.primary_run_id;
  if (!chosen) return { noRun: true as const };
  const run = await getRun(id, chosen);
  if (!run.ok) return { failure: run };
  return { runs: runs.data, run: run.data };
}

/** A failed load still names the page, so the result's absence is never an unlabeled screen. */
function Unavailable({ detail, children }: { detail: InvestigationDetail; children: ReactNode }) {
  return (
    <>
      <h1 className="rf-page-title">{titleOf(detail)}</h1>
      {children}
    </>
  );
}

async function Reality({
  id,
  detail,
  runId,
}: {
  id: string;
  detail: InvestigationDetail;
  runId: string | undefined;
}) {
  const loaded = await loadRun(id, runId);
  if (loaded.failure) {
    return (
      <Unavailable detail={detail}>
        <FailurePanel failure={loaded.failure} />
      </Unavailable>
    );
  }
  if (loaded.noRun) {
    return (
      <Unavailable detail={detail}>
        <NoRun detail={detail} />
      </Unavailable>
    );
  }
  return <RealityView id={id} detail={detail} runs={loaded.runs} run={loaded.run} />;
}

async function Evidence({
  id,
  detail,
  runId,
}: {
  id: string;
  detail: InvestigationDetail;
  runId: string | undefined;
}) {
  const loaded = await loadRun(id, runId);
  if (loaded.failure) return <FailurePanel failure={loaded.failure} />;
  if (loaded.noRun) return <NoRun detail={detail} />;
  return <RawEvidence detail={detail} run={loaded.run} />;
}

async function Timeline({
  id,
  detail,
  showAll,
  runId,
  call,
  event,
}: {
  id: string;
  detail: InvestigationDetail;
  showAll: boolean;
  runId: string | undefined;
  call: number | null;
  event: number | null;
}) {
  const page = await getTimeline(id);
  if (!page.ok) return <FailurePanel failure={page} />;
  return (
    <TimelineView
      id={id}
      page={page.data}
      detail={detail}
      showAll={showAll}
      fixture={detail.summary.investigator_evidence === "offline_fixture"}
      runId={runId}
      call={call}
      event={event}
    />
  );
}

/** Every run of the investigation, because a cycle states what its own run recorded. */
async function loadJourney(id: string, detail: InvestigationDetail) {
  const [experiments, list] = await Promise.all([getExperiments(id), getRuns(id)]);
  if (!experiments.ok) return { failure: experiments };
  if (!list.ok) return { failure: list };
  const loaded = await Promise.all(list.data.runs.map((r) => getRun(id, r.run_id)));
  const runs: RealityRun[] = [];
  for (const run of loaded) {
    if (!run.ok) return { failure: run };
    runs.push(run.data);
  }
  return { list: list.data, runs, cycles: cyclesFrom(detail, experiments.data.experiments, runs, list.data) };
}

async function Investigator({
  id,
  detail,
  runId,
  cycle,
}: {
  id: string;
  detail: InvestigationDetail;
  runId: string | undefined;
  cycle: string | undefined;
}) {
  const journey = await loadJourney(id, detail);
  if (journey.failure) return <FailurePanel failure={journey.failure} />;
  return (
    <InvestigatorView
      id={id}
      detail={detail}
      cycles={journey.cycles}
      opened={openCycle(journey.cycles, cycle, runId)}
      runId={runId}
    />
  );
}

async function Overview({
  id,
  detail,
  runId,
}: {
  id: string;
  detail: InvestigationDetail;
  runId: string | undefined;
}) {
  const journey = await loadJourney(id, detail);
  if (journey.failure) return <FailurePanel failure={journey.failure} />;
  // An unknown run id is the link's mistake, not a fact about the investigation: RunContext names it,
  // and the page keeps the primary run rather than saying no run took place.
  const byId = (id: string | null | undefined) => journey.runs.find((r) => r.run_id === id);
  const run = byId(runId) ?? byId(journey.list.primary_run_id) ?? null;
  return <OverviewView id={id} detail={detail} run={run} runs={journey.runs} list={journey.list} cycles={journey.cycles} runId={runId} />;
}

/** Which run the other views are following, so a tab change never loses it silently. */
async function RunContext({ id, runId, view }: { id: string; runId: string; view: View }) {
  const list = await getRuns(id);
  if (!list.ok) return null;
  return <RunLine id={id} runs={list.data} runId={runId} view={view} />;
}

function RunLine({ id, runs, runId, view }: { id: string; runs: RunList; runId: string; view: View }) {
  const index = runs.runs.findIndex((r) => r.run_id === runId);
  const run = runs.runs[index];
  return (
    <p className="rf-run-context" data-testid="run-following">
      {run ? (
        <>
          <span className="rf-label">Following</span>
          <Link href={`/investigations/${id}?view=reality&run=${runId}`} className="rf-link">
            Run {index + 1} of {runs.runs.length}, {run.world_ref}
          </Link>
          <VerdictTag verdict={run.verdict} />
        </>
      ) : (
        <span>That run is not part of this investigation.</span>
      )}
      <Link href={`/investigations/${id}?view=${view}`} className="rf-link" data-testid="run-clear">
        Clear
      </Link>
    </p>
  );
}

/** The same record on every view, folded: what it holds is reference, and nothing on it qualifies a result. */
function AboutPanel({ detail }: { detail: InvestigationDetail }) {
  return (
    <details className="rf-disclose rf-panel" data-testid="about-panel">
      <summary>
        <Chevron /> About this investigation, its evidence and limits
      </summary>
      <div className="rf-stack rf-about-body">
        <About detail={detail} />
        <EvidencePanel detail={detail} />
      </div>
    </details>
  );
}

async function Investigation({ params, searchParams }: PageProps<"/investigations/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const detail = await getInvestigation(id);
  if (!detail.ok) return <FailurePanel failure={detail} />;
  const view = asView(query.view);
  const runId = typeof query.run === "string" ? query.run : undefined;
  const digits = (value: string | string[] | undefined) =>
    typeof value === "string" && /^\d+$/.test(value) ? Number(value) : null;
  const call = digits(query.call);
  const event = digits(query.event);
  const cycle = typeof query.cycle === "string" ? query.cycle : undefined;
  return (
    <>
      <Header detail={detail.data} view={view} />
      <Tabs id={id} view={view} runId={runId} />
      {view === "evidence" || view === "timeline" ? <EvidenceNav id={id} view={view} runId={runId} /> : null}
      {runId && view !== "reality" ? <RunContext id={id} runId={runId} view={view} /> : null}
      {view === "overview" ? <Overview id={id} detail={detail.data} runId={runId} /> : null}
      {view === "reality" ? <Reality id={id} detail={detail.data} runId={runId} /> : null}
      {view === "timeline" ? (
        <Timeline
          id={id}
          detail={detail.data}
          showAll={query.show === "all"}
          runId={runId}
          call={call}
          event={event}
        />
      ) : null}
      {view === "investigator" ? (
        <Investigator id={id} detail={detail.data} runId={runId} cycle={cycle} />
      ) : null}
      {view === "evidence" ? <Evidence id={id} detail={detail.data} runId={runId} /> : null}
      <AboutPanel detail={detail.data} />
      <HashFocus />
    </>
  );
}

export default function Page(props: PageProps<"/investigations/[id]">) {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-4 pb-10 pt-1 sm:gap-6 sm:pt-3 sm:px-6">
      <Suspense fallback={<LoadingPanel label="Loading this investigation from the evidence API" />}>
        <Investigation {...props} />
      </Suspense>
    </main>
  );
}
