import Link from "next/link";

import type {
  ExperimentView,
  HypothesisView,
  InvestigationDetail,
  ProposalView,
} from "@/lib/evidence-types";
import {
  ADAPTATION_LABEL,
  FINDING_CLASS_LABEL,
  humanize,
  REPRODUCTION_LABEL,
  type Tone,
} from "@/lib/labels";

import { Chevron, Code, Eyebrow, Tag, VerdictTag, TableScroll } from "./ui";

const STATUS_TONE: Record<HypothesisView["status"], Tone> = {
  supported: "bad",
  refuted: "good",
  inconclusive: "warn",
  open: "neutral",
};

const STATUS_LABEL: Record<HypothesisView["status"], string> = {
  supported: "Supported",
  refuted: "Refuted",
  inconclusive: "Inconclusive",
  open: "Not assessed",
};

function Line({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 text-sm leading-6 text-muted">{text}</dd>
    </div>
  );
}

function Program({ proposal }: { proposal: ProposalView }) {
  const adaptation = ADAPTATION_LABEL[proposal.adaptation];
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-foreground">{proposal.label ?? proposal.proposal_id}</span>
        <Tag title={adaptation.note} testId={`adaptation-${proposal.proposal_id}`}>
          {adaptation.title}
        </Tag>
        {proposal.status === "rejected_before_execution" ? (
          <Tag tone="warn">Refused: {humanize(proposal.rejection_problem)}</Tag>
        ) : null}
      </div>
      <p className="text-xs text-faint">{adaptation.note}</p>
      {proposal.rationale ? (
        <dl>
          <Line label="Experiment objective" text={proposal.rationale} />
        </dl>
      ) : null}
      {proposal.motivated_by.length ? (
        <p className="text-xs text-faint">
          Informed by <span className="font-mono text-muted">{proposal.motivated_by.join(", ")}</span>
        </p>
      ) : null}
      {proposal.code ? (
        <details>
          <summary className="flex items-center gap-1 text-sm text-muted hover:text-foreground">
            <Chevron /> Generated Python, as run in the sandbox
          </summary>
          <div className="mt-2">
            <Code>{proposal.code.text}</Code>
            {proposal.code.truncated ? (
              <p className="mt-1 text-xs text-faint">
                Cut to {proposal.code.text.length} of {proposal.code.original_chars} characters.
              </p>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function Hypothesis({
  id,
  hypothesis,
  proposals,
  detail,
  experiments,
  fixture,
}: {
  id: string;
  fixture: boolean;
  hypothesis: HypothesisView;
  proposals: ProposalView[];
  detail: InvestigationDetail;
  experiments: ExperimentView[];
}) {
  const mine = proposals.filter((p) => p.hypothesis_id === hypothesis.hypothesis_id);
  const observations = detail.observations.filter((o) =>
    mine.some((p) => p.proposal_id === o.proposal_id),
  );
  return (
    <li
      id={hypothesis.hypothesis_id}
      data-testid={`hypothesis-${hypothesis.hypothesis_id}`}
      data-status={hypothesis.status}
      className="flex flex-col gap-3 border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm text-foreground">{hypothesis.hypothesis_id}</span>
        <Tag tone={STATUS_TONE[hypothesis.status]}>{STATUS_LABEL[hypothesis.status]}</Tag>
        {hypothesis.revises ? (
          <span className="font-mono text-xs text-faint">follows {hypothesis.revises}</span>
        ) : null}
        <span className="text-xs text-faint">
          {fixture ? "Scripted by a labeled fixture, not a model" : "Written by the Investigator model"}
        </span>
      </div>
      <p className="text-base leading-7 text-foreground">{hypothesis.behavior}</p>
      <dl className="grid gap-3 md:grid-cols-2">
        <Line label="Suspected mechanism" text={hypothesis.suspected_mechanism} />
        <Line label="Why now" text={hypothesis.motivation} />
        <Line label="Predicted observation" text={hypothesis.predicted_observation} />
        <Line label="What separates failure from success" text={hypothesis.failure_discriminator} />
      </dl>
      {mine.map((proposal) => (
        <Program key={proposal.proposal_id} proposal={proposal} />
      ))}
      {observations.map((o) => {
        const experiment = experiments.find((e) => e.experiment_id === o.experiment_id);
        return (
          <div key={o.observation_id} className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <span className="font-mono text-xs text-muted">{o.observation_id}</span>
            <span className="text-sm text-muted">{humanize(o.result_class)}</span>
            {o.verdicts.map((v, i) => (
              <VerdictTag key={i} verdict={v} />
            ))}
            <span className="font-mono text-xs text-faint">{o.faults_delivered} fault(s) delivered</span>
            {experiment?.target_run_ids[0] ? (
              <Link
                href={`/investigations/${id}?view=reality&run=${experiment.target_run_ids[0]}`}
                className="text-sm text-truth hover:underline"
              >
                Compare realities
              </Link>
            ) : null}
          </div>
        );
      })}
      {hypothesis.assessment_reasoning ? (
        <dl className="border-t border-line pt-3">
          <Line
            label={fixture ? "The fixture's assessment" : "The model's assessment"}
            text={hypothesis.assessment_reasoning}
          />
        </dl>
      ) : null}
    </li>
  );
}

export function InvestigatorView({
  id,
  detail,
  experiments,
}: {
  id: string;
  detail: InvestigationDetail;
  experiments: ExperimentView[];
}) {
  const noHypotheses = detail.hypotheses.length === 0;
  const fixture = detail.summary.investigator_evidence === "offline_fixture";
  return (
    <div className="flex flex-col gap-8" data-testid="investigator-view">
      <section className="flex flex-col gap-3">
        <Eyebrow>Hypotheses, in order</Eyebrow>
        {noHypotheses ? (
          <p className="border border-line p-4 text-sm text-muted">
            This strategy runs predetermined programs, so no model wrote a hypothesis.
          </p>
        ) : null}
        <ol className="flex flex-col gap-3">
          {detail.hypotheses.map((h) => (
            <Hypothesis
              key={h.hypothesis_id}
              id={id}
              fixture={fixture}
              hypothesis={h}
              proposals={detail.proposals}
              detail={detail}
              experiments={experiments}
            />
          ))}
        </ol>
      </section>

      {detail.conclusion ? (
        <section className="flex flex-col gap-2">
          <Eyebrow>
            {fixture ? "The fixture's conclusion, scripted" : "The model's conclusion: interpretation, checked below"}
          </Eyebrow>
          <div className="border border-line bg-surface p-4">
            <p className="font-mono text-sm text-foreground">{humanize(detail.conclusion.conclusion)}</p>
            <p className="mt-2 text-sm leading-6 text-muted">{detail.conclusion.reasoning}</p>
          </div>
        </section>
      ) : null}

      {detail.claim_checks.length ? (
        <section className="flex flex-col gap-2">
          <Eyebrow>Claims checked against the Oracle</Eyebrow>
          <ul className="flex flex-col gap-2">
            {detail.claim_checks.map((check, i) => (
              <li key={i} className="border border-line bg-surface p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Tag tone={check.supported ? "truth" : "warn"}>
                    {check.supported ? "Backed by the Oracle" : "Not backed"}
                  </Tag>
                  <span className="font-mono text-xs text-muted">{check.finding_code}</span>
                </div>
                <p className="mt-2 text-sm leading-6 text-muted">{check.statement}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <Eyebrow>Findings, classified by trusted code</Eyebrow>
        <TableScroll label="Findings table" className="border border-line">
          <table className="w-full min-w-[38rem] text-left text-sm" data-testid="findings-table">
            <caption className="sr-only">Every target run and how it was classified</caption>
            <thead className="bg-raised text-xs text-faint">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Run</th>
                <th scope="col" className="px-3 py-2 font-medium">Class</th>
                <th scope="col" className="px-3 py-2 font-medium">Verdict</th>
                <th scope="col" className="px-3 py-2 font-medium">Outcome</th>
                <th scope="col" className="px-3 py-2 font-medium">Reproduction</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line bg-surface">
              {detail.findings.map((f) => (
                <tr key={f.run_id} data-testid={`finding-${f.run_id}`}>
                  <td className="px-3 py-2">
                    <Link
                      href={`/investigations/${id}?view=reality&run=${f.run_id}`}
                      className="font-mono text-xs text-truth hover:underline"
                    >
                      {f.world_ref}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {FINDING_CLASS_LABEL[f.finding_class] ?? f.finding_class}
                  </td>
                  <td className="px-3 py-2">
                    <VerdictTag verdict={f.oracle_verdict} />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-muted">{humanize(f.run_outcome)}</td>
                  <td className="px-3 py-2 text-xs text-muted">
                    {REPRODUCTION_LABEL[f.reproduction] ?? f.reproduction}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
        {detail.findings.length === 0 ? (
          <p className="text-sm text-muted">No target run produced a classified finding.</p>
        ) : null}
      </section>
    </div>
  );
}
