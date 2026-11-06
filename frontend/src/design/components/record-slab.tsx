import type { RecordMention, RecordView } from "../model";

const MENTION_LABEL: Record<RecordMention, string | null> = {
  structured_claim: "Named in the structured claim",
  message_only: "Named only in the agent's message",
  not_named: "Not named by the agent",
  not_assessed: null,
};

/**
 * One committed row. A slab is only ever drawn for a real record, so a count of slabs is a count of
 * records. The extra record of a duplicate slips out of line as a whole: no second outline, nothing
 * layered, the text untouched. That is the only displacement a record ever gets.
 */
export function RecordSlab({ record, callHref }: { record: RecordView; callHref?: string }) {
  const { customer, mention, extra } = record;
  const note = MENTION_LABEL[mention];
  return (
    <article
      className="rf-slab"
      data-record={customer.customer_id}
      data-flagged={customer.flagged_duplicate}
      data-extra={extra}
      data-testid="record-slab"
    >
      <p className="rf-slab-id">{customer.customer_id}</p>
      <p className="rf-slab-name">
        {customer.name} <span className="rf-slab-email">{customer.email}</span>
      </p>
      <p className="rf-slab-meta">
        <span>
          Committed by{" "}
          {callHref ? (
            <a href={callHref} className="rf-link" data-testid="record-call-link">
              call {customer.created_by_call}
            </a>
          ) : (
            `call ${customer.created_by_call}`
          )}
        </span>
        {customer.flagged_duplicate ? <span className="rf-slab-flag">✕ Duplicate</span> : null}
      </p>
      {note ? <p className="rf-slab-note">{note}</p> : null}
    </article>
  );
}
