import { OracleSeal } from "@/design/components/oracle-seal";
import { missionLine, sealFromRun } from "@/design/model";
import { stateLine } from "@/design/story";
import type { RealityRun } from "@/lib/evidence-types";

/** The four things a reader needs first: the task, the report, the outcome, and the verdict. */
export function VerdictStrip({ run }: { run: RealityRun }) {
  const claim = run.agent.claim;
  const task = missionLine(run);
  return (
    <dl className="rf-strip" data-testid="outcome-strip">
      <div className="rf-strip-task">
        <dt className="rf-label">Task</dt>
        <dd data-testid="mission" className="rf-strip-body">
          {task ?? "The task text is not in this record."}
        </dd>
      </div>
      <div data-reality="agent">
        <dt className="rf-label">Agent reported</dt>
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
