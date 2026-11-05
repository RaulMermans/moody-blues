import type { RecordMention, RecordView } from "../model";

const MENTION_LABEL: Record<RecordMention, string | null> = {
  structured_claim: "Named in the structured claim",
  message_only: "Named only in the agent's message",
  not_named: "Not named by the agent",
  not_assessed: null,
};

/** One committed row. A slab is only ever drawn for a real record, and it is never echoed. */
export function RecordSlab({ record }: { record: RecordView }) {
  const { customer, mention } = record;
  const note = MENTION_LABEL[mention];
  return (
    <article
      className="rf-slab"
      data-record={customer.customer_id}
      data-flagged={customer.flagged_duplicate}
      data-testid="record-slab"
    >
      <p className="rf-slab-id">{customer.customer_id}</p>
      <p className="rf-slab-name">
        {customer.name} <span className="rf-slab-email">{customer.email}</span>
      </p>
      <p className="rf-micro rf-slab-meta">
        <span>Committed by call {customer.created_by_call}</span>
        {customer.flagged_duplicate ? <span className="rf-slab-flag">✕ Duplicate</span> : null}
      </p>
      {note ? <p className="rf-slab-note">{note}</p> : null}
    </article>
  );
}
