import Link from "next/link";
import { Suspense } from "react";

import { CopyButton } from "@/components/copy-button";
import { EvidencePanel } from "@/components/evidence-panel";
import { FailurePanel } from "@/components/failure-panel";
import { InvestigatorView } from "@/components/investigator-view";
import { RealityView } from "@/components/reality-view";
import { TimelineView } from "@/components/timeline-view";
import { Eyebrow, Fact, LoadingPanel, ModeTag, OutcomeTag, Tag } from "@/components/ui";
import {
  getExperiments,
  getInvestigation,
  getRun,
  getRuns,
  getTimeline,
} from "@/lib/evidence";
import type { InvestigationDetail } from "@/lib/evidence-types";
import { CASE_LABEL, formatDuration, formatUsd, formatWhen, STRATEGY_LABEL } from "@/lib/labels";

const VIEWS = [
  { key: "reality", label: "Reality Comparison" },
  { key: "timeline", label: "Timeline" },
  { key: "investigator", label: "Investigator" },
] as const;
type View = (typeof VIEWS)[number]["key"];

function asView(value: string | string[] | undefined): View {
  return VIEWS.find((v) => v.key === value)?.key ?? "reality";
}

function Header({ detail }: { detail: InvestigationDetail }) {
  const { summary } = detail;
  const title = summary.case?.title ?? `${STRATEGY_LABEL[summary.strategy]} investigation`;
  const study = detail.case_study;
  return (
    <header className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/" className="mr-1 text-sm text-muted hover:text-foreground">
          ← Investigations
        </Link>
        <OutcomeTag outcome={summary.outcome} testId="outcome" />
        {summary.case ? <Tag>{CASE_LABEL[summary.case.kind]}</Tag> : null}
        <ModeTag mode={summary.mode} />
      </div>
      <h1 className="max-w-4xl text-2xl font-semibold leading-tight tracking-tight text-foreground sm:text-3xl">
        {title}
      </h1>
      {summary.case ? (
        <p className="max-w-4xl text-sm leading-6 text-muted">
          <span className="text-faint">Case note: </span>
          {summary.case.summary}
        </p>
      ) : null}
      <dl className="flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-xs text-faint">
        <div className="flex gap-1.5">
          <dt>target</dt>
          <dd className="text-muted">{summary.target_model}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>strategy</dt>
          <dd className="text-muted">{STRATEGY_LABEL[summary.strategy]}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>experiments</dt>
          <dd className="text-muted">{summary.experiment_count}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>verified findings</dt>
          <dd data-testid="verified-count" className="text-muted">
            {summary.verified_finding_count}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>runtime</dt>
          <dd className="text-muted">{formatDuration(summary.runtime_ms)}</dd>
        </div>
        <div className="flex gap-1.5" title={summary.cost_note}>
          <dt>est. inference</dt>
          <dd className="text-muted">{formatUsd(summary.estimated_cost_usd)}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">Investigation id</dt>
          <dd data-testid="investigation-id" className="break-all text-muted">
            {summary.investigation_id}
          </dd>
          <CopyButton value={summary.investigation_id} label="Copy investigation id" />
        </div>
      </dl>
      {study ? (
        <p data-testid="case-study" className="text-sm text-foreground">
          Reproduced in {study.eligible_reproduced} of {study.eligible_runs} eligible registered
          reruns.
        </p>
      ) : null}
    </header>
  );
}

function About({ detail }: { detail: InvestigationDetail }) {
  const { summary } = detail;
  const study = detail.case_study;
  return (
    <section aria-label="About this investigation" className="flex flex-col gap-3 border-t border-line pt-6">
      <Eyebrow>About this investigation</Eyebrow>
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

function Tabs({ id, view }: { id: string; view: View }) {
  return (
    <nav aria-label="Investigation views" className="flex gap-1 overflow-x-auto border-b border-line">
      {VIEWS.map((v) => (
        <Link
          key={v.key}
          href={`/investigations/${id}?view=${v.key}`}
          aria-current={view === v.key ? "page" : undefined}
          data-testid={`tab-${v.key}`}
          className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
            view === v.key
              ? "border-truth text-foreground"
              : "border-transparent text-muted hover:text-foreground"
          }`}
        >
          {v.label}
        </Link>
      ))}
    </nav>
  );
}

async function Reality({ id, runId }: { id: string; runId: string | undefined }) {
  const runs = await getRuns(id);
  if (!runs.ok) return <FailurePanel failure={runs} />;
  const chosen = runId ?? runs.data.primary_run_id;
  if (!chosen) {
    return (
      <p data-testid="no-runs" className="rounded-lg border border-line p-6 text-sm text-muted">
        No target run took place in this investigation, so there is nothing to compare.
      </p>
    );
  }
  const run = await getRun(id, chosen);
  if (!run.ok) return <FailurePanel failure={run} />;
  return <RealityView id={id} runs={runs.data} run={run.data} />;
}

async function Timeline({
  id,
  showAll,
  fixture,
}: {
  id: string;
  showAll: boolean;
  fixture: boolean;
}) {
  const page = await getTimeline(id);
  if (!page.ok) return <FailurePanel failure={page} />;
  return <TimelineView id={id} page={page.data} showAll={showAll} fixture={fixture} />;
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
  return (
    <>
      <Header detail={detail.data} />
      <Tabs id={id} view={view} />
      {view === "reality" ? <Reality id={id} runId={runId} /> : null}
      {view === "timeline" ? (
        <Timeline
          id={id}
          showAll={query.show === "all"}
          fixture={detail.data.summary.investigator_evidence === "offline_fixture"}
        />
      ) : null}
      {view === "investigator" ? <Investigator id={id} detail={detail.data} /> : null}
      <About detail={detail.data} />
      <EvidencePanel detail={detail.data} />
    </>
  );
}

export default function Page(props: PageProps<"/investigations/[id]">) {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6">
      <Suspense fallback={<LoadingPanel label="Loading this investigation from the evidence API" />}>
        <Investigation {...props} />
      </Suspense>
    </main>
  );
}
