// Mirrors backend/moody_blues/contracts/explorer.py. The backend owns these contracts.

export type ExecutionMode = "recorded" | "live" | "rehearsal" | "local";
export type Verdict = "PASS" | "VIOLATION" | "INCONCLUSIVE";
export type ProductOutcome =
  | "violation_verified"
  | "violation_impaired"
  | "no_violation_found"
  | "inconclusive"
  | "outcome_uncertain"
  | "failed"
  | "cancelled"
  | "budget_exhausted";
export type CaseKind =
  | "verified_violation"
  | "honest_violation"
  | "successful_recovery"
  | "negative_result"
  | "inconclusive";
export type TargetEvidence =
  | "live_provider"
  | "local_ollama"
  | "offline_fixture"
  | "reference_executor"
  | "external_scripted";

/** A real model answered: hosted or on this machine. Only these say anything about model behavior. */
export function isModelEvidence(evidence: string | null | undefined): boolean {
  return evidence === "live_provider" || evidence === "local_ollama";
}

/** Who an external run was. `uses_model` is what the host observed, never what the agent said. */
export interface ExternalTarget {
  agent_id: string;
  name: string;
  agent_version: string;
  protocol: string;
  uses_model: boolean;
  execution_mode: string;
  bundle_sha256: string;
  transcript_sha256: string;
  /** Requests that reached a provider, as the host recorded them. */
  model_calls: number;
  /** No answer to trust: each may have run, and may be billed. */
  model_calls_uncertain: number;
  /** Present only when a local model answered, read from the running provider. */
  model_provider?: string;
  model_digest?: string;
}

export interface BoundedText {
  text: string;
  truncated: boolean;
  original_chars: number;
  sha256: string;
}

export interface CaseNote {
  kind: CaseKind;
  title: string;
  summary: string;
  primary_run_id: string | null;
}

export interface InvestigationSummary {
  investigation_id: string;
  mode: ExecutionMode;
  case: CaseNote | null;
  outcome: ProductOutcome;
  state: string;
  termination: string | null;
  strategy: "fixed" | "one_shot" | "adaptive";
  tier: string;
  world_ids: string[];
  investigator_model: string;
  target_model: string;
  investigator_evidence: "live_provider" | "local_ollama" | "offline_fixture" | null;
  target_evidence: TargetEvidence[];
  experiment_count: number;
  target_run_count: number;
  verified_finding_count: number;
  violation_codes: string[];
  started_at: string;
  finished_at: string | null;
  runtime_ms: number;
  estimated_cost_usd: number;
  usage_complete: boolean;
  cost_note: string;
}

export interface ListedInvestigation {
  investigation_id: string;
  integrity: "verified" | "corrupt";
  summary: InvestigationSummary | null;
  problem: string | null;
}

export interface StudyContext {
  manifest_id: string;
  results_sha256: string;
  conclusion: string;
  units_with_verified_discovery: Record<string, number>;
  units_planned: Record<string, number>;
  reasons: string[];
}

export interface InvestigationList {
  items: ListedInvestigation[];
  study: StudyContext | null;
}

export interface HypothesisView {
  hypothesis_id: string;
  status: "open" | "supported" | "refuted" | "inconclusive";
  behavior: string;
  suspected_mechanism: string;
  motivation: string;
  predicted_observation: string;
  failure_discriminator: string;
  motivating_observations: string[];
  revises: string | null;
  assessment_reasoning: string | null;
  assessment_observations: string[];
}

export type AdaptationKind =
  | "first_experiment"
  | "cited_prior_observations"
  | "planned_without_results"
  | "predetermined_program";

export interface ProposalView {
  proposal_id: string;
  hypothesis_id: string | null;
  label: string | null;
  rationale: string | null;
  status: "executed" | "rejected_before_execution";
  authorship: "developer_script" | "model_generated";
  adaptation: AdaptationKind;
  motivated_by: string[];
  rejection_problem: string | null;
  replaces_proposal_id: string | null;
  code: BoundedText | null;
  code_sha256: string | null;
}

export interface ObservationView {
  observation_id: string;
  experiment_id: string;
  proposal_id: string;
  result_class: string;
  verdicts: Verdict[];
  claim_statuses: (string | null)[];
  faults_delivered: number;
}

export interface ExperimentView {
  experiment_id: string;
  proposal_id: string;
  observation_id: string;
  label: string;
  status: string;
  termination: string;
  result_class: string;
  target_run_ids: string[];
  reproduction_of: string | null;
  sandbox_executions: number;
  sandbox_network_enabled: boolean;
  total_tokens: number;
  estimated_cost_usd: number | null;
  wall_ms: number;
}

export interface FindingView {
  experiment_id: string;
  run_id: string;
  world_ref: string;
  config: string;
  finding_class: string;
  oracle_verdict: Verdict;
  run_outcome: string | null;
  termination: string;
  violation_codes: string[];
  faults_delivered: number;
  target_evidence: TargetEvidence;
  reproduction: string;
  impairments: string[];
  eligible_for_rate: boolean;
}

export interface ClaimCheckView {
  experiment_id: string;
  finding_code: string;
  statement: string;
  supported: boolean;
  reason: string;
  fault_was_delivered: boolean;
}

export interface CaseStudy {
  rerun_source_sha256: string;
  eligible_runs: number;
  eligible_reproduced: number;
  impaired_runs: number;
  note: string;
}

