import Link from "next/link";
import type { ReactNode } from "react";

import { OracleSeal } from "@/design/components/oracle-seal";
import {
  assessmentCheck,
  type Cycle,
  cycleVerdicts,
  journeyLine,
  plainQuestion,
  type Trial,
} from "@/design/journey";
import { sealFromRun, targetNoun } from "@/design/model";
import { stateLine, storyFrom } from "@/design/story";
import type { AssessmentCheck, HypothesisView, InvestigationDetail, ProposalView } from "@/lib/evidence-types";
import {
  ADAPTATION_LABEL,
  FAULT_LABEL,
  inRehearsal,
  FINDING_CLASS_LABEL,
  humanize,
  REPRODUCTION_LABEL,
} from "@/lib/labels";

import { ClampText } from "./clamp-text";
import { runHref } from "./reality-view";
import { Chevron, Code, TableScroll, Tag, VerdictTag } from "./ui";

const STATUS_LABEL: Record<HypothesisView["status"], string> = {
  supported: "supported",
  refuted: "refuted",
  inconclusive: "inconclusive",
  not_exercised: "not exercised",
  open: "not assessed",
};

const FLOW = ["Hypothesis", "Experiment", "Observation", "Decision"];

const ASSESSMENT_LABEL: Record<Exclude<AssessmentCheck["outcome"], "accepted">, string> = {
  not_exercised: "Undelivered fault",
  contradicts_oracle: "Contradicts the Oracle",
  conflicting: "Conflicting assessments",
  no_target_run: "Cites no run",
  unknown_evidence: "Cites unknown evidence",
};

type ReasoningRow = { key: string; kind: string; label: string; text: string };

// Rows come from typed checks only. Nothing here reads what the model wrote.
function reasoningRows(detail: InvestigationDetail, cycles: Cycle[], reader: string): ReasoningRow[] {
  const validity = detail.validity;
  if (!validity) return [];
  const rows: ReasoningRow[] = [];
  if (validity.conclusion_matches_findings === false) {
    rows.push({
      key: "conclusion",
      kind: "unsupported_finding",
      label: "Unsupported finding",
      text: `The ${reader}'s conclusion does not match the verified findings. The findings stand.`,
    });
  }
  validity.assessments.forEach((check, i) => {
    if (check.outcome !== "accepted") {
      rows.push({
        key: `assessment-${i}`,
        kind: check.outcome,
        label: ASSESSMENT_LABEL[check.outcome],
        text: `${check.hypothesis_id} was stated as ${check.claimed_status}. The records allow ${check.effective_status.replace("_", " ")}.`,
      });
    } else if (check.effective_status === "supported" && check.strength !== "paired_contrast_observed") {
      rows.push({
        key: `assessment-${i}`,
        kind: "correlation_only",
        label: "Correlation only",
        text: `${check.hypothesis_id} stands as supported, with no paired run without the fault. That is not a cause.`,
      });
    }
  });
  validity.repeated_hypotheses.forEach((repeat) => {
    rows.push({
      key: `repeat-${repeat.hypothesis_id}`,
      kind: "repeated_hypothesis",
      label: "Repeated hypothesis",
      text: `${repeat.hypothesis_id} repeats ${repeat.repeats}.`,
    });
  });
  validity.experiments
    .filter((e) => e.classification === "not_exercised")
    .forEach((e) => {
      rows.push({
        key: `undelivered-${e.experiment_id}`,
        kind: "undelivered_fault",
        label: "Undelivered fault",
        text: `The fault chosen for ${e.experiment_id} never fired, so that run tested nothing about it.`,
      });
    });
  const refused = cycles.flatMap((c) => c.proposals).filter((p) => p.status === "rejected_before_execution");
  if (refused.length) {
    rows.push({
      key: "invalid",
      kind: "invalid_experiment",
      label: "Invalid experiment",
      text: `${refused.length} proposal${refused.length === 1 ? " was" : "s were"} refused before running.`,
    });
  }
  return rows;
}

