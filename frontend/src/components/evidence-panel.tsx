import type { InvestigationDetail } from "@/lib/evidence-types";
import { MODE_NOTE } from "@/lib/labels";

import { Chevron, Eyebrow, Fact, Tag } from "./ui";

export function EvidencePanel({ detail }: { detail: InvestigationDetail }) {
  const { provenance, summary } = detail;
  return (
    <section aria-label="Evidence and limits" className="flex flex-col gap-3 border-t border-line pt-6">
      <div className="flex flex-wrap items-center gap-2">
        <Eyebrow>Evidence and limits</Eyebrow>
        <Tag tone="truth" testId="integrity">
          Hash and schema verified on load
        </Tag>
      </div>
      <p className="text-sm text-muted">{MODE_NOTE[summary.mode]}</p>
      <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-muted">
        {detail.limitations.map((limit) => (
          <li key={limit}>{limit}</li>
        ))}
      </ul>
      <details className="border border-line bg-surface p-3">
        <summary className="flex items-center gap-1 text-sm text-muted hover:text-foreground">
          <Chevron /> Provenance
        </summary>
        <dl className="mt-3 grid gap-3">
          <Fact label="Source report sha256">
            <span className="break-all text-xs">{provenance.source_report_sha256}</span>
          </Fact>
          <Fact label={`Journal head sha256 (${provenance.source_journal_records} records)`}>
            <span className="break-all text-xs">{provenance.source_journal_head_sha256}</span>
          </Fact>
          {provenance.experiments.map((e) => (
            <Fact key={e.experiment_id} label={`${e.experiment_id} evidence sha256`}>
              <span className="break-all text-xs">{e.evidence_sha256}</span>
            </Fact>
          ))}
        </dl>
      </details>
    </section>
  );
}
