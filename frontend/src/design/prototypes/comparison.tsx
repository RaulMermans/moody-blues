import Link from "next/link";

import { MODE_LABEL } from "@/lib/labels";

import { DivergenceDivider, DivergenceField } from "../components/divergence-divider";
import { FractureMarker } from "../components/fracture-marker";
import { OracleSeal } from "../components/oracle-seal";
import { RealityEcho } from "../components/reality-echo";
import { RealityFrame } from "../components/reality-frame";
import { RecordSlab } from "../components/record-slab";
import type { ComparisonModel } from "../model";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function AgentSide({ model }: { model: ComparisonModel }) {
  const { claim } = model;
  return (
    <RealityFrame reality="agent" className="rf-comparison-agent">
      <p className="rf-micro">{claim ? "Final status it filed" : "Final status"}</p>
      <p className="rf-evidence-word" data-testid="claim-status">
        {claim ? claim.status : "no valid claim"}
      </p>
      {claim ? (
        <RealityEcho>
          <div className="rf-slip">
            <p className="rf-micro">
              {plural(model.claimedIdCount, "customer id", "customer ids")} in the structured claim
            </p>
            <p className="rf-slip-id" data-testid="claim-id">
              {claim.customerId ?? "none"}
            </p>
          </div>
        </RealityEcho>
      ) : (
        <p className="rf-copy">
          The run ended as <code className="rf-inline-code">{model.termination}</code>. A missing
          claim is never read as success.
        </p>
      )}
      {model.disclosure ? (
        <p className="rf-disclosure" data-testid="disclosure">
          {model.disclosure}
        </p>
      ) : null}
      {model.phantomWrites.map((phantom) => (
        <div key={phantom.callSeq} className="rf-phantom" data-testid="phantom-write">
          <p className="rf-micro">Phantom write · call {phantom.callSeq}</p>
          <p className="rf-slip-id">{phantom.delivered}</p>
          <p className="rf-phantom-note">Delivered to the agent. Never committed.</p>
        </div>
      ))}
      {claim ? (
        <details className="rf-details">
          <summary>Read the agent&apos;s full message</summary>
          <p className="rf-copy" data-testid="claim-message">
            {claim.message}
            {claim.truncated ? " [cut for display]" : ""}
          </p>
        </details>
      ) : null}
    </RealityFrame>
  );
}

function ActualSide({ model }: { model: ComparisonModel }) {
  const count = model.newRecords.length;
  return (
    <RealityFrame reality="actual" className="rf-comparison-actual">
      <div className="rf-count">
        <p className="rf-count-number" data-testid="record-count">
          {count}
        </p>
        <p className="rf-count-caption">
          new {count === 1 ? "record" : "records"} committed
          <span className="rf-micro">
            Objective {model.objectiveSatisfied ? "satisfied" : "not satisfied"} in authoritative state
          </span>
        </p>
      </div>
      <div className="rf-slabs">
        {model.newRecords.map((record) => (
          <RecordSlab key={record.customer.customer_id} record={record} />
        ))}
      </div>
      <p className="rf-micro" data-testid="seed-count">
        Plus {plural(model.seedRecordCount, "pre-existing seeded record", "pre-existing seeded records")}, not
        created in this run
      </p>
    </RealityFrame>
  );
}

function OracleSlab({ model }: { model: ComparisonModel }) {
  const study = model.caseStudy;
  const broken = model.invariants.filter((i) => !i.held).length;
  return (
    <section aria-label="Oracle verdict" className="rf-oracle" data-testid="oracle-slab">
      <div className="rf-oracle-verdict">
        <p className="rf-micro">Authoritative interpretation</p>
        <OracleSeal state={model.seal} />
      </div>
      <div className="rf-oracle-findings">
        {model.violations.length ? (
          <ul className="rf-oracle-list">
            {model.violations.map((finding) => (
              <li key={finding.code} data-testid="oracle-finding">
                <code>{finding.code}</code>
                <span>{finding.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rf-oracle-empty">No invariant was found broken in this run.</p>
        )}
        {study ? (
          <p className="rf-oracle-study" data-testid="case-study">
            Reproduced in {study.eligible_reproduced} of {study.eligible_runs} eligible registered reruns
            {study.impaired_runs ? `; ${plural(study.impaired_runs, "impaired run was", "impaired runs were")} not counted` : ""}
            . {study.note}
          </p>
        ) : null}
      </div>
      <div className="rf-oracle-invariants">
        <p className="rf-micro">
          {plural(model.invariants.length, "invariant", "invariants")} evaluated · {broken} broken
        </p>
        <ul>
          {model.invariants.map((invariant) => (
            <li key={invariant.name} data-held={invariant.held}>
              <span aria-hidden>{invariant.held ? "✓" : "✕"}</span>
              <code>{invariant.name}</code>
              <span className="rf-oracle-state">{invariant.held ? "held" : "broken"}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function RealityComparison({ model }: { model: ComparisonModel }) {
  const base = `/investigations/${model.investigationId}`;
  const count = model.discrepancies.length;
  return (
    <article className="rf-comparison" data-run={model.runId} data-testid="comparison">
      <header className="rf-comparison-head">
        {model.caseTitle ? <h1 className="rf-comparison-title">{model.caseTitle}</h1> : null}
        <div className="rf-comparison-context">
          <p className="rf-micro" data-testid="provenance">
            {MODE_LABEL[model.mode]} · {model.targetLabel} · World {model.world} · Run {model.runIndex} of{" "}
            {model.runTotal} · {plural(model.faultsDelivered, "fault", "faults")} delivered
          </p>
          {model.task ? (
            <p className="rf-copy">
              <span className="rf-text-strong">The task:</span> {model.task}
            </p>
          ) : null}
        </div>
      </header>

      <DivergenceField state={model.divergence} className="rf-comparison-field">
        <AgentSide model={model} />
        <DivergenceDivider
          state={model.divergence}
          detail={
            <>
              <span className="rf-divider-count" data-testid="discrepancy-count">
                {count}
              </span>
              <span className="rf-micro">recorded {count === 1 ? "discrepancy" : "discrepancies"}</span>
            </>
          }
        />
        <ActualSide model={model} />
      </DivergenceField>

      <OracleSlab model={model} />

      {count ? (
        <section aria-labelledby="fracture-points" className="rf-markers-section">
          <h2 id="fracture-points" className="rf-section-title">
            {model.divergence === "violation" ? "Fracture points" : "Recorded discrepancies"}
          </h2>
          <div className="rf-markers">
            {model.discrepancies.map((discrepancy, index) => (
              <FractureMarker
                key={index}
                discrepancy={discrepancy}
                tone={model.divergence === "violation" ? "fracture" : "distortion"}
              />
            ))}
          </div>
        </section>
      ) : null}

      <nav aria-label="Raw evidence" className="rf-evidence-links">
        <Link href={`${base}?view=reality&run=${model.runId}`} data-testid="raw-evidence">
          Every tool call and record
        </Link>
        <Link href={`${base}?view=timeline`}>Journal timeline</Link>
        <Link href={`${base}?view=investigator`}>Investigator reasoning</Link>
      </nav>
      {model.caseSummary ? (
        <p className="rf-case-note">
          <span className="rf-micro">Case note, editorial</span> {model.caseSummary}
        </p>
      ) : null}
    </article>
  );
}
