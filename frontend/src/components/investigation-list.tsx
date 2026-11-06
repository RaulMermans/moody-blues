import Link from "next/link";

import type { ListedInvestigation } from "@/lib/evidence-types";
import { CASE_LABEL, externalAgent, formatUsd, humanize, modeNote, OUTCOME_LABEL, STRATEGY_LABEL } from "@/lib/labels";
import { referenceTest } from "@/lib/test-catalog";

import { ModeTag, OutcomeTag, Tag } from "./ui";

function Corrupt({ item }: { item: ListedInvestigation }) {
  return (
    <li
      data-testid={`investigation-${item.investigation_id}`}
      data-integrity="corrupt"
      className="flex flex-col gap-1 py-4"
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

function targetLabel(
  summary: NonNullable<ListedInvestigation["summary"]>,
  external: string | null,
  live: boolean,
): string {
  if (summary.target_evidence.includes("local_ollama")) return "External agent on a local model (Ollama)";
  if (live) return `AI agent, ${summary.target_model}`;
  if (!external) return "Reference script, not a model";
  return summary.target_evidence.includes("external_scripted")
    ? "External script, not a model"
    : "External agent on an offline fixture, not a model";
}

function Row({ item }: { item: ListedInvestigation }) {
  const summary = item.summary;
  if (!summary) return <Corrupt item={item} />;
  const reference = referenceTest(summary.target_model);
  const external = externalAgent(summary);
  const title =
    summary.case?.title ??
    reference?.label ??
    (external ? `Test of external agent ${external}` : `${STRATEGY_LABEL[summary.strategy]} investigation`);
  const live = summary.target_evidence.includes("live_provider");
  return (
    <li
      data-testid={`investigation-${item.investigation_id}`}
      data-integrity="verified"
      data-outcome={summary.outcome}
      className="group relative py-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeTag outcome={summary.outcome} />
        {summary.case && CASE_LABEL[summary.case.kind] !== OUTCOME_LABEL[summary.outcome] ? (
          <Tag>{CASE_LABEL[summary.case.kind]}</Tag>
        ) : null}
        <ModeTag mode={summary.mode} note={modeNote(summary)} />
        {summary.world_name ? <Tag testId="investigation-world">{summary.world_name}</Tag> : null}
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
        <p className="mt-1 line-clamp-2 max-w-3xl text-sm leading-6 text-muted">{summary.case.summary}</p>
      ) : null}
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono text-xs text-faint">
        <div className="flex gap-1.5">
          <dt>target</dt>
          <dd className="text-muted">
            {targetLabel(summary, external, live)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt>experiments</dt>
          <dd className="text-muted">{summary.experiment_count}</dd>
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
      className="divide-y divide-line border-y border-line"
    >
      {items.map((item) => (
        <Row key={item.investigation_id} item={item} />
      ))}
    </ul>
  );
}
