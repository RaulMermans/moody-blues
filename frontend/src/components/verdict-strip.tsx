import { OracleSeal } from "@/design/components/oracle-seal";
import { sealFromRun, targetNoun } from "@/design/model";
import type { Tested } from "@/design/outcome";
import { stateLine } from "@/design/story";
import type { RealityRun } from "@/lib/evidence-types";

/** The four things a reader needs first: the task, the report, the outcome, and the verdict. */
export function VerdictStrip({ run, tested }: { run: RealityRun; tested: Tested }) {
  const claim = run.agent.claim;
  const noun = targetNoun(run);
  return (
    <dl className="rf-strip" data-testid="outcome-strip">
      <div className="rf-strip-task">
        <dt className="rf-label">Task</dt>
        <dd data-testid="mission" className="rf-strip-body">
          {tested.text}
        </dd>
        {tested.source ? <dd className="rf-strip-note">{tested.source}</dd> : null}
      </div>
      <div data-reality="agent">
        <dt className="rf-label">{noun.charAt(0).toUpperCase() + noun.slice(1)} reported</dt>
        <dd data-testid="strip-claim" className="rf-strip-status">
          {claim ? claim.status : "no valid claim"}
        </dd>
        <dd className="rf-strip-note">
          {claim ? "Structured final status" : "A missing claim is never read as success"}
        </dd>
      </div>
      <div data-reality="actual">
        <dt className="rf-label">Actual outcome</dt>
        <dd data-testid="strip-state" className="rf-strip-state">
          {stateLine(run)}
        </dd>
        <dd className="rf-strip-note">
          Objective {run.actual.objective_satisfied ? "satisfied" : "not satisfied"} in authoritative state
        </dd>
      </div>
      <div className="rf-strip-verdict">
        <dt className="rf-label">Oracle verdict</dt>
        <dd>
          <OracleSeal state={sealFromRun(run)} size="sm" labelTestId="strip-verdict" />
        </dd>
      </div>
    </dl>
  );
}
