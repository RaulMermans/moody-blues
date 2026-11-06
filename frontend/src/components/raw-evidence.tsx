import Link from "next/link";

import type { InvestigationDetail, RealityRun } from "@/lib/evidence-types";
import { isModelEvidence } from "@/lib/evidence-types";
import { FAULT_LABEL, humanize, inRehearsal } from "@/lib/labels";

import { runHref } from "./reality-view";
import { Code, Fact, TableScroll } from "./ui";

/** Level three: the recorded fields of one run, named as they are in the evidence. */
export function RawEvidence({ detail, run }: { detail: InvestigationDetail; run: RealityRun }) {
  const id = detail.summary.investigation_id;
  return (
    <div className="rf-raw" data-testid="raw-evidence-view" data-run={run.run_id}>
      <p className="rf-body">
        Recorded fields of run <code className="font-mono">{run.run_id}</code>, as they were exported.{" "}
        <Link href={runHref(id, run.run_id)} className="rf-link">
          Back to the comparison of this run
        </Link>
      </p>

      <section aria-labelledby="raw-run">
        <h2 id="raw-run" className="rf-section-title">Run record</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <Fact label="run_id">{run.run_id}</Fact>
          <Fact label="run_ref">{run.run_ref}</Fact>
          <Fact label="experiment_id">{run.experiment_id}</Fact>
          <Fact label="world_ref">{run.world_ref}</Fact>
          <Fact label="scenario_ref">{run.scenario_ref}</Fact>
          <Fact label="config">{run.config}</Fact>
          <Fact label="target_kind">{run.target_kind}</Fact>
          <Fact label="target_evidence">{run.target_evidence}</Fact>
          {run.external ? (
            <>
              <Fact label="external_agent">{`${run.external.name} (${run.external.agent_id}@${run.external.agent_version})`}</Fact>
              <Fact label="adapter_protocol">{run.external.protocol}</Fact>
              <Fact label="execution_mode">{run.external.execution_mode}</Fact>
              <Fact label="model_calls_brokered">{String(run.external.model_calls)}</Fact>
              <Fact label="model_calls_uncertain">{String(run.external.model_calls_uncertain)}</Fact>
              {run.external.model_provider ? (
                <Fact label="model_provider">{run.external.model_provider}</Fact>
              ) : null}
              {run.external.model_digest ? (
                <Fact label="model_digest">
                  <span className="break-all">{run.external.model_digest}</span>
                </Fact>
              ) : null}
              <Fact label="bundle_sha256">{run.external.bundle_sha256}</Fact>
              <Fact label="transcript_sha256">{run.external.transcript_sha256}</Fact>
            </>
          ) : null}
          <Fact label="reported_models">{run.reported_models.join(", ") || "none"}</Fact>
          <Fact label="verdict">{run.verdict}</Fact>
          <Fact label="run_outcome">{run.run_outcome ?? "none"}</Fact>
          <Fact label="finding_class">{run.finding_class ?? "none"}</Fact>
          <Fact label="termination">{run.agent.termination}</Fact>
          <Fact label="recovery_pattern">{run.agent.recovery_pattern ?? "none"}</Fact>
          <Fact label="impairments">{run.impairments.join(", ") || "none"}</Fact>
          <Fact label="objective_satisfied">{String(run.actual.objective_satisfied)}</Fact>
          <Fact label="faults_delivered">{run.faults_delivered}</Fact>
        </dl>
      </section>

      <section aria-labelledby="raw-faults">
        <h2 id="raw-faults" className="rf-section-title">Fault configuration</h2>
        {run.faults.length ? (
          <ul data-testid="fault-list" className="flex flex-col gap-1 text-sm leading-6 text-muted">
            {run.faults.map((f, i) => (
              <li key={i}>
                {isModelEvidence(run.target_evidence) ? (FAULT_LABEL[f.kind] ?? humanize(f.kind)) : inRehearsal(FAULT_LABEL[f.kind] ?? humanize(f.kind))}{" "}
                <span className="font-mono text-xs text-faint">
                  ({f.operation}, occurrence {f.occurrence}
                  {f.span > 1 ? `, span ${f.span}` : ""})
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No fault was selected for this run.</p>
        )}
      </section>

      <section aria-labelledby="raw-findings">
        <h2 id="raw-findings" className="rf-section-title">Oracle findings</h2>
        {run.actual.findings.length ? (
          <TableScroll label="Findings table">
            <table className="rf-table min-w-[40rem]" data-testid="raw-findings">
              <caption className="sr-only">Every finding the Oracle recorded for this run</caption>
              <thead>
                <tr>
                  <th scope="col">Code</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Invariant</th>
                  <th scope="col">Message</th>
                  <th scope="col">Calls</th>
                </tr>
              </thead>
              <tbody>
                {run.actual.findings.map((f, i) => (
                  <tr key={i}>
                    <td className="font-mono">{f.code}</td>
                    <td>{f.severity}</td>
                    <td className="font-mono">{f.invariant ?? "none"}</td>
                    <td>{f.message}</td>
                    <td className="font-mono">{f.call_seqs.join(", ") || "none"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        ) : (
          <p className="text-sm text-muted">The Oracle recorded no finding for this run.</p>
        )}
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          <Fact label="invariants_evaluated">{run.actual.invariants_evaluated.join(", ") || "none"}</Fact>
          <Fact label="invariants_violated">{run.actual.invariants_violated.join(", ") || "none"}</Fact>
        </dl>
      </section>

      <section aria-labelledby="raw-changes">
        <h2 id="raw-changes" className="rf-section-title">Committed changes</h2>
        <Code>{JSON.stringify(run.actual.changes, null, 2)}</Code>
      </section>

      {run.agent.mission ? (
        <section aria-labelledby="raw-mission">
          <h2 id="raw-mission" className="rf-section-title">Full task text</h2>
          <Code>{run.agent.mission.text}</Code>
        </section>
      ) : null}
    </div>
  );
}
