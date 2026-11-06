import Link from "next/link";

import { OracleSeal } from "@/design/components/oracle-seal";
import { type Cycle, cycleVerdicts, journeyLine } from "@/design/journey";
import { sealWithoutRun } from "@/design/model";
import { explanationFrom } from "@/design/story";
import type { InvestigationDetail, RealityRun } from "@/lib/evidence-types";
import { humanize } from "@/lib/labels";

import { cycleHref } from "./investigator-view";
import { METHOD_HREF } from "./reality-view";
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

export function OverviewView({
  id,
  detail,
  run,
  cycles,
  runId,
}: {
  id: string;
  detail: InvestigationDetail;
  run: RealityRun | null;
  cycles: Cycle[];
  runId?: string;
}) {
  const note = detail.summary.case?.summary;
  const suffix = runId ? `&run=${runId}` : "";
  return (
    <div className="rf-journey" data-testid="overview-view">
      {note ? <p className="rf-lead">{note}</p> : null}
      {run ? (
        <section aria-label="Result" className="rf-stack">
          <VerdictStrip run={run} />
          <Answers detail={detail} run={run} />
        </section>
      ) : (
        <section aria-label="Result" className="rf-stack" data-testid="overview-no-run">
          <OracleSeal state={sealWithoutRun(detail.summary.outcome, detail.integrity)} />
          <p className="rf-body">No target run took place, so nothing here has an Oracle verdict.</p>
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
        <ol className="rf-ladder">
          {cycles.map((cycle) => (
            <li key={cycle.key}>
              <Link href={cycleHref(id, cycle.key, runId)} data-testid={`ladder-${cycle.key}`}>
                <span className="rf-cycle-number">{cycle.hypothesis?.hypothesis_id ?? "—"}</span>
                <span className="rf-ladder-title">
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