export interface Provenance {
  export_version: number;
  source_report_sha256: string;
  source_journal_head_sha256: string;
  source_journal_records: number;
  capability_sha256: string;
  experiments: {
    experiment_id: string;
    evidence_sha256: string;
    journal_head_sha256: string;
    run_report_sha256: string[];
  }[];
}

export interface InvestigationDetail {
  summary: InvestigationSummary;
  integrity: "verified" | "corrupt";
  objective: string;
  statement: string;
  limitations: string[];
  hypotheses: HypothesisView[];
  proposals: ProposalView[];
  observations: ObservationView[];
  findings: FindingView[];
  claim_checks: ClaimCheckView[];
  conclusion: { conclusion: string; reasoning: string } | null;
  case_study: CaseStudy | null;
  provenance: Provenance;
}

export interface ToolEvent {
  call_seq: number;
  tool: string;
  arguments: BoundedText;
  ok: boolean;
  delivered: BoundedText;
  delivered_summary: string;
  error_code: string | null;
  fault_injected: string | null;
  fault_effect: string | null;
  actual_summary: string | null;
  agent_note: BoundedText | null;
}

export interface ClaimView {
  status: string;
  customer_id: string | null;
  message: BoundedText;
}

export interface DisclosureView {
  flagged_customer_ids: string[];
  mentioned_in_message: string[];
  not_mentioned_in_message: string[];
}

export interface CustomerView {
  customer_id: string;
  name: string;
  email: string;
  metadata: Record<string, unknown>;
  client_request_id: string | null;
  created_by_call: number;
  role: "seed" | "new";
  objective_match: boolean;
  flagged_duplicate: boolean;
  named_in_claim: boolean;
}

export interface OracleFindingView {
  code: string;
  severity: "violation" | "warning" | "info";
  invariant: string | null;
  message: string;
  customer_ids: string[];
  call_seqs: number[];
}

export interface Discrepancy {
  kind:
    | "misleading_write_response"
    | "stale_read"
    | "claim_versus_state"
    | "duplicate_side_effect";
  call_seq: number | null;
  agent_saw: string;
  actually: string;
  source: "oracle" | "fault_event";
}

export interface RealityRun {
  run_id: string;
  run_ref: string;
  experiment_id: string;
  world_ref: string;
  scenario_ref: string;
  config: string;
  target_kind: "llm_agent" | "reference_executor" | "external_agent";
  target_evidence: TargetEvidence;
  /** Present only on an external run. */
  external?: ExternalTarget;
  reported_models: string[];
  verdict: Verdict;
  run_outcome: string | null;
  finding_class: string | null;
  impairments: string[];
  faults: { kind: string; operation: string; occurrence: number; span: number }[];
  faults_delivered: number;
  agent: {
    mission: BoundedText | null;
    tool_events: ToolEvent[];
    termination: string;
    claim: ClaimView | null;
    disclosure: DisclosureView | null;
    recovery_pattern: string | null;
  };
  actual: {
    customers: CustomerView[];
    changes: {
      change_seq: number;
      operation: string;
      customer_id: string;
      created_by_call: number;
    }[];
    new_customer_ids: string[];
    verdict: Verdict;
    objective_satisfied: boolean;
    invariants_evaluated: string[];
    invariants_violated: string[];
    findings: OracleFindingView[];
  };
  discrepancies: Discrepancy[];
}

export interface RunSummary {
  run_id: string;
  experiment_id: string;
  world_ref: string;
  config: string;
  verdict: Verdict;
  run_outcome: string | null;
  faults_delivered: number;
}

export interface RunList {
  investigation_id: string;
  primary_run_id: string | null;
  runs: RunSummary[];
}

export type Authorship =
  | "investigator_model"
  | "coordinator"
  | "sandbox"
  | "gateway"
  | "target_agent"
  | "oracle";

export interface TimelineEntry {
  seq: number;
  at: string;
  at_precision: "exact" | "run_report";
  stage: string;
  authorship: Authorship;
  title: string;
  detail: string | null;
  facts: Record<string, unknown>;
  evidence: {
    journal: "investigation" | "experiment";
    journal_seq: number;
    record_sha256: string;
    experiment_id: string | null;
    run_id: string | null;
    hypothesis_id: string | null;
    proposal_id: string | null;
    observation_id: string | null;
    call_seq: number | null;
  };
}

export interface TimelinePage {
  investigation_id: string;
  total: number;
  offset: number;
  entries: TimelineEntry[];
}

export type JobStatus =
  | "created"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "budget_exhausted"
  | "outcome_uncertain";

export interface JobRecord {
  job_id: string;
  mission_id: string;
  mode: ExecutionMode;
  status: JobStatus;
  investigation_id: string;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  code: string | null;
  cancel_requested: boolean;
  evidence_available: boolean;
  bundle_sha256: string | null;
}

export interface JobEvent {
  event_id: number;
  job_id: string;
  at: string;
  type: string;
  code: string;
  experiment_id: string | null;
  result_class: string | null;
}

export interface JobView {
  job: JobRecord;
  events: JobEvent[];
}

export interface MissionView {
  mission_id: string;
  mode: ExecutionMode;
  title: string;
  description: string;
  worlds: string[];
  max_experiments: number;
  available: boolean;
  blocked_by: string | null;
}

export interface LiveStatus {
  live_enabled: boolean;
  budget: {
    limit_usd: number;
    settled_usd: number;
    open_reservations_usd: number;
    remaining_usd: number;
    required_usd: number;
    note: string;
  } | null;
  budget_problem: string | null;
  active_job_id: string | null;
  missions: MissionView[];
}
