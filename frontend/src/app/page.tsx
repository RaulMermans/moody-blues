import Link from "next/link";
import { Suspense } from "react";

import { FailurePanel } from "@/components/failure-panel";
import { InvestigationListView } from "@/components/investigation-list";
import { StatusPanel } from "@/components/status-panel";
import { HashFocus } from "@/components/hash-focus";
import { Chevron, Eyebrow, LoadingPanel } from "@/components/ui";
import { Headline } from "@/design/components/headline";
import { OracleSeal } from "@/design/components/oracle-seal";
import { sealFromRun } from "@/design/model";
import { disclosureLine, stateLine } from "@/design/story";
import { getRun, listInvestigations } from "@/lib/evidence";
import type { StudyContext } from "@/lib/evidence-types";
import { STRATEGY_LABEL } from "@/lib/labels";

const FLOW = [
  ["Choose a test", "A scenario with a controlled fault."],
  ["Run it", "In an isolated sandbox, against a synthetic world."],
  ["See what happened", "What the target saw and what was really saved."],
  ["Explore the evidence", "Every call, record and hash behind the result."],
] as const;

const REPOSITORY = "https://github.com/RaulMermans/moody-blues/blob/main";
const METHODOLOGY = `${REPOSITORY}/docs/evaluations/methodology.md`;
const QUICKSTART = `${REPOSITORY}/docs/quickstart.md`;
const LIMITATIONS = `${REPOSITORY}/docs/evaluation-and-limitations.md`;

function HowItWorks() {
  return (
    <section id="how" aria-labelledby="how-title" className="rf-how">
      <h2 id="how-title" className="rf-section-title">
        How it works
      </h2>
      <ol className="rf-how-steps">
        {FLOW.map(([title, body]) => (
          <li key={title}>
            <strong>{title}</strong>
            {body}
          </li>
        ))}
      </ol>
      <details id="method" className="rf-fold" data-testid="method">
        <summary>
          <Chevron />
          <span className="rf-fold-title">What a verdict does not show</span>
        </summary>
        <div className="rf-fold-body">
          <p className="rf-body">
            A verdict states what is true of one run&apos;s committed state. It does not say why. A delivered
            fault is exposure, and saying a fault raised the chance of a failure needs a registered contrast
            against a clean control. A rerun is not a control. An investigation record holds no such contrast,
            so its page says that instead of guessing.{" "}
            <a href={METHODOLOGY} className="rf-link">
              Evaluation methodology
            </a>
          </p>
        </div>
      </details>
    </section>
  );
}

function SampleEntry() {
  return (
    <section aria-labelledby="sample-title" className="rf-entry-card" data-testid="entry-sample">
      <p className="rf-label">Free · No AI model</p>
      <h3 id="sample-title">Try a sample test</h3>
      <p className="rf-body">
        A safe rehearsal. A reference script, not an AI agent, works through a controlled failure.
      </p>
      <dl className="rf-entry-facts">
        <div>
          <dt className="rf-label">Target</dt>
          <dd>Reference script</dd>
        </div>
        <div>
          <dt className="rf-label">Cost</dt>
          <dd>Free, no inference</dd>
        </div>
        <div>
          <dt className="rf-label">Tests</dt>
          <dd>Safe recovery, failure detection</dd>
        </div>
        <div>
          <dt className="rf-label">To run one</dt>
          <dd>Operator token</dd>
        </div>
      </dl>
      <Link href="/operator" className="rf-cta rf-cta-quiet" data-testid="hero-sample">
        Choose a test <span aria-hidden>→</span>
      </Link>
      <p className="rf-data" data-testid="own-agent-note">
        No token? Clone the repository and run <code>make quickstart</code>. Your own Python agent connects through
        the{" "}
        <a href={QUICKSTART} className="rf-link">
          SDK and command line
        </a>
        , not through this website.
      </p>
    </section>
  );
}

/** The recorded case a visitor can open now. With none available, it says so by going to the list. */
async function RecordedEntry() {
  const list = await listInvestigations();
  const lead = list.ok
    ? list.data.items.find((i) => i.summary?.case?.kind === "verified_violation")?.summary
    : undefined;
  const primary = lead?.case?.primary_run_id;
  const run = lead && primary ? await getRun(lead.investigation_id, primary) : null;
  const shown = run?.ok ? run.data : null;
  const disclosure = shown ? disclosureLine(shown) : null;
  return (
    <section aria-labelledby="signature" className="rf-entry-card" data-testid="signature">
      <p className="rf-label">Recorded evidence{shown ? ` · ${shown.reported_models.join(", ")}` : ""}</p>
      <h3 id="signature">Explore a real AI investigation</h3>
      <p className="rf-body" data-testid="signature-story">
        An authentic past run of an LLM agent, exported from its records. It is not running now.
      </p>
      {shown && lead ? (
        <>
          <p className="rf-crumb-title">{lead.case?.title}</p>
          <dl className="rf-entry-facts" data-testid="outcome-strip">
            <div>
              <dt className="rf-label">Agent reported</dt>
              <dd data-testid="strip-claim">{shown.agent.claim ? shown.agent.claim.status : "no valid claim"}</dd>
            </div>
            <div>
              <dt className="rf-label">Actual outcome</dt>
              <dd data-testid="strip-state">{stateLine(shown)}</dd>
            </div>
          </dl>
          <div className="flex">
            <OracleSeal state={sealFromRun(shown)} size="sm" labelTestId="strip-verdict" />
          </div>
          {disclosure ? <p className="rf-data">{disclosure}</p> : null}
        </>
      ) : null}
      <Link
        href={lead ? `/investigations/${lead.investigation_id}` : "#investigations"}
        className="rf-cta"
        data-testid="open-signature"
      >
        Open the recorded run <span aria-hidden>→</span>
      </Link>
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
        them. The Investigator stays experimental, and a later local benchmark was inconclusive.{" "}
        <a href={LIMITATIONS} className="rf-link">
          Evaluation and limitations
        </a>
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

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-12 px-4 pb-16 pt-6 sm:px-6 sm:pt-10">
      <header className="rf-hero" data-testid="hero">
        <h1 className="rf-label">MOODY BLUES</h1>
        <Headline as="h2" first="Test what agents do." second="Verify what actually happened." />
        <p className="rf-hero-lead">
          Run agents against controlled failures, catch incorrect outcomes, and reproduce verified issues with
          independent evidence.
        </p>
      </header>

      <div className="rf-entry" data-testid="entry">
        <SampleEntry />
        <Suspense fallback={<div className="rf-signature-hold" />}>
          <RecordedEntry />
        </Suspense>
      </div>

      <HowItWorks />

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

      <StatusPanel />
      <HashFocus />
    </main>
  );
}
