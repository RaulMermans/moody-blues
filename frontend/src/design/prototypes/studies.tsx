import { DisplayType } from "../components/display-type";
import { DivergenceDivider, DivergenceField } from "../components/divergence-divider";
import { OracleSeal } from "../components/oracle-seal";
import { RealityEcho } from "../components/reality-echo";
import type { ComparisonModel } from "../model";

// Three studies of one recorded run. The evidence is identical; only the visual language changes.

/** Direction A. Overlapping planes, one crack, type that will not sit still. */
export function StudyFracture({ model }: { model: ComparisonModel }) {
  return (
    <DivergenceField state={model.divergence} scale={1.6} className="st-a">
      <div className="st-a-left">
        <p className="rf-micro">Direction A · Reality Fracture</p>
        <DisplayType as="h1" text="Two realities." effect="slice" className="st-a-title" />
        <RealityEcho>
          <div className="rf-slip">
            <p className="rf-micro">The agent filed</p>
            <p className="rf-evidence-word">{model.claim?.status ?? "no valid claim"}</p>
          </div>
        </RealityEcho>
      </div>
      <DivergenceDivider state={model.divergence} scale={1.6} />
      <div className="st-a-right">
        <DisplayType text="One truth." effect="plain" className="st-a-title st-a-title-actual" />
        <div className="rf-count">
          <p className="rf-count-number">{model.newRecords.length}</p>
          <p className="rf-count-caption">new records committed</p>
        </div>
        <OracleSeal state={model.seal} size="sm" />
      </div>
    </DivergenceField>
  );
}

/** Direction B. A perfect reflection that stops being one at the point of disagreement. */
export function StudyMirror({ model }: { model: ComparisonModel }) {
  return (
    <div className="st-b">
      <div className="st-b-row st-b-title">
        <div className="st-b-neg">
          <p className="rf-micro">Direction B · Mirror Corruption</p>
          <h1 className="st-b-word">Reality</h1>
        </div>
        <div className="st-b-pos">
          <p aria-hidden className="st-b-word st-b-flip">
            Reality
          </p>
        </div>
      </div>
      <div className="st-b-row">
        <div className="st-b-neg">
          <p className="st-b-label">Final status</p>
          <p className="st-b-value">{model.claim?.status ?? "no valid claim"}</p>
        </div>
        <div className="st-b-pos">
          <p className="st-b-label">Objective</p>
          <p className="st-b-value">{model.objectiveSatisfied ? "satisfied" : "not satisfied"}</p>
        </div>
      </div>
      <div className="st-b-row st-b-break">
        <div className="st-b-neg">
          <p className="st-b-label">Ids in the claim</p>
          <p className="st-b-number">{model.claimedIdCount}</p>
          <p className="st-b-id">{model.claim?.customerId}</p>
        </div>
        <div className="st-b-pos">
          <p className="st-b-label">New records committed</p>
          <p className="st-b-number">{model.newRecords.length}</p>
          {model.newRecords.map((r) => (
            <p key={r.customer.customer_id} className="st-b-id">
              {r.customer.customer_id}
            </p>
          ))}
        </div>
      </div>
      <div className="st-b-seal">
        <OracleSeal state={model.seal} size="sm" />
      </div>
    </div>
  );
}

/** Direction C. An evidence dossier: rules, numbers, one stamp. */
export function StudyDossier({ model }: { model: ComparisonModel }) {
  return (
    <div className="st-c">
      <header className="st-c-head">
        <p>Direction C · Forensic Brutalism</p>
        <p>
          {model.investigationId} / {model.runId}
        </p>
      </header>
      <h1 className="st-c-title">{model.caseTitle}</h1>
      <div className="st-c-grid">
        <section className="st-c-exhibit">
          <p className="st-c-tag">Exhibit A · Filed claim</p>
          <p className="st-c-number">{model.claimedIdCount}</p>
          <p className="st-c-caption">
            customer id, status <b>{model.claim?.status ?? "no valid claim"}</b>
          </p>
          <p className="st-c-id">{model.claim?.customerId}</p>
        </section>
        <section className="st-c-exhibit st-c-exhibit-wide">
          <p className="st-c-tag">Exhibit B · Committed state</p>
          <p className="st-c-number">{model.newRecords.length}</p>
          <p className="st-c-caption">new records committed</p>
          {model.newRecords.map((r) => (
            <p key={r.customer.customer_id} className="st-c-id">
              {r.customer.customer_id} · call {r.customer.created_by_call}
            </p>
          ))}
        </section>
      </div>
      <ol className="st-c-findings">
        {model.violations.map((finding) => (
          <li key={finding.code}>
            <code>{finding.code}</code> {finding.message}
          </li>
        ))}
      </ol>
      <p className="st-c-stamp">{model.seal.kind === "verdict" ? model.seal.verdict : "NO VERDICT"}</p>
    </div>
  );
}

