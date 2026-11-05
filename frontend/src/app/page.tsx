import Link from "next/link";
import { Suspense } from "react";

import { FailurePanel } from "@/components/failure-panel";
import { InvestigationListView } from "@/components/investigation-list";
import { StatusPanel } from "@/components/status-panel";
import { Eyebrow, LoadingPanel } from "@/components/ui";
import { disclosureLine, VerdictStrip } from "@/components/verdict-strip";
import { getRun, listInvestigations } from "@/lib/evidence";
import type { InvestigationList, StudyContext } from "@/lib/evidence-types";
import { STRATEGY_LABEL } from "@/lib/labels";

const STEPS = [
  {
    title: "Distort",
    body: "Trusted code changes what the agent's tools return: a save that reports failure but committed, a success that rolled back, a read from an old snapshot.",
  },
  {
    title: "Observe",
    body: "A real agent works through the task in a synthetic CRM. Every call, response and final claim is recorded.",
  },
  {
    title: "Verify",
    body: "An independent Oracle reads committed state. It never sees what the agent was told, so a claim cannot change the verdict.",
  },
];

async function Signature({ list }: { list: InvestigationList }) {
  const lead = list.items.find((i) => i.summary?.case?.kind === "verified_violation")?.summary;
  const primary = lead?.case?.primary_run_id;
  if (!lead || !primary) return null;
  const run = await getRun(lead.investigation_id, primary);
  if (!run.ok) return null;
  const disclosure = disclosureLine(run.data);
  return (
    <section aria-labelledby="signature" className="flex flex-col gap-3" data-testid="signature">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="signature" className="text-lg font-semibold text-foreground">
          {lead.case?.title}
        </h2>
        <p className="font-mono text-xs text-faint">
          Recorded run · {run.data.reported_models.join(", ")} · {run.data.world_ref}
        </p>
      </div>
      <VerdictStrip run={run.data} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        {disclosure ? <p className="max-w-2xl text-sm text-muted">{disclosure}</p> : <span />}
        <Link
          href={`/investigations/${lead.investigation_id}`}
          data-testid="open-signature"
          className="rounded bg-truth px-3 py-1.5 text-sm font-medium text-background hover:opacity-90"
        >
          Compare the two realities
        </Link>
      </div>
    </section>
  );
}

function StudyNote({ study }: { study: StudyContext }) {
  const rows = Object.keys(study.units_planned);
  return (
    <section aria-labelledby="study" className="rounded-lg border border-line p-4" data-testid="study-note">
      <Eyebrow>Registered benchmark · {study.manifest_id}</Eyebrow>
      <h2 id="study" className="mt-2 font-mono text-sm text-foreground">
        {study.conclusion}
      </h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
        Adaptive investigation did not beat fixed tests in the registered comparison. MOODY BLUES
        can find and verify real failures; this benchmark does not show that adapting finds more of
        them.
      </p>
      <ul className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-muted">
        {rows.map((strategy) => (
          <li key={strategy}>
            {STRATEGY_LABEL[strategy] ?? strategy}: {study.units_with_verified_discovery[strategy]} of{" "}
            {study.units_planned[strategy]} found a verified failure
          </li>
        ))}
      </ul>
    </section>
  );
}

async function Evidence() {
  const list = await listInvestigations();
  if (!list.ok) return <FailurePanel failure={list} />;
  return (
    <>
      <Signature list={list.data} />
      <section aria-labelledby="investigations" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="investigations" className="text-lg font-semibold text-foreground">
            Investigations
          </h2>
          <p className="text-sm text-muted">
            Recorded runs are real past executions. None of them is running now.
          </p>
        </div>
        <InvestigationListView items={list.data.items} />
      </section>
      {list.data.study ? <StudyNote study={list.data.study} /> : null}
    </>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-10 px-4 py-10 sm:px-6">
      <header className="flex flex-col gap-3">
        <h1 className="font-mono text-sm font-semibold tracking-[0.18em] text-truth">MOODY BLUES</h1>
        <p className="max-w-3xl text-3xl font-semibold leading-tight tracking-tight text-foreground sm:text-4xl">
          What an AI agent believes, checked against what really happened.
        </p>
        <p className="max-w-3xl text-base leading-7 text-muted">
          An autonomous adversarial experimentation system for AI agents. It distorts the tools an
          agent depends on, watches how the agent responds, and has an independent Oracle check its
          claims against authoritative state.
        </p>
      </header>

      <Suspense fallback={<LoadingPanel label="Loading investigations from the evidence API" />}>
        <Evidence />
      </Suspense>

      <section aria-labelledby="how" className="flex flex-col gap-3">
        <h2 id="how" className="text-lg font-semibold text-foreground">
          Environmental distortion
        </h2>
        <ol className="grid gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-3">
          {STEPS.map((step) => (
            <li key={step.title} className="bg-surface p-4">
              <h3 className="text-sm font-semibold text-foreground">{step.title}</h3>
              <p className="mt-1 text-sm leading-6 text-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <StatusPanel />
    </main>
  );
}