function ReasoningChecks({ detail, cycles, fixture }: { detail: InvestigationDetail; cycles: Cycle[]; fixture: boolean }) {
  if (!detail.validity) return null;
  const reader = fixture ? "fixture" : "model";
  const rows = reasoningRows(detail, cycles, reader);
  return (
    <section aria-labelledby="reasoning-title" className="rf-stack" data-testid="reasoning-checks">
      <h2 id="reasoning-title" className="rf-section-title">
        Reasoning checks
      </h2>
      <p className="rf-body rf-measure">
        These compare the {reader}&apos;s reading with the records. They are not Oracle verdicts and change none.
      </p>
      {rows.length ? (
        <ul className="rf-checks">
          {rows.map((row) => (
            <li key={row.key} data-testid="reasoning-check" data-kind={row.kind}>
              <p className="rf-stage-program">
                <Tag tone="warn">{row.label}</Tag>
              </p>
              <p className="rf-body rf-measure">{row.text}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rf-body" data-testid="reasoning-clean">
          No check flagged anything in this investigation.
        </p>
      )}
    </section>
  );
}

export function cycleHref(id: string, key: string, runId?: string): string {
  return `/investigations/${id}?view=investigator${runId ? `&run=${runId}` : ""}&cycle=${key}#${key}`;
}

function Stage({
  label,
  source,
  id,
  children,
}: {
  label: string;
  source: string;
  id?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="rf-stage" data-stage={label.toLowerCase()}>
      <div className="rf-stage-head">
        <h3>{label}</h3>
        <p>{source}</p>
      </div>
      <div className="rf-stage-body">{children}</div>
    </section>
  );
}

function Line({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <dt className="rf-label">{label}</dt>
      <dd className="rf-body">{text}</dd>
    </div>
  );
}

/** The reason for a step is recorded with the step before it, so a reader arriving here gets a way back. */
function ledHere(cycle: Cycle, cycles: Cycle[]): Cycle | undefined {
  return cycles.find((c) => c.decision.next?.key === cycle.key && c.decision.reason);
}

function HypothesisStage({
  id,
  cycle,
  from,
  fixture,
  runId,
}: {
  id: string;
  cycle: Cycle;
  from: Cycle | undefined;
  fixture: boolean;
  runId?: string;
}) {
  const hypothesis = cycle.hypothesis;
  if (!hypothesis) {
    return (
      <Stage label="Hypothesis" source="None recorded">
        <p className="rf-body">No hypothesis is attached to this program.</p>
      </Stage>
    );
  }
  const question = plainQuestion(cycle);
  return (
    <Stage label="Hypothesis" source={fixture ? "Fixture's proposal, not a finding" : "Model's proposal, not a finding"}>
      {question ? <p className="rf-stage-lead">{question}</p> : null}
      <dl className="rf-stage-list">
        <div>
          <dt className="rf-label">Suspected failure</dt>
          <dd className="rf-body rf-voice">
            <ClampText text={hypothesis.predicted_observation} />
          </dd>
        </div>
      </dl>
      {from ? (
        <Link
          href={cycleHref(id, from.key, runId).replace(`#${from.key}`, `#decision-${from.key}`)}
          className="rf-link rf-why"
          data-testid={`why-${cycle.key}`}
        >
          Why this was tried: the decision after {from.hypothesis?.hypothesis_id ?? "the last experiment"}
        </Link>
      ) : null}
      <details className="rf-disclose">
        <summary>
          <Chevron /> The full hypothesis
        </summary>
        <dl className="rf-stage-list">
          <Line label="Behavior under test" text={hypothesis.behavior} />
          <Line label="Suspected mechanism" text={hypothesis.suspected_mechanism} />
          <Line label="What separates failure from success" text={hypothesis.failure_discriminator} />
          <Line label="Why it was proposed" text={hypothesis.motivation} />
        </dl>
      </details>
    </Stage>
  );
}

function Program({ proposal, sandbox }: { proposal: ProposalView; sandbox: string | null }) {
  const adaptation = ADAPTATION_LABEL[proposal.adaptation];
  const refused = proposal.status === "rejected_before_execution";
  return (
    <div className="rf-stack">
      <p className="rf-stage-program">
        <span className="rf-mono">{proposal.label ?? proposal.proposal_id}</span>
        {/* A refused program has no place in the sequence, whatever adaptation it was filed under. */}
        {refused ? (
          <Tag tone="warn">Refused: {humanize(proposal.rejection_problem)}</Tag>
        ) : (
          <Tag title={adaptation.note} testId={`adaptation-${proposal.proposal_id}`}>
            {adaptation.title}
          </Tag>
        )}
      </p>
      {refused ? (
        <p className="rf-body">
          The coordinator refused this output before it ran, so no target saw it.
          {proposal.replaces_proposal_id ? ` It was a replacement for ${proposal.replaces_proposal_id}.` : ""}
        </p>
      ) : sandbox ? (
        <p className="rf-body">{sandbox}</p>
      ) : null}
      {proposal.code ? (
        <details className="rf-disclose">
          <summary>
            <Chevron /> Generated Python, as run in the sandbox
          </summary>
          <Code>{proposal.code.text}</Code>
          {proposal.code.truncated ? (
            <p className="rf-data">
              Cut to {proposal.code.text.length} of {proposal.code.original_chars} characters.
            </p>
          ) : null}
        </details>
      ) : null}
    </div>
  );
}

function sandboxLine(proposal: ProposalView, trial: Trial | undefined, fixture: boolean): string | null {
  if (!trial) return null;
  const { sandbox_executions: steps, sandbox_network_enabled: network } = trial.experiment;
  const who =
    proposal.authorship === "model_generated"
      ? `Executable Python written by the ${fixture ? "fixture" : "model"}`
      : "A developer script, not written by a model";
  return `${who}, run in ${steps} sandbox step${steps === 1 ? "" : "s"} with networking ${network ? "on" : "off"}.`;
}

function ExperimentStage({ cycle, fixture }: { cycle: Cycle; fixture: boolean }) {
  const first = cycle.trials.find((t) => !t.rerun);
  const run = first?.run ?? null;
  return (
    <Stage label="Experiment" source="What was set up and run">
      {cycle.proposals.map((proposal) => (
        <Program
          key={proposal.proposal_id}
          proposal={proposal}
          sandbox={sandboxLine(proposal, cycle.trials.find((t) => t.experiment.proposal_id === proposal.proposal_id), fixture)}
        />
      ))}
      {cycle.proposals.length === 0 ? (
        <p className="rf-body">No experiment is on record for this hypothesis.</p>
      ) : null}
      {run ? (
        <dl className="rf-stage-list">
          <div>
            <dt className="rf-label">Condition</dt>
            <dd className="rf-body">
              World {run.world_ref}{run.external ? "." : `, ${run.config} policy.`}{" "}
              {run.faults.length ? "Configured faults:" : "No fault was configured."}
            </dd>
            {run.faults.map((fault, i) => (
              <dd key={i} className="rf-body">
                {fixture ? inRehearsal(FAULT_LABEL[fault.kind] ?? humanize(fault.kind)) : (FAULT_LABEL[fault.kind] ?? humanize(fault.kind))}{" "}
                <span className="rf-data">
                  {fault.operation}, occurrence {fault.occurrence}, span {fault.span}
                </span>
              </dd>
            ))}
          </div>
        </dl>
      ) : null}
    </Stage>
  );
}

function TrialResult({ id, trial }: { id: string; trial: Trial }) {
  const { run, experiment, observation } = trial;
  const refs = [observation?.observation_id, run?.run_id, experiment.experiment_id].filter(Boolean);
  if (!run) {
    return (
      <div className="rf-trial">
        <p className="rf-body">
          The experiment ended as {humanize(experiment.termination).toLowerCase()} with no target run to read.
        </p>
        <p className="rf-data rf-break">{refs.join(" · ")}</p>
      </div>
    );
  }
  const story = storyFrom(run);
  const discrepancies = run.discrepancies.length;
  return (
    <div className="rf-trial" data-testid={`trial-${run.run_id}`} data-verdict={run.verdict}>
      <p className="rf-label">
        Run {trial.runNumber ?? "?"} · {run.world_ref}
        {trial.rerun ? " · Rerun of the same program" : ""}
      </p>
      <p className="rf-stage-lead">
        {story.reported} {story.reality}
      </p>
      <dl className="rf-trial-facts">
        <div>
          <dt className="rf-label">{targetNoun(run) === "agent" ? "Agent reported" : "Script reported"}</dt>
          <dd data-testid="trial-claim">{run.agent.claim?.status ?? "no valid claim"}</dd>
        </div>
        <div>
          <dt className="rf-label">Actual outcome</dt>
          <dd data-testid="trial-state">{stateLine(run)}</dd>
        </div>
        <div>
          <dt className="rf-label">Faults delivered</dt>
          <dd data-testid="trial-faults">{run.faults_delivered}</dd>
        </div>
        <div>
          <dt className="rf-label">Discrepancies</dt>
          <dd data-testid="trial-discrepancies">{discrepancies}</dd>
        </div>
        <div className="rf-trial-seal">
          <dt className="rf-label">Oracle verdict</dt>
          <dd>
            <OracleSeal state={sealFromRun(run)} size="sm" labelTestId="trial-verdict" />
          </dd>
        </div>
      </dl>
      <p className="rf-trial-foot">
        <Link href={runHref(id, run.run_id)} className="rf-link" data-testid="trial-compare">
          Compare the two realities
        </Link>
        <span className="rf-data rf-break">
          {run.finding_class ? `${FINDING_CLASS_LABEL[run.finding_class] ?? humanize(run.finding_class)} · ` : ""}
          {refs.join(" · ")}
        </span>
      </p>
    </div>
  );
}

function DecisionStage({
  id,
  cycle,
  fixture,
  runId,
}: {
  id: string;
  cycle: Cycle;
  fixture: boolean;
  runId?: string;
}) {
  const { decision, hypothesis } = cycle;
  const author = fixture ? "fixture" : "model";
  const check = assessmentCheck(cycle);
  const citedNote = ADAPTATION_LABEL.cited_prior_observations.note.split(";")[0];
  return (
    <Stage id={`decision-${cycle.key}`} label="Decision" source={`The record, then the ${fixture ? "fixture" : "model"}'s reasoning`}>
      <p className="rf-stage-lead" data-testid={`decision-${cycle.key}`} data-kind={decision.kind}>
        {decision.title}
      </p>
      <p className="rf-body">{decision.sequence}</p>
      <dl className="rf-stage-list">
        {hypothesis?.assessment_reasoning ? (
          <div>
            <dt className="rf-label">
              The {author}&apos;s assessment: {STATUS_LABEL[hypothesis.status]}
              {hypothesis.assessment_observations.length
                ? `, citing ${hypothesis.assessment_observations.join(", ")}`
                : ""}
            </dt>
            <dd className="rf-body rf-voice">
              <ClampText text={hypothesis.assessment_reasoning} />
            </dd>
            {check ? <dd className="rf-body rf-stage-check">{check}</dd> : null}
          </div>
        ) : null}
        {decision.reason ? (
          <div>
            <dt className="rf-label">
              The {author}&apos;s stated reason for the next step
              {decision.reason.cites.length ? `, citing ${decision.reason.cites.join(", ")}` : ""}
            </dt>
            <dd className="rf-body rf-voice">{decision.reason.text}</dd>
            {decision.reason.cites.length ? <dd className="rf-data">{citedNote}.</dd> : null}
          </div>
        ) : null}
      </dl>
      {decision.next ? (
        <Link href={cycleHref(id, decision.next.key, runId)} className="rf-link" data-testid={`next-${cycle.key}`}>
          Go to {decision.next.label}
        </Link>
      ) : null}
    </Stage>
  );
}

function CycleItem({
  id,
  cycle,
  from,
  open,
  fixture,
  runId,
}: {
  id: string;
  cycle: Cycle;
  from: Cycle | undefined;
  open: boolean;
  fixture: boolean;
  runId?: string;
}) {
  const { hypothesis } = cycle;
  const refused = cycle.proposals.every((p) => p.status === "rejected_before_execution");
  const verdicts = cycleVerdicts(cycle);
  const title =
    hypothesis?.behavior ??
    (refused
      ? `${cycle.proposals.length} generated program${cycle.proposals.length === 1 ? "" : "s"} refused before execution`
      : (cycle.proposals[0]?.label ?? cycle.key));
  return (
    <li
      id={cycle.key}
      data-testid={hypothesis ? `hypothesis-${hypothesis.hypothesis_id}` : `program-${cycle.key}`}
      data-status={hypothesis?.status}
      className="rf-cycle"
    >
      <details open={open}>
        <summary>
          <Chevron />
          <span className="rf-cycle-number">{hypothesis?.hypothesis_id ?? "—"}</span>
          <span className="rf-cycle-title">{title}</span>
          <span className="rf-cycle-result">
            {verdicts.map((v, i) => (
              <VerdictTag key={i} verdict={v} />
            ))}
            {hypothesis ? (
              <span className="rf-cycle-model">
                {fixture ? "Fixture" : "Model"}: {STATUS_LABEL[hypothesis.status]}
              </span>
            ) : null}
          </span>
        </summary>
        <div className="rf-cycle-body">
          <HypothesisStage id={id} cycle={cycle} from={from} fixture={fixture} runId={runId} />
          <ExperimentStage cycle={cycle} fixture={fixture} />
          <Stage label="Observation" source={`Recorded evidence, not the ${fixture ? "fixture" : "model"}'s words`}>
            {cycle.trials.map((trial) => (
              <TrialResult key={`${trial.experiment.experiment_id}-${trial.run?.run_id}`} id={id} trial={trial} />
            ))}
            {cycle.trials.length === 0 ? (
              <p className="rf-body">Nothing ran, so there is nothing to observe.</p>
            ) : null}
          </Stage>
          <DecisionStage id={id} cycle={cycle} fixture={fixture} runId={runId} />
        </div>
      </details>
    </li>
  );
}

export function InvestigatorView({
  id,
  detail,
  cycles,
  opened,
  runId,
}: {
  id: string;
  detail: InvestigationDetail;
  cycles: Cycle[];
  opened: string | null;
  runId?: string;
}) {
  const fixture = detail.summary.investigator_evidence === "offline_fixture";
  return (
    <div className="rf-journey" data-testid="investigator-view">
      <noscript>
        <style>{".rf-clamp{display:block;-webkit-line-clamp:unset;overflow:visible}.rf-more{display:none}"}</style>
      </noscript>
      <section aria-labelledby="journey-title" className="rf-stack">
        <div className="rf-section-head">
          <h2 id="journey-title" className="rf-section-title">
            What the Investigator did
          </h2>
          <ol aria-label="Each step runs in this order" className="rf-flow">
            {FLOW.map((stage) => (
              <li key={stage}>{stage}</li>
            ))}
          </ol>
        </div>
        {cycles.length ? (
          <p className="rf-body" data-testid="journey-line">
            {journeyLine(detail)} The tags give the Oracle&apos;s verdict; the words beside them are the{" "}
            {fixture ? "fixture's" : "model's"} own reading.
          </p>
        ) : (
          <p className="rf-body" data-testid="no-cycles">
            No hypothesis or experiment is on record for this investigation.
          </p>
        )}
        <ol className="rf-cycles">
          {cycles.map((cycle) => (
            <CycleItem
              key={cycle.key}
              id={id}
              cycle={cycle}
              from={ledHere(cycle, cycles)}
              open={cycle.key === opened}
              fixture={fixture}
              runId={runId}
            />
          ))}
        </ol>
      </section>

      {detail.conclusion ? (
        <section aria-labelledby="conclusion-title" className="rf-stack">
          <h2 id="conclusion-title" className="rf-section-title">
            {fixture ? "The fixture's conclusion, scripted" : "The model's conclusion"}
          </h2>
          <p className="rf-label">{humanize(detail.conclusion.conclusion)}. An interpretation, checked below.</p>
          <div className="rf-body rf-measure rf-voice">
            <ClampText text={detail.conclusion.reasoning} />
          </div>
        </section>
      ) : null}

      <ReasoningChecks detail={detail} cycles={cycles} fixture={fixture} />

      {detail.claim_checks.length ? (
        <section aria-labelledby="checks-title" className="rf-stack">
          <h2 id="checks-title" className="rf-section-title">
            Claims checked against the Oracle
          </h2>
          {detail.claim_checks.some((c) => c.statement === detail.conclusion?.reasoning) ? (
            <p className="rf-body">Each finding the conclusion names, set against what the Oracle recorded.</p>
          ) : null}
          <ul className="rf-checks">
            {detail.claim_checks.map((check, i) => (
              <li key={i}>
                <p className="rf-stage-program">
                  <Tag tone={check.supported ? "truth" : "warn"}>
                    {check.supported ? "Backed by the Oracle" : "Not backed"}
                  </Tag>
                  <span className="rf-data">{check.finding_code}</span>
                </p>
                {check.statement !== detail.conclusion?.reasoning ? (
                  <p className="rf-body rf-measure">{check.statement}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="findings-title" className="rf-stack">
        <h2 id="findings-title" className="rf-section-title">
          Findings, classified by trusted code
        </h2>
        <TableScroll label="Findings table">
          <table className="rf-table min-w-[38rem]" data-testid="findings-table">
            <caption className="sr-only">Every target run and how it was classified</caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Class</th>
                <th scope="col">Verdict</th>
                <th scope="col">Outcome</th>
                <th scope="col">Reproduction</th>
              </tr>
            </thead>
            <tbody>
              {detail.findings.map((f) => (
                <tr key={f.run_id} data-testid={`finding-${f.run_id}`}>
                  <td>
                    <Link href={runHref(id, f.run_id)} className="rf-link font-mono">
                      {f.world_ref}
                    </Link>
                  </td>
                  <td>{FINDING_CLASS_LABEL[f.finding_class] ?? f.finding_class}</td>
                  <td>
                    <VerdictTag verdict={f.oracle_verdict} />
                  </td>
                  <td className="font-mono">{humanize(f.run_outcome)}</td>
                  <td>{REPRODUCTION_LABEL[f.reproduction] ?? f.reproduction}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
        {detail.findings.length === 0 ? (
          <p className="rf-body">No target run produced a classified finding.</p>
        ) : null}
      </section>
    </div>
  );
}
