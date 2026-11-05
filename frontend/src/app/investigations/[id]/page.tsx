import Link from "next/link";
import { type ReactNode, Suspense } from "react";

import { CopyButton } from "@/components/copy-button";
import { EvidencePanel } from "@/components/evidence-panel";
import { FailurePanel } from "@/components/failure-panel";
import { HashFocus } from "@/components/hash-focus";
import { InvestigatorView } from "@/components/investigator-view";
import { RawEvidence } from "@/components/raw-evidence";
import { RealityView } from "@/components/reality-view";
import { TimelineView } from "@/components/timeline-view";
import { Fact, LoadingPanel, ModeTag, OutcomeTag, Tag } from "@/components/ui";
import { OracleSeal } from "@/design/components/oracle-seal";
import { sealWithoutRun } from "@/design/model";
import {
  getExperiments,
  getInvestigation,
  getRun,
  getRuns,
  getTimeline,
} from "@/lib/evidence";
import type { InvestigationDetail } from "@/lib/evidence-types";
import {
  CASE_LABEL,
  formatDuration,
  formatUsd,
  formatWhen,
  OUTCOME_LABEL,
  STRATEGY_LABEL,
} from "@/lib/labels";

const VIEWS = [
  { key: "reality", label: "Reality Comparison" },
  { key: "timeline", label: "Timeline" },
  { key: "investigator", label: "Investigator" },
  { key: "evidence", label: "Raw evidence" },
] as const;
type View = (typeof VIEWS)[number]["key"];

function asView(value: string | string[] | undefined): View {
  return VIEWS.find((v) => v.key === value)?.key ?? "reality";
}

function titleOf(detail: InvestigationDetail): string {
  const { summary } = detail;
  return summary.case?.title ?? `${STRATEGY_LABEL[summary.strategy]} investigation`;
}

/** Where the reader is. The Reality view states its own result, so only other views repeat a title. */
function Header({ detail, view }: { detail: InvestigationDetail; view: View }) {
  const { summary } = detail;
  return (
    <header className="flex flex-col gap-1 sm:gap-3">
      <div className="rf-crumbs">
        <Link href="/" className="rf-crumb-back">
          <span aria-hidden>←</span> Investigations
        </Link>
        <span className="flex flex-wrap items-center gap-2">
          <OutcomeTag outcome={summary.outcome} testId="outcome" />
          {summary.case && CASE_LABEL[summary.case.kind] !== OUTCOME_LABEL[summary.outcome] ? (
            <span className="flex max-sm:hidden">
              <Tag>{CASE_LABEL[summary.case.kind]}</Tag>
            </span>
          ) : null}
          <ModeTag mode={summary.mode} />
        </span>
      </div>
      {view === "reality" ? null : <h1 className="rf-page-title">{titleOf(detail)}</h1>}
    </header>
  );
}

function About({ detail }: { detail: InvestigationDetail }) {
  const { summary } = detail;
  const study = detail.case_study;
  return (
    <section aria-label="About this investigation" className="flex flex-col gap-4 border-t border-line pt-6">
      <h2 className="rf-section-title">About this investigation</h2>
      <p data-testid="case-title" className="max-w-3xl text-base font-medium text-foreground">
        {titleOf(detail)}
      </p>
      {summary.case ? (
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
        <div className="col-span-2 min-w-0">
          <dt className="text-xs text-faint">Investigation id</dt>
          <dd className="mt-0.5 flex flex-wrap items-center gap-2 font-mono text-sm text-foreground">
            <span data-testid="investigation-id" className="break-all">
              {summary.investigation_id}
            </span>
            <CopyButton value={summary.investigation_id} label="Copy investigation id" />
          </dd>
        </div>
      </dl>
      <p className="text-xs text-faint">Cost: {summary.cost_note}.</p>
    </section>
  );
}

function Tabs({ id, view, runId }: { id: string; view: View; runId: string | undefined }) {
  const run = runId ? `&run=${runId}` : "";
  return (
    <nav aria-label="Investigation views" className="rf-tabs">
      {VIEWS.map((v) => (
        <Link
          key={v.key}
          href={`/investigations/${id}?view=${v.key}${run}`}
          aria-current={view === v.key ? "page" : undefined}
          data-testid={`tab-${v.key}`}
        >
          {v.label}
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
  showAll,
  fixture,
  runId,
  call,
}: {
  id: string;
  showAll: boolean;
  fixture: boolean;
  runId: string | undefined;
  call: number | null;
}) {
  const page = await getTimeline(id);
  if (!page.ok) return <FailurePanel failure={page} />;
  return (
    <TimelineView id={id} page={page.data} showAll={showAll} fixture={fixture} runId={runId} call={call} />
  );
}

async function Investigator({ id, detail }: { id: string; detail: InvestigationDetail }) {
  const experiments = await getExperiments(id);
  if (!experiments.ok) return <FailurePanel failure={experiments} />;
  return <InvestigatorView id={id} detail={detail} experiments={experiments.data.experiments} />;
}

async function Investigation({ params, searchParams }: PageProps<"/investigations/[id]">) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const detail = await getInvestigation(id);
  if (!detail.ok) return <FailurePanel failure={detail} />;
  const view = asView(query.view);
  const runId = typeof query.run === "string" ? query.run : undefined;
  const call = typeof query.call === "string" && /^\d+$/.test(query.call) ? Number(query.call) : null;
  return (
    <>
      <Header detail={detail.data} view={view} />
      <Tabs id={id} view={view} runId={runId} />
      {view === "reality" ? <Reality id={id} detail={detail.data} runId={runId} /> : null}
      {view === "timeline" ? (
        <Timeline
          id={id}
          showAll={query.show === "all"}
          fixture={detail.data.summary.investigator_evidence === "offline_fixture"}
          runId={runId}
          call={call}
        />
      ) : null}
      {view === "investigator" ? <Investigator id={id} detail={detail.data} /> : null}
      {view === "evidence" ? <Evidence id={id} detail={detail.data} runId={runId} /> : null}
      <About detail={detail.data} />
      <EvidencePanel detail={detail.data} />
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
