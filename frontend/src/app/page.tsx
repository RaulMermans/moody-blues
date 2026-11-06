import Link from "next/link";
import { Suspense } from "react";

import { FailurePanel } from "@/components/failure-panel";
import { InvestigationListView } from "@/components/investigation-list";
import { StatusPanel } from "@/components/status-panel";
import { Eyebrow, LoadingPanel } from "@/components/ui";
import { VerdictStrip } from "@/components/verdict-strip";
import { Headline } from "@/design/components/headline";
import { disclosureLine } from "@/design/story";
import { getRun, listInvestigations } from "@/lib/evidence";
import type { InvestigationList, StudyContext } from "@/lib/evidence-types";
import { STRATEGY_LABEL } from "@/lib/labels";

const STEPS = [
  {
    title: "Investigate",
    body: "An AI Investigator forms a hypothesis about how an agent could fail, writes a Python experiment to test it, and picks its next step from what it observed.",
  },
  {
    title: "Contain",
    body: "Generated code is untrusted. It runs in a disposable Docker sandbox with no network, and can only request validated actions from trusted code.",
  },
  {
    title: "Distort",
    body: "Trusted code changes what the agent's tools return: a save that reports failure but committed, a success that rolled back, a read from an old snapshot.",
  },
  {
    title: "Observe",
    body: "A real LLM agent works through the task in a synthetic CRM. Every call, response and final claim is recorded.",
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
    <section aria-labelledby="signature" className="rf-signature" data-testid="signature">
      <div className="rf-section-head">
        <h2 id="signature" className="rf-section-title">
          {lead.case?.title}
        </h2>
        <p className="rf-data">
          Recorded run · {run.data.reported_models.join(", ")} · {run.data.world_ref}
        </p>
      </div>
      <p className="rf-lead" data-testid="signature-story">
        {lead.case?.summary}
      </p>
      <VerdictStrip run={run.data} />
      <div className="rf-signature-foot">
        {disclosure ? <p className="rf-body">{disclosure}</p> : <span />}
        <Link
          href={`/investigations/${lead.investigation_id}`}
          data-testid="open-signature"
          className="rf-cta rf-cta-quiet"
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
    <section aria-labelledby="study" className="border-t border-line pt-4" data-testid="study-note">
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
      <section id="investigations" aria-labelledby="investigations-title" className="flex flex-col gap-3">
        <div className="rf-section-head">
          <h2 id="investigations-title" className="rf-section-title">
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

/** The primary action needs a real case to point at. Without one it says so by going to the list. */
async function PrimaryAction() {
  const list = await listInvestigations();
  const lead = list.ok
    ? list.data.items.find((i) => i.summary?.case?.kind === "verified_violation")
    : undefined;
  return (
    <Link
      href={lead ? `/investigations/${lead.investigation_id}` : "#investigations"}
      className="rf-cta"
      data-testid="hero-cta"
    >
      Explore a verified failure <span aria-hidden>→</span>
    </Link>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-16 px-4 pb-16 pt-10 sm:px-6 sm:pt-16">
      <header className="rf-hero" data-testid="hero">
        <h1 className="rf-label">MOODY BLUES</h1>
        <Headline
          as="h2"
          first="What the agent reported."
          second="What reality recorded."
          outOfRegister
          size="poster"
        />
        <p className="rf-hero-lead">
          MOODY BLUES investigates the gap between an AI agent&apos;s reported outcome and what
          actually happened.
        </p>
        <div className="rf-hero-actions">
          <Suspense
            fallback={
              <Link href="#investigations" className="rf-cta" data-testid="hero-cta">
                Explore a verified failure <span aria-hidden>→</span>
              </Link>
            }
          >
            <PrimaryAction />
          </Suspense>
          <Link href="#how" className="rf-cta rf-cta-quiet" data-testid="hero-how">
            How it works
          </Link>
        </div>
      </header>

      <Suspense
        fallback={
          // Holds the space the evidence will take, so what follows does not jump when it streams in.
          <div className="min-h-screen">
            <LoadingPanel label="Loading investigations from the evidence API" />
          </div>
        }
      >
        <Evidence />
      </Suspense>

      <section id="how" aria-labelledby="how-title" className="rf-how">
        <h2 id="how-title" className="rf-section-title">
          How it works
        </h2>
        <p className="rf-lead">
          MOODY BLUES is an autonomous adversarial experimentation system. An AI Investigator designs
          experiments, a sandbox contains them, and an independent Oracle checks the agent&apos;s claims
          against authoritative state.
        </p>
        <ol>
          {STEPS.map((step) => (
            <li key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <StatusPanel />
    </main>
  );
}
