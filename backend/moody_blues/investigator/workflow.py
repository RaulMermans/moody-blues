"""The deterministic investigation workflow around one model.

The model chooses hypotheses and writes programs. This code holds every limit and every
transition: it decides whether another call or experiment may happen, runs programs only through
the coordinator, classifies results from evidence, and writes the findings.

Rules that matter:

- A rejected experiment stays rejected. A replacement is a new proposal with a new record, and
  only if the failed one provably touched no world.
- Nothing is repeated after possible world effects. Reproduction is a separate, deliberate
  experiment in a fresh world, never after an uncertain outcome.
- The model's conclusion is recorded and checked. It cannot create, remove or relabel a finding.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

from moody_blues.contracts.experiment_evidence import (
    ExperimentAuthorship,
    ExperimentEvidence,
    ExperimentLimits,
    ExperimentSpec,
    GenerationRecord,
)
from moody_blues.contracts.investigation import (
    TERMINAL_INVESTIGATION_STATES,
    ConcludeInvestigation,
    DecisionKind,
    ExperimentRef,
    FindingClass,
    GenerationDiagnostic,
    Hypothesis,
    HypothesisAssessment,
    HypothesisRecord,
    InvestigationDecision,
    InvestigationObservation,
    InvestigationReport,
    InvestigationRequest,
    InvestigationState,
    InvestigationUsage,
    ModelCallRecord,
    ProposalRecord,
    ProposalStatus,
    ProposedExperiment,
    ProposeExperiment,
    ResultClass,
    Strategy,
    TargetCapability,
    VerifiedFinding,
)
from moody_blues.contracts.protocol import MAX_EXPERIMENT_CODE_BYTES
from moody_blues.contracts.sandbox import SandboxLimits
from moody_blues.contracts.validity import AssessmentCheck, InvestigationValidity
from moody_blues.experiments.budget import BudgetExceededError, ScopedSpend
from moody_blues.experiments.coordinator import ExperimentCoordinator
from moody_blues.experiments.programs import probe_program
from moody_blues.experiments.recovery import verify_experiment
from moody_blues.experiments.target import TargetPort
from moody_blues.experiments.workspace import EVIDENCE, sha256_text
from moody_blues.investigator.catalog import target_capability, world_of
from moody_blues.investigator.context import (
    InvestigationContext,
    PromptTooLargeError,
    build_messages,
)
from moody_blues.investigator.findings import (
    check_claims,
    reproduction_status,
    run_finding,
    statement,
)
from moody_blues.investigator.model import (
    CONCLUDE_TOOL,
    PROPOSE_TOOL,
    Decision,
    InvestigatorModel,
    invalid,
    parse_decision,
)
from moody_blues.investigator.observations import (
    classify,
    diagnostic_for,
    observe,
    recoverable,
)
from moody_blues.investigator.validity import (
    check_batch,
    conclusion_matches,
    experiment_validity,
    repeated_hypotheses,
)
from moody_blues.investigator.workspace import InvestigationWorkspace, exclusive
from moody_blues.sandbox.base import SandboxRunner

log = logging.getLogger("moody_blues.investigator")

_ALLOWED: dict[InvestigationState, frozenset[InvestigationState]] = {
    InvestigationState.CREATED: frozenset({InvestigationState.PLANNING}),
    InvestigationState.PLANNING: frozenset(
        {InvestigationState.EXPERIMENTING, InvestigationState.REVISING}
    ),
    InvestigationState.EXPERIMENTING: frozenset({InvestigationState.EVALUATING}),
    InvestigationState.EVALUATING: frozenset(
        {InvestigationState.REVISING, InvestigationState.EXPERIMENTING}
    ),
    InvestigationState.REVISING: frozenset({InvestigationState.EXPERIMENTING}),
}

_STOPS_INVESTIGATION: dict[ResultClass, tuple[InvestigationState, str]] = {
    ResultClass.UNCERTAIN_SIDE_EFFECTS: (InvestigationState.FAILED, "uncertain_side_effects"),
    ResultClass.INFRASTRUCTURE_FAILURE: (InvestigationState.FAILED, "infrastructure_failure"),
    ResultClass.PROVIDER_FAILURE: (InvestigationState.FAILED, "target_provider_failure"),
    ResultClass.BUDGET_EXHAUSTED: (InvestigationState.BUDGET_EXHAUSTED, "experiment_budget"),
    ResultClass.CANCELLED: (InvestigationState.CANCELLED, "cancelled"),
}

LOCAL_USAGE_NOTE = "a model on this machine; no provider was paid, and the ledger was not touched"

COST_LIMITATION = "Costs are estimates at assumed ceiling prices, not provider billing."
LOCAL_COST_LIMITATION = "The Investigator's model ran on this machine: no provider was paid."

LIMITATIONS: tuple[str, ...] = (
    "Covers only the listed worlds, faults and configurations, within the stated budget.",
    "Target runs are non-deterministic: one run is one sample, not a rate.",
    COST_LIMITATION,
    "Containers share the host VM's kernel; there is no gVisor or Kata layer.",
)


class InvalidInvestigationTransitionError(RuntimeError):
    pass


def check_transition(current: InvestigationState, new: InvestigationState) -> None:
    """Terminal states are final; any live state may end; the rest is listed."""
    if current in TERMINAL_INVESTIGATION_STATES:
        raise InvalidInvestigationTransitionError(f"{current.value} is terminal")
    if new in TERMINAL_INVESTIGATION_STATES or new in _ALLOWED.get(current, frozenset()):
        return
    raise InvalidInvestigationTransitionError(f"{current.value} -> {new.value}")


@dataclass(frozen=True, slots=True)
class ExperimentRunner:
    """Everything needed to build a coordinator. Assembled by trusted code only."""

    sandbox: SandboxRunner
    target: TargetPort
    root: Path
    sandbox_limits: SandboxLimits

    def run(
        self,
        spec: ExperimentSpec,
        *,
        worlds: tuple[str, ...],
        max_runtime_seconds: float,
        cancel: Event | None,
    ) -> ExperimentEvidence:
        coordinator = ExperimentCoordinator(
            sandbox=self.sandbox,
            target=self.target,
            root=self.root,
            sandbox_limits=self.sandbox_limits,
            limits=ExperimentLimits(max_runtime_seconds=min(300.0, max_runtime_seconds)),
            allowed_scenarios=worlds,
            world=world_of(worlds),
        )
        return coordinator.run(spec, cancel=cancel)


@dataclass(frozen=True, slots=True)
class _Stop:
    state: InvestigationState
    termination: str


def fixed_plan(worlds: tuple[str, ...], count: int) -> list[tuple[str, str]]:
    """Strategy A: each world as built, baseline policy, in catalog order. No choice involved."""
    return [
        (
            f"fixed-{world}",
            probe_program(
                scenario_id=world, config="baseline", looking_for="duplicate_side_effect"
            ),
        )
        for world in worlds[:count]
    ]


class InvestigationWorkflow:
    def __init__(
        self,
        *,
        request: InvestigationRequest,
        runner: ExperimentRunner,
        root: Path,
        model: InvestigatorModel | None,
        spend: ScopedSpend | None = None,
        investigation_id: str | None = None,
        cancel: Event | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        capability: TargetCapability | None = None,
        fixed_schedule: Sequence[tuple[str, str]] | None = None,
        repair_unrun_programs: bool = False,
    ) -> None:
        if request.strategy is not Strategy.FIXED and model is None:
            raise ValueError("this strategy needs a model")
        if fixed_schedule is not None and request.strategy is not Strategy.FIXED:
            raise ValueError("only the fixed strategy follows a schedule")
        self.request = request
        self.investigation_id = investigation_id or f"inv_{uuid4().hex[:12]}"
        self._runner = runner
        self._root = root
        self._model = model
        self._spend = spend
        self._cancel = cancel
        self._monotonic = monotonic
        self._capability = capability or target_capability(request.world_ids)
        self._world = world_of(request.world_ids)
        self._fixed_schedule = fixed_schedule
        self._repair_unrun_programs = repair_unrun_programs
        self._limits = request.limits
        self._state = InvestigationState.CREATED
        self._termination: str | None = None
        self._started_at = datetime.now(UTC)
        self._started = monotonic()
        self._hypotheses: dict[str, HypothesisRecord] = {}
        self._decisions: list[InvestigationDecision] = []
        self._proposals: list[ProposalRecord] = []
        self._experiments: list[ExperimentRef] = []
        self._observations: list[InvestigationObservation] = []
        self._calls: list[ModelCallRecord] = []
        self._evidence: dict[str, ExperimentEvidence] = {}
        self._assessment_checks: list[AssessmentCheck] = []
        self._conclusion: ConcludeInvestigation | None = None
        self._findings: list[VerifiedFinding] = []
        self._slots_used = 0
        self._refinements_used = 0
        self._workspace: InvestigationWorkspace

    # --- lifecycle ----------------------------------------------------------------------

    def run(self) -> InvestigationReport:
        with exclusive(self._root):
            self._workspace = InvestigationWorkspace(self._root, self.investigation_id)
            self._journal_created()
            self._transition(InvestigationState.PLANNING)
            try:
                match self.request.strategy:
                    case Strategy.ADAPTIVE:
                        stop = self._adaptive()
                    case Strategy.ONE_SHOT:
                        stop = self._one_shot()
                    case Strategy.FIXED:
                        stop = self._fixed()
            except BudgetExceededError as exc:
                self._workspace.journal("budget_refused", {"message": exc.detail.message[:300]})
                stop = _Stop(InvestigationState.BUDGET_EXHAUSTED, "spend_limit")
            return self._finish(stop)

    def _journal_created(self) -> None:
        self._workspace.journal(
            "investigation_created",
            {
                "investigation_id": self.investigation_id,
                "request": self.request.model_dump(mode="json"),
                "capability_sha256": self._capability_sha(),
            },
        )

    def _capability_sha(self) -> str:
        return sha256_text(self._capability.model_dump_json())

    def _transition(self, new: InvestigationState) -> None:
        check_transition(self._state, new)
        self._state = new
        self._workspace.journal("state", {"state": new.value})
        self._workspace.save_state(self._report(None))

    def _remaining_seconds(self) -> float:
        return self._limits.max_wall_seconds - (self._monotonic() - self._started)

    def _guard(self) -> _Stop | None:
        if self._cancel is not None and self._cancel.is_set():
            return _Stop(InvestigationState.CANCELLED, "cancelled")
        if self._remaining_seconds() <= 0:
            return _Stop(InvestigationState.BUDGET_EXHAUSTED, "max_wall_seconds")
        return None

    def _decide(self, kind: DecisionKind, reason: str, **fields: object) -> None:
        decision = InvestigationDecision.model_validate(
            {
                "seq": len(self._decisions) + 1,
                "kind": kind,
                "model_call_seq": self._calls[-1].seq if self._calls else None,
                "reason": reason,
            }
            | fields
        )
        self._decisions.append(decision)
        self._workspace.journal("decision", decision.model_dump(mode="json"))

    # --- strategies ---------------------------------------------------------------------

    def _adaptive(self) -> _Stop:
        diagnostic: GenerationDiagnostic | None = None
        replaces: str | None = None
        while True:
            stop = self._guard()
            if stop is not None:
                return stop
            if len(self._calls) >= self._limits.max_model_calls:
                return _Stop(InvestigationState.BUDGET_EXHAUSTED, "max_model_calls")
            slots_left = self._limits.max_experiments - self._slots_used
            offered = [PROPOSE_TOOL, CONCLUDE_TOOL] if slots_left > 0 else [CONCLUDE_TOOL]
            outcome = self._ask(offered, "decide", diagnostic)
            if isinstance(outcome, _Stop):
                return outcome
            diagnostic = None
            if isinstance(outcome, ConcludeInvestigation):
                return self._accept_conclusion(outcome)
            if isinstance(outcome, ProposeExperiment):
                outcome = self._check_proposal(outcome, replaces)
            if isinstance(outcome, GenerationDiagnostic):
                proposal_id = self._record_rejected(outcome, replaces)
                if self._refinements_used >= self._limits.max_refinements:
                    self._decide(DecisionKind.INVALID, outcome.problem, proposal_id=proposal_id)
                    return _Stop(InvestigationState.INCONCLUSIVE, "generation_failed")
                self._refinements_used += 1
                self._decide(DecisionKind.REFINE, outcome.problem, proposal_id=proposal_id)
                diagnostic, replaces = outcome, proposal_id
                self._to_revising()
                continue
            self._apply_assessments(outcome.assessments)
            self._hypotheses[outcome.hypothesis.hypothesis_id] = HypothesisRecord(
                hypothesis=outcome.hypothesis
            )
            proposal = self._record_generated(outcome.hypothesis, outcome.experiment, replaces)
            replaces = None
            self._decide(
                DecisionKind.PROPOSE,
                "model_proposed_experiment",
                hypothesis_id=outcome.hypothesis.hypothesis_id,
                proposal_id=proposal.proposal_id,
                cited_observations=list(outcome.experiment.motivated_by),
            )
            evidence, observation = self._execute(proposal, outcome.experiment.python_code)
            stop = self._stop_for(observation)
            if stop is not None:
                self._slots_used += 1
                return stop
            result = observation.result_class
            if recoverable(evidence, result) and (
                self._refinements_used < self._limits.max_refinements
            ):
                self._refinements_used += 1
                diagnostic, replaces = diagnostic_for(observation), proposal.proposal_id
                self._decide(DecisionKind.REFINE, result.value, proposal_id=proposal.proposal_id)
                continue
            self._slots_used += 1

    def _one_shot(self) -> _Stop:
        """Every program is written first, then all run. Results reach no model at all."""
        planned: list[tuple[ProposalRecord, str]] = []
        diagnostic: GenerationDiagnostic | None = None
        replaces: str | None = None
        while len(planned) < self._limits.max_experiments:
            stop = self._guard()
            if stop is not None:
                return stop
            if len(self._calls) >= self._limits.max_model_calls:
                break
            outcome = self._ask([PROPOSE_TOOL], "plan", diagnostic, planned=len(planned))
            if isinstance(outcome, _Stop):
                return outcome
            diagnostic = None
            if isinstance(outcome, ProposeExperiment):
                outcome = self._check_proposal(outcome, planning=True)
            if isinstance(outcome, GenerationDiagnostic):
                proposal_id = self._record_rejected(outcome, replaces)
                if self._refinements_used >= self._limits.max_refinements:
                    self._decide(DecisionKind.INVALID, outcome.problem, proposal_id=proposal_id)
                    break
                self._refinements_used += 1
                self._decide(DecisionKind.REFINE, outcome.problem, proposal_id=proposal_id)
                diagnostic, replaces = outcome, proposal_id
                continue
            if not isinstance(outcome, ProposeExperiment):  # pragma: no cover - not offered
                raise TypeError("only proposals are offered while planning")
            self._hypotheses[outcome.hypothesis.hypothesis_id] = HypothesisRecord(
                hypothesis=outcome.hypothesis
            )
            proposal = self._record_generated(outcome.hypothesis, outcome.experiment, replaces)
            replaces = None
            self._decide(
                DecisionKind.PROPOSE,
                "model_planned_experiment",
                hypothesis_id=outcome.hypothesis.hypothesis_id,
                proposal_id=proposal.proposal_id,
            )
            planned.append((proposal, outcome.experiment.python_code))
        queue = deque(planned)
        while queue:
            stop = self._guard()
            if stop is not None:
                return stop
            proposal, code = queue.popleft()
            evidence, observation = self._execute(proposal, code)
            stop = self._stop_for(observation)
            if stop is not None:
                self._slots_used += 1
                return stop
            result = observation.result_class
            if (
                self._repair_unrun_programs
                and recoverable(evidence, result)
                and self._refinements_used < self._limits.max_refinements
            ):
                replacement = self._replace_planned(proposal, observation, len(queue))
                if isinstance(replacement, _Stop):
                    return replacement
                if replacement is not None:
                    queue.appendleft(replacement)
                    continue
            self._slots_used += 1
        return self._plan_finished()

    def _replace_planned(
        self, failed: ProposalRecord, observation: InvestigationObservation, queued: int
    ) -> tuple[ProposalRecord, str] | _Stop | None:
        """Opt-in, for matched comparisons: a program that never reached the target is replaced.

        Adaptive runs always have this repair, so without it a broken program would cost this
        strategy a slot and the adaptive one nothing. The diagnostic is about the program. No
        target ran, so it carries nothing about behavior, and ``_ask`` still shows no observations.
        """
        if len(self._calls) >= self._limits.max_model_calls:
            return None
        self._refinements_used += 1
        self._decide(
            DecisionKind.REFINE, observation.result_class.value, proposal_id=failed.proposal_id
        )
        outcome = self._ask(
            [PROPOSE_TOOL],
            "plan",
            diagnostic_for(observation),
            planned=self._slots_used + queued,
        )
        if isinstance(outcome, _Stop):
            return outcome
        if isinstance(outcome, ProposeExperiment):
            outcome = self._check_proposal(outcome, failed.proposal_id, planning=True)
        if isinstance(outcome, GenerationDiagnostic):
            proposal_id = self._record_rejected(outcome, failed.proposal_id)
            self._decide(DecisionKind.INVALID, outcome.problem, proposal_id=proposal_id)
            return None
        if not isinstance(outcome, ProposeExperiment):  # pragma: no cover - not offered
            raise TypeError("only proposals are offered while planning")
        self._hypotheses[outcome.hypothesis.hypothesis_id] = HypothesisRecord(
            hypothesis=outcome.hypothesis
        )
        proposal = self._record_generated(
            outcome.hypothesis, outcome.experiment, failed.proposal_id
        )
        self._decide(
            DecisionKind.PROPOSE,
            "model_planned_experiment",
            hypothesis_id=outcome.hypothesis.hypothesis_id,
            proposal_id=proposal.proposal_id,
        )
        return proposal, outcome.experiment.python_code

    def _fixed(self) -> _Stop:
        plan = (
            list(self._fixed_schedule[: self._limits.max_experiments])
            if self._fixed_schedule is not None
            else fixed_plan(self.request.world_ids, self._limits.max_experiments)
        )
        for index, (label, code) in enumerate(plan, start=1):
            stop = self._guard()
            if stop is not None:
                return stop
            proposal = ProposalRecord(
                proposal_id=f"prop_{index}",
                model_call_seq=None,
                authorship=ExperimentAuthorship.DEVELOPER_SCRIPT,
                hypothesis_id=None,
                label=label,
                rationale=None,
                motivated_by=[],
                source_sha256=sha256_text(code),
                source_bytes=len(code.encode()),
                source_path=self._workspace.save_source(f"prop_{index}", code),
                status=ProposalStatus.EXECUTED,
            )
            self._proposals.append(proposal)
            self._decide(DecisionKind.PROPOSE, "fixed_plan", proposal_id=proposal.proposal_id)
            _, observation = self._execute(proposal, code)
            self._slots_used += 1
            stop = self._stop_for(observation)
            if stop is not None:
                return stop
        return self._plan_finished()

    def _plan_finished(self) -> _Stop:
        ran = any(e.target_run_ids for e in self._experiments)
        if ran:
            return _Stop(InvestigationState.COMPLETED, "plan_finished")
        return _Stop(InvestigationState.INCONCLUSIVE, "no_target_run")

    # --- the model ----------------------------------------------------------------------

    def _ask(
        self,
        offered: list[str],
        purpose: str,
        diagnostic: GenerationDiagnostic | None,
        planned: int | None = None,
    ) -> Decision | GenerationDiagnostic | _Stop:
        if self._model is None:  # pragma: no cover - refused in __init__
            raise AssertionError("no model")
        context = InvestigationContext(
            objective=self.request.objective,
            capability=self._capability,
            limits=self._limits,
            experiments_remaining=self._limits.max_experiments
            - (self._slots_used if planned is None else planned),
            model_calls_remaining=self._limits.max_model_calls - len(self._calls),
            hypotheses=list(self._hypotheses.values()),
            # Planning sees no result by construction, however far execution has got.
            observations=self._observations if planned is None else [],
            diagnostic=diagnostic,
            planning_without_results=planned is not None,
            subject=self._world.investigator_subject(),
        )
        try:
            messages = build_messages(context)
        except PromptTooLargeError:
            return _Stop(InvestigationState.FAILED, "prompt_limit")
        seq = len(self._calls) + 1
        self._workspace.journal("model_call_intent", {"seq": seq, "purpose": purpose})
        call = self._model.call(
            seq=seq,
            purpose=purpose,
            messages=messages,
            offered=offered,
            artifact_dir=self._workspace.calls_dir,
        )
        self._calls.append(call.record)
        self._workspace.journal("model_call_finished", call.record.model_dump(mode="json"))
        if call.result is None:
            return _Stop(InvestigationState.FAILED, "investigator_provider_error")
        return parse_decision(call.result, offered)

    def _known_observations(self) -> set[str]:
        return {o.observation_id for o in self._observations}

    def _check_proposal(
        self, proposal: ProposeExperiment, replaces: str | None = None, *, planning: bool = False
    ) -> ProposeExperiment | GenerationDiagnostic:
        """References must be real. Causal claims cannot be checked here; see evaluation.py."""
        known = set[str]() if planning else self._known_observations()
        hypothesis, experiment = proposal.hypothesis, proposal.experiment
        if len(experiment.python_code.encode()) > MAX_EXPERIMENT_CODE_BYTES:
            return invalid("code_too_long", ["python_code"])
        bad: list[str] = []
        # A replacement program may keep testing the hypothesis of the proposal it replaces.
        replaced = next((p for p in self._proposals if p.proposal_id == replaces), None)
        kept = replaced is not None and replaced.hypothesis_id == hypothesis.hypothesis_id
        if hypothesis.hypothesis_id in self._hypotheses and not kept:
            bad.append("hypothesis_id")
        if hypothesis.revises is not None and hypothesis.revises not in self._hypotheses:
            bad.append("revises")
        if not set(hypothesis.motivating_observations) <= known:
            bad.append("motivating_observations")
        if not set(experiment.motivated_by) <= known or (known and not experiment.motivated_by):
            bad.append("motivated_by")
        for assessment in proposal.assessments:
            if assessment.hypothesis_id not in self._hypotheses:
                bad.append("hypothesis_id")
            if not set(assessment.cited_observations) <= known:
                bad.append("cited_observations")
        return invalid("invalid_decision", sorted(set(bad))) if bad else proposal

    def _apply_assessments(self, assessments: list[HypothesisAssessment]) -> None:
        """The model's assessment is kept. Its status stands only as far as the evidence does."""
        checks = check_batch(
            assessments,
            earlier=self._assessment_checks,
            observations={o.observation_id: o for o in self._observations},
            evidence=self._evidence,
            proposals=self._proposals,
            experiment_by_proposal={e.proposal_id: e.experiment_id for e in self._experiments},
        )
        self._assessment_checks.extend(checks)
        for assessment, check in zip(assessments, checks, strict=True):
            record = self._hypotheses.get(assessment.hypothesis_id)
            if record is not None:
                self._hypotheses[assessment.hypothesis_id] = record.model_copy(
                    update={"status": check.effective_status, "assessment": assessment}
                )

    def _accept_conclusion(self, conclusion: ConcludeInvestigation) -> _Stop:
        known = self._known_observations()
        valid = [
            a
            for a in conclusion.assessments
            if a.hypothesis_id in self._hypotheses and set(a.cited_observations) <= known
        ]
        self._apply_assessments(valid)
        self._conclusion = conclusion
        self._decide(DecisionKind.CONCLUDE, f"model_concluded:{conclusion.conclusion}")
        ran = any(e.target_run_ids for e in self._experiments)
        if not ran or conclusion.conclusion == "inconclusive":
            return _Stop(InvestigationState.INCONCLUSIVE, "model_concluded")
        return _Stop(InvestigationState.COMPLETED, "model_concluded")

    def _to_revising(self) -> None:
        if self._state is not InvestigationState.REVISING:
            self._transition(InvestigationState.REVISING)

    # --- proposals and execution --------------------------------------------------------

    def _next_proposal_id(self) -> str:
        return f"prop_{len(self._proposals) + 1}"

    def _record_rejected(self, diagnostic: GenerationDiagnostic, replaces: str | None) -> str:
        """The raw response stays in calls/. It never ran, so it has no source artifact."""
        proposal_id = self._next_proposal_id()
        self._proposals.append(
            ProposalRecord(
                proposal_id=proposal_id,
                model_call_seq=self._calls[-1].seq if self._calls else None,
                authorship=ExperimentAuthorship.MODEL_GENERATED,
                hypothesis_id=None,
                label=None,
                rationale=None,
                motivated_by=[],
                source_sha256=None,
                source_bytes=None,
                source_path=None,
                status=ProposalStatus.REJECTED_BEFORE_EXECUTION,
                rejection=diagnostic,
                replaces_proposal_id=replaces,
            )
        )
        return proposal_id

    def _record_generated(
        self, hypothesis: Hypothesis, experiment: ProposedExperiment, replaces: str | None
    ) -> ProposalRecord:
        proposal_id = self._next_proposal_id()
        code = experiment.python_code
        record = ProposalRecord(
            proposal_id=proposal_id,
            model_call_seq=self._calls[-1].seq if self._calls else None,
            authorship=ExperimentAuthorship.MODEL_GENERATED,
            hypothesis_id=hypothesis.hypothesis_id,
            label=experiment.label,
            rationale=experiment.rationale,
            motivated_by=list(experiment.motivated_by),
            source_sha256=sha256_text(code),
            source_bytes=len(code.encode()),
            source_path=self._workspace.save_source(proposal_id, code),
            status=ProposalStatus.EXECUTED,
            replaces_proposal_id=replaces,
        )
        self._proposals.append(record)
        return record

    def _spec(
        self, proposal: ProposalRecord, code: str, reproduction_of: str | None
    ) -> ExperimentSpec:
        generated = proposal.authorship is ExperimentAuthorship.MODEL_GENERATED
        generation = None
        if generated and self._model is not None:
            generation = GenerationRecord(
                proposal_id=proposal.proposal_id,
                model=self._model.model,
                evidence_source=self._model.evidence,
            )
        label = proposal.label or proposal.proposal_id
        return ExperimentSpec(
            label=f"repro-{label}" if reproduction_of else label,
            code=code,
            parent_investigation_id=self.investigation_id,
            authorship=proposal.authorship,
            generation=generation,
            reproduction_of=reproduction_of,
        )

    def _run_experiment(self, spec: ExperimentSpec) -> ExperimentEvidence:
        self._workspace.journal(
            "experiment_intent",
            {"label": spec.label, "code_sha256": sha256_text(spec.code)},
        )
        evidence = self._runner.run(
            spec,
            worlds=self.request.world_ids,
            max_runtime_seconds=max(self._remaining_seconds(), 1.0),
            cancel=self._cancel,
        )
        self._evidence[evidence.experiment_id] = evidence
        return evidence

    def _link(
        self,
        evidence: ExperimentEvidence,
        proposal_id: str,
        observation_id: str,
        result: ResultClass,
    ) -> None:
        path = self._runner.root / evidence.experiment_id / EVIDENCE
        ref = ExperimentRef(
            experiment_id=evidence.experiment_id,
            proposal_id=proposal_id,
            observation_id=observation_id,
            code_sha256=evidence.code_sha256,
            evidence_sha256=sha256_text(path.read_text(encoding="utf-8")),
            status=evidence.status,
            result_class=result,
            target_run_ids=[r.run_id for r in evidence.target_runs],
            reproduction_of=evidence.reproduction_of,
        )
        self._experiments.append(ref)
        self._workspace.journal("experiment_linked", ref.model_dump(mode="json"))

    def _execute(
        self, proposal: ProposalRecord, code: str
    ) -> tuple[ExperimentEvidence, InvestigationObservation]:
        if self._state in {InvestigationState.EVALUATING}:
            self._to_revising()
        self._transition(InvestigationState.EXPERIMENTING)
        evidence = self._run_experiment(self._spec(proposal, code, None))
        self._transition(InvestigationState.EVALUATING)
        observation = observe(
            evidence,
            observation_id=f"obs_{len(self._observations) + 1}",
            proposal_id=proposal.proposal_id,
        )
        self._observations.append(observation)
        self._link(evidence, proposal.proposal_id, observation.observation_id, classify(evidence))
        self._workspace.save_state(self._report(None))
        return evidence, observation

    @staticmethod
    def _stop_for(observation: InvestigationObservation) -> _Stop | None:
        stop = _STOPS_INVESTIGATION.get(observation.result_class)
        return _Stop(*stop) if stop is not None else None

    # --- verification -------------------------------------------------------------------

    def _build_findings(self) -> None:
        for ref in self._experiments:
            if ref.reproduction_of is not None:
                continue
            evidence = self._evidence[ref.experiment_id]
            intact = not verify_experiment(self._runner.root / ref.experiment_id)
            self._findings.extend(
                run_finding(evidence, run, proposal_id=ref.proposal_id, evidence_intact=intact)
                for run in evidence.target_runs
            )

    def _reproduce(self, stop: _Stop) -> None:
        """Independent reruns of confirmed violations, in fresh worlds, while budget allows."""
        if stop.state is InvestigationState.CANCELLED:
            return
        attempts = 0
        for index, finding in enumerate(self._findings):
            if finding.finding_class is not FindingClass.ORACLE_CONFIRMED_VIOLATION:
                continue
            if attempts >= self._limits.max_reproductions or self._guard() is not None:
                continue
            attempts += 1
            original = self._evidence[finding.experiment_id]
            proposal = next(p for p in self._proposals if p.proposal_id == finding.proposal_id)
            source = self._workspace.directory / (proposal.source_path or "")
            spec = self._spec(proposal, source.read_text(encoding="utf-8"), finding.experiment_id)
            try:
                attempt = self._run_experiment(spec)
            except BudgetExceededError:  # pragma: no cover - the target reports this as evidence
                continue
            observation_id = f"repro_{len(self._experiments) + 1}"
            self._link(attempt, proposal.proposal_id, observation_id, classify(attempt))
            run = next(r for r in original.target_runs if r.run_id == finding.run_id)
            self._findings[index] = finding.model_copy(
                update={
                    "reproduction": reproduction_status(run, attempt),
                    "reproduction_experiment_id": attempt.experiment_id,
                }
            )

    # --- closing ------------------------------------------------------------------------

    def _limitations(self) -> list[str]:
        if not any(c.evidence_source == "local_ollama" for c in self._calls):
            return list(LIMITATIONS)
        return [LOCAL_COST_LIMITATION if t == COST_LIMITATION else t for t in LIMITATIONS]

    def _usage(self) -> InvestigationUsage:
        runs = [r for e in self._evidence.values() for r in e.target_runs]
        tokens = [r.tokens for r in runs if r.tokens is not None]
        scope = None
        ledger_readable = True
        if self._spend is not None:
            try:
                scope = self._spend.status()
            except BudgetExceededError:  # unreadable: the refusal itself must still be recorded
                ledger_readable = False
        complete = (
            ledger_readable
            and all(t.complete for t in tokens)
            and all(c.prompt_tokens is not None for c in self._calls)
        )
        local = any(c.evidence_source == "local_ollama" for c in self._calls)
        return InvestigationUsage(
            model_calls=len(self._calls),
            investigator_prompt_tokens=sum(c.prompt_tokens or 0 for c in self._calls),
            investigator_completion_tokens=sum(c.completion_tokens or 0 for c in self._calls),
            investigator_latency_ms=sum(c.latency_ms for c in self._calls),
            investigator_cost_usd=round(sum(c.estimated_cost_usd or 0 for c in self._calls), 6),
            target_runs=len(runs),
            target_tokens=sum(t.total_tokens for t in tokens),
            target_cost_usd=round(sum(r.estimated_cost_usd or 0 for r in runs), 6),
            sandbox_executions=sum(e.usage.sandbox_executions for e in self._evidence.values()),
            sandbox_ms=sum(e.usage.sandbox_ms for e in self._evidence.values()),
            wall_ms=int((self._monotonic() - self._started) * 1000),
            scope_settled_usd=scope.settled_usd if scope is not None else None,
            scope_open_usd=scope.open_reservations_usd if scope is not None else None,
            scope_limit_usd=self._spend.limit_usd if self._spend is not None else None,
            usage_complete=complete,
            **({"note": LOCAL_USAGE_NOTE} if local else {}),
        )

    def _report(self, finished_at: datetime | None) -> InvestigationReport:
        claims = self._conclusion.claimed_findings if self._conclusion is not None else []
        return InvestigationReport(
            investigation_id=self.investigation_id,
            request=self.request,
            model_evidence_source=self._model.evidence if self._model is not None else None,
            state=self._state,
            termination=self._termination,
            started_at=self._started_at,
            finished_at=finished_at,
            capability_sha256=self._capability_sha(),
            hypotheses=list(self._hypotheses.values()),
            decisions=self._decisions,
            proposals=self._proposals,
            experiments=self._experiments,
            observations=self._observations,
            model_calls=self._calls,
            model_conclusion=self._conclusion,
            findings=self._findings,
            claim_checks=check_claims(claims, self._evidence),
            statement=statement(self._findings),
            limitations=self._limitations(),
            usage=self._usage(),
            validity=InvestigationValidity(
                experiments=experiment_validity(self._evidence.values()),
                assessments=self._assessment_checks,
                repeated_hypotheses=repeated_hypotheses(self._hypotheses.values()),
                conclusion_matches_findings=conclusion_matches(self._conclusion, self._findings),
            ),
        )

    def _finish(self, stop: _Stop) -> InvestigationReport:
        self._build_findings()
        try:
            self._reproduce(stop)
        except BudgetExceededError:  # pragma: no cover - the target reports this as evidence
            log.warning("reproduction_refused")
        self._decide(DecisionKind.TERMINATE, stop.termination)
        self._termination = stop.termination
        check_transition(self._state, stop.state)
        self._state = stop.state
        self._workspace.journal("state", {"state": stop.state.value})
        report = self._report(datetime.now(UTC))
        self._workspace.save_state(report)
        self._workspace.save_report(report)
        return report
