import Link from "next/link";

import { OracleSeal } from "@/design/components/oracle-seal";
import { StorySequence } from "@/design/components/story-sequence";
import { type Cycle, cycleVerdicts, journeyLine } from "@/design/journey";
import { sealFromRun, sealWithoutRun } from "@/design/model";
import { conditionLine, outcomeFrom, targetNote, testedFrom, verdictMeaning } from "@/design/outcome";
import { type StepLink, stepsFrom } from "@/design/sequence";
import { disclosureLine, explanationFrom, scopeNote } from "@/design/story";
import type { InvestigationDetail, RealityRun, RunList, Verdict } from "@/lib/evidence-types";
import { isModelEvidence } from "@/lib/evidence-types";
import { formatWhen, humanize, modeNote, STRATEGY_LABEL } from "@/lib/labels";

import { cycleHref } from "./investigator-view";
import { METHOD_HREF, RunPicker, runHref, targetLabel } from "./reality-view";
import { Chevron, Tag, VerdictTag } from "./ui";

/** Level 3 of the result: what the Oracle verified and what is established. Nothing here is hidden from a link. */
function Answers({ detail, run }: { detail: InvestigationDetail; run: RealityRun }) {
  const findings = run.actual.findings.filter((f) => f.severity === "violation");
  return (
    <dl className="rf-answers" data-testid="overview-answers">
      <div>
        <dt className="rf-label">The Oracle verified</dt>
        {findings.length ? (
          findings.map((f) => (
            <dd key={f.code} className="rf-body">
              {humanize(f.code)}: {f.message}.
            </dd>
          ))
        ) : (
          <dd className="rf-body">
            No violation in this run. Objective {run.actual.objective_satisfied ? "satisfied" : "not satisfied"} in
            authoritative state.
          </dd>
        )}
      </div>
      {detail.conclusion ? (
        <div>
          <dt className="rf-label">{detail.summary.investigator_evidence === "offline_fixture" ? "The fixture concluded" : "The model concluded"}</dt>
          <dd className="rf-body">
            {humanize(detail.conclusion.conclusion)}. This is an interpretation, not a verdict.
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

const VERDICTS: Verdict[] = ["VIOLATION", "PASS", "INCONCLUSIVE"];

/** How the runs came out. Counted from the runs themselves, and a zero is left out. */
function Tally({ runs }: { runs: RealityRun[] }) {
  const verdicts = VERDICTS.map((v) => [v, runs.filter((r) => r.verdict === v).length] as const).filter(
    ([, n]) => n > 0,
  );
  return (
    <dl className="rf-tally" data-testid="overview-tally">
      {verdicts.map(([verdict, n]) => (
        <div key={verdict} data-verdict={verdict}>
          <dt className="rf-label">{verdict}</dt>
          <dd data-testid={`tally-${verdict}`}>{n}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The next place to look. Only the Oracle's verdict on the shown run can call it a finding. */
function PrimaryAction({ id, run }: { id: string; run: RealityRun | null }) {
  if (!run) {
    return (
      <Link href={`/investigations/${id}?view=investigator`} className="rf-cta" data-testid="overview-primary">
        Read what the Investigator did <span aria-hidden>→</span>
      </Link>
    );
  }
  return (
    <Link href={runHref(id, run.run_id)} className="rf-cta" data-testid="overview-primary">
      {run.verdict === "VIOLATION" ? "Open the verified finding" : "See the comparison"}{" "}
      <span aria-hidden>→</span>
    </Link>
  );
}

/** Which investigation and run this is, and what kind of evidence. Always in view, never folded. */
function Identity({ detail, run }: { detail: InvestigationDetail; run: RealityRun | null }) {
  const { summary } = detail;
  return (
    <div className="rf-identity" data-testid="overview-identity">
      {run ? (
        <Tag testId="target-evidence" tone={isModelEvidence(run.target_evidence) ? "neutral" : "warn"}>
          {targetLabel(run)}
        </Tag>
      ) : null}
      <p className="rf-data rf-wide-only">{modeNote(summary)}</p>
    </div>
  );
}

function ResultBand({
  id,
  detail,
  run,
  list,
}: {
  id: string;
  detail: InvestigationDetail;
  run: RealityRun;
  list: RunList;
}) {
  const outcome = outcomeFrom(run);
  const tested = testedFrom(run, detail.summary);
  const scope = scopeNote(detail.summary, list, run);
  const disclosure = disclosureLine(run);
  const note = targetNote(run);
  const primary = detail.summary.case?.primary_run_id === run.run_id;
  const { causal } = explanationFrom(run, detail.case_study, primary);
  const index = list.runs.findIndex((r) => r.run_id === run.run_id) + 1;
  return (
    <section aria-label="Result" className="rf-result" data-testid="result" data-verdict={run.verdict}>
        {scope ? (
          <p data-testid="scope-note" className="rf-note rf-scope-lead">
            <span className="rf-label">Scope</span>
            <span>
              {scope.text}{" "}
              {scope.link ? (
                <Link
                  href={`/investigations/${id}?view=overview&run=${scope.link.runId}`}
                  className="rf-link"
                  data-testid="scope-link"
                >
                  {scope.link.label}
                </Link>
              ) : null}
            </span>
          </p>
        ) : null}
      <div className="rf-result-main">
        <div className="rf-result-tested">
          <p className="rf-label">
            What was tested{tested.source ? `, ${tested.source}` : ""} · Run {index} of {list.runs.length}
          </p>
          <p data-testid="tested" className="rf-result-task">
            {tested.text}
          </p>
          <p data-testid="condition" className="rf-result-condition">
            {conditionLine(run)}
          </p>
        </div>
        <div className="rf-result-happened">
          <p className="rf-label">What happened</p>
          <h1 data-testid="outcome-headline" className="rf-outcome">
            {outcome.headline}
          </h1>
          <p data-testid="outcome-support" className="rf-lead">
            {outcome.support}
          </p>
        </div>
      </div>
      <aside aria-label="Verdict" className="rf-result-verdict">
        <p className="rf-label">Oracle verdict</p>
        <OracleSeal state={sealFromRun(run)} labelTestId="oracle-verdict" />
        <p data-testid="verdict-meaning" className="rf-body">
          {verdictMeaning(run)}
        </p>
        {note ? (
          <p data-testid="target-note" className="rf-body">
            {note}
          </p>
        ) : null}
        <PrimaryAction id={id} run={run} />
      </aside>
      <div className="rf-result-notes">
        <p className="rf-note rf-narrow-only">
          <span className="rf-label">Evidence</span>
          <span>{modeNote(detail.summary)}</span>
        </p>
        {disclosure ? (
          <p data-testid="disclosure" className="rf-note">
            <span className="rf-label">Disclosure</span> {disclosure}
          </p>
        ) : null}
        {run.verdict === "VIOLATION" ? (
          <p className="rf-note">
            <span className="rf-label">Cause</span>
            <span>
              <span data-testid="overview-causal">{causal.causalEvidence}</span>{" "}
              {causal.reproduction ? `${causal.reproduction} ` : null}
              <Link href={METHOD_HREF} className="rf-link" data-testid="method-link">
                How causal claims are evaluated
              </Link>
            </span>
          </p>
        ) : null}
      </div>
    </section>
  );
}

export function OverviewView({
  id,
  detail,
  run,
  runs,
  list,
  cycles,
  runId,
}: {
  id: string;
  detail: InvestigationDetail;
  run: RealityRun | null;
  runs: RealityRun[];
  list: RunList;
  cycles: Cycle[];
  runId?: string;
}) {
  const holdsShownRun = (cycle: Cycle) => cycle.trials.some((t) => t.run?.run_id === run?.run_id);
  const shown = run ? cycles.find(holdsShownRun) : undefined;
  const hrefFor = (link: StepLink): string => {
    if (link.to === "cycle") return cycleHref(id, link.cycle, runId);
    const target = run?.run_id ?? "";
    return link.to === "oracle" ? runHref(id, target, "#oracle") : runHref(id, target, `#call-${link.call}`);
  };
  return (
    <div className="rf-journey" data-testid="overview-view">
      <Identity detail={detail} run={run} />
      {run ? (
        <>
          <ResultBand id={id} detail={detail} run={run} list={list} />
          <section aria-labelledby="story-title" className="rf-stack">
            <h2 id="story-title" className="rf-section-title">
              Step by step
            </h2>
            <StorySequence steps={stepsFrom(run, detail, shown)} hrefFor={hrefFor} />
          </section>
        </>
      ) : (
        <section aria-label="Result" className="rf-stack" data-testid="overview-no-run">
          <h1 className="rf-outcome">No target run took place.</h1>
          <OracleSeal state={sealWithoutRun(detail.summary.outcome, detail.integrity)} />
          <p className="rf-body">Nothing here has an Oracle verdict.</p>
          <PrimaryAction id={id} run={null} />
        </section>
      )}
      {runs.length > 1 ? (
        <section aria-labelledby="runs-title" className="rf-stack" data-testid="overview-runs">
          <div className="rf-section-head">
            <h2 id="runs-title" className="rf-section-title">
              All runs in this investigation
            </h2>
            <p className="rf-data">{journeyLine(detail)}</p>
          </div>
          <div className="rf-runs-band">
            <Tally runs={runs} />
            {run ? <RunPicker id={id} runs={list} current={run.run_id} view="overview" /> : null}
          </div>
        </section>
      ) : null}
      <div className="rf-folds">
      {run ? (
        <details className="rf-fold" data-testid="overview-details">
          <summary>
            <Chevron />
            <span className="rf-fold-title">Findings and conclusion</span>
            <span className="rf-fold-meta">What the Oracle verified and what the Investigator concluded</span>
          </summary>
          <div className="rf-fold-body">
            <Answers detail={detail} run={run} />
          </div>
        </details>
      ) : null}
      {cycles.length ? (
        <details className="rf-fold" data-testid="overview-path">
          <summary>
            <Chevron />
            <span className="rf-fold-title">How the investigation got here</span>
            <span className="rf-fold-meta">
              {STRATEGY_LABEL[detail.summary.strategy]} · {formatWhen(detail.summary.started_at)}
            </span>
          </summary>
          <div className="rf-fold-body">
            <ol className="rf-ladder" data-lead={shown ? "true" : undefined}>
              {cycles.map((cycle) => (
                <li key={cycle.key} data-shown={cycle === shown || undefined}>
                  <Link href={cycleHref(id, cycle.key, runId)} data-testid={`ladder-${cycle.key}`}>
                    <span className="rf-cycle-number">{cycle.hypothesis?.hypothesis_id ?? "—"}</span>
                    <span className="rf-ladder-title" title={cycle.hypothesis?.behavior}>
                      {cycle.hypothesis?.behavior ?? cycle.decision.title}
                    </span>
                    <span className="rf-cycle-result">
                      {cycleVerdicts(cycle).map((v, i) => (
                        <VerdictTag key={i} verdict={v} />
                      ))}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
            {shown ? (
              <Link href={cycleHref(id, shown.key, runId)} className="rf-link" data-testid="overview-why">
                How the Investigator reached {shown.hypothesis?.hypothesis_id ?? "this run"}
              </Link>
            ) : null}
          </div>
        </details>
      ) : null}
      </div>
    </div>
  );
}
