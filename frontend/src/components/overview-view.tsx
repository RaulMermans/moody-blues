import Link from "next/link";

import { OracleSeal } from "@/design/components/oracle-seal";
import { type Cycle, cycleVerdicts, journeyLine } from "@/design/journey";
import { sealWithoutRun } from "@/design/model";
import { explanationFrom, scopeNote } from "@/design/story";
import type { InvestigationDetail, RealityRun, RunList, Verdict } from "@/lib/evidence-types";
import { formatWhen, humanize, MODE_NOTE, STRATEGY_LABEL } from "@/lib/labels";

import { cycleHref } from "./investigator-view";
import { METHOD_HREF, runHref } from "./reality-view";
import { VerdictTag } from "./ui";
import { VerdictStrip } from "./verdict-strip";

const OVERVIEW_LINKS = [
  ["reality", "Reality Comparison", "What the agent reported against what was recorded, event by event"],
  ["timeline", "Timeline", "Every milestone in order, with the record behind it"],
  ["investigator", "Investigator", "Each hypothesis, experiment, observation and decision"],
  ["evidence", "Raw evidence", "The recorded fields themselves"],
] as const;

function Answers({ detail, run }: { detail: InvestigationDetail; run: RealityRun }) {
  const { causal } = explanationFrom(run, detail.case_study, true);
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
          <dt className="rf-label">The model concluded</dt>
          <dd className="rf-body">
            {humanize(detail.conclusion.conclusion)}. This is an interpretation, not a verdict.
          </dd>
        </div>
      ) : null}
      <div>
        <dt className="rf-label">Causal evidence</dt>
        <dd className="rf-body" data-testid="overview-causal">
          {causal.causalEvidence}
        </dd>
        {causal.reproduction ? <dd className="rf-data">{causal.reproduction}</dd> : null}
        <dd>
          <Link href={METHOD_HREF} className="rf-link" data-testid="method-link">
            How causal claims are evaluated
          </Link>
        </dd>
      </div>
    </dl>
  );
}

/** Which investigation this is. The mode note stands here because the limits below are folded. */
function Identity({ detail }: { detail: InvestigationDetail }) {
  const { summary } = detail;
  return (
    <div className="rf-identity" data-testid="overview-identity">
      <p className="rf-data">
        {summary.target_model} · {STRATEGY_LABEL[summary.strategy]} · {summary.world_ids.join(", ")} ·{" "}
        {formatWhen(summary.started_at)}
      </p>
      <p className="rf-data">{MODE_NOTE[summary.mode]}</p>
    </div>
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
function NextStep({
  id,
  run,
  cycle,
  runId,
}: {
  id: string;
  run: RealityRun | null;
  cycle: Cycle | undefined;
  runId?: string;
}) {
  const label = cycle?.hypothesis?.hypothesis_id ?? "this run";
  return (
    <nav aria-label="Next step" className="rf-next" data-testid="overview-next">
      {run ? (
        <Link href={runHref(id, run.run_id)} className="rf-cta" data-testid="overview-primary">
          {run.verdict === "VIOLATION" ? "Open the verified finding" : "Compare the report with the record"}{" "}
          <span aria-hidden>→</span>
        </Link>
      ) : (
        <Link href={`/investigations/${id}?view=investigator`} className="rf-cta" data-testid="overview-primary">
          Read what the Investigator did <span aria-hidden>→</span>
        </Link>
      )}
      {cycle ? (
        <Link href={cycleHref(id, cycle.key, runId)} className="rf-cta rf-cta-quiet" data-testid="overview-why">
          How the Investigator reached {label}
        </Link>
      ) : null}
    </nav>
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
  const note = detail.summary.case?.summary;
  const suffix = runId ? `&run=${runId}` : "";
  const holdsShownRun = (cycle: Cycle) => cycle.trials.some((t) => t.run?.run_id === run?.run_id);
  const shown = run ? cycles.find(holdsShownRun) : undefined;
  const scope = run ? scopeNote(detail.summary, list, run) : null;
  return (
    <div className="rf-journey" data-testid="overview-view">
      <Identity detail={detail} />
      {note ? <p className="rf-lead">{note}</p> : null}
      {run ? (
        <section aria-label="Result" className="rf-stack">
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
          <VerdictStrip run={run} />
          <Answers detail={detail} run={run} />
          <NextStep id={id} run={run} cycle={shown} runId={runId} />
        </section>
      ) : (
        <section aria-label="Result" className="rf-stack" data-testid="overview-no-run">
          <OracleSeal state={sealWithoutRun(detail.summary.outcome, detail.integrity)} />
          <p className="rf-body">No target run took place, so nothing here has an Oracle verdict.</p>
          <NextStep id={id} run={null} cycle={undefined} runId={runId} />
        </section>
      )}
      {cycles.length ? (
      <section aria-labelledby="path-title" className="rf-stack">
        <div className="rf-section-head">
          <h2 id="path-title" className="rf-section-title">
            How it got there
          </h2>
          <p className="rf-data">{journeyLine(detail)}</p>
        </div>
        <Tally runs={runs} />
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
      </section>
      ) : null}
      <nav aria-label="Go deeper" className="rf-deeper rf-deeper-four">
        {OVERVIEW_LINKS.map(([view, label, note]) => (
          <Link key={view} href={`/investigations/${id}?view=${view}${suffix}`}>
            <span>{label}</span>
            <small>{note}</small>
          </Link>
        ))}
      </nav>
    </div>
  );
}
