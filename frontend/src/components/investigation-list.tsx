import Link from "next/link";

import type { ListedInvestigation } from "@/lib/evidence-types";
import { CASE_LABEL, formatDuration, formatUsd, humanize, STRATEGY_LABEL } from "@/lib/labels";

import { ModeTag, OutcomeTag, Tag } from "./ui";

function Corrupt({ item }: { item: ListedInvestigation }) {
  return (
    <li
      data-testid={`investigation-${item.investigation_id}`}
      data-integrity="corrupt"
      className="flex flex-col gap-1 px-4 py-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone="warn">Failed verification</Tag>
        <Link
          href={`/investigations/${item.investigation_id}`}
          className="font-mono text-xs text-muted hover:text-foreground"
        >
          {item.investigation_id}
        </Link>
      </div>
      <p className="text-sm text-muted">
        This record was refused ({humanize(item.problem)}). No result is shown for it.
      </p>
    </li>
  );
}

function Row({ item }: { item: ListedInvestigation }) {
  const summary = item.summary;
  if (!summary) return <Corrupt item={item} />;
  const title = summary.case?.title ?? `${STRATEGY_LABEL[summary.strategy]} investigation`;
  return (
    <li
      data-testid={`investigation-${item.investigation_id}`}
      data-integrity="verified"
      data-outcome={summary.outcome}
      className="group relative px-4 py-4 hover:bg-raised"
    >
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeTag outcome={summary.outcome} />
        {summary.case ? <Tag>{CASE_LABEL[summary.case.kind]}</Tag> : null}
        <ModeTag mode={summary.mode} />
      </div>
      <h3 className="mt-2 text-base font-medium text-foreground">
        <Link
          href={`/investigations/${item.investigation_id}`}
          className="after:absolute after:inset-0 group-hover:text-truth"
        >
          {title}
        </Link>
      </h3>
      {summary.case ? (
        <p className="mt-1 max-w-3xl text-sm leading-6 text-muted">{summary.case.summary}</p>
      ) : null}
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-faint">
        <div className="flex gap-1.5">
          <dt>target</dt>
          <dd className="text-muted">{summary.target_model}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>experiments</dt>
          <dd className="text-muted">{summary.experiment_count}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>verified findings</dt>
          <dd className="text-muted">{summary.verified_finding_count}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt>runtime</dt>
          <dd className="text-muted">{formatDuration(summary.runtime_ms)}</dd>
        </div>
        <div className="flex gap-1.5" title={summary.cost_note}>
          <dt>est. inference</dt>
          <dd className="text-muted">{formatUsd(summary.estimated_cost_usd)}</dd>
        </div>
      </dl>
    </li>
  );
}

export function InvestigationListView({ items }: { items: ListedInvestigation[] }) {
  if (items.length === 0) {
    return (
      <p data-testid="empty-investigations" className="border border-line p-6 text-sm text-muted">
        No investigations are published on this server.
      </p>
    );
  }
  return (
    <ul
      aria-label="Investigations"
      className="divide-y divide-line overflow-hidden border border-line bg-surface"
    >
      {items.map((item) => (
        <Row key={item.investigation_id} item={item} />
      ))}
    </ul>
  );
}
