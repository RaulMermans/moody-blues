"""The registered evaluation, as data. Frozen before any scored trial runs.

A manifest fixes everything that could otherwise drift or be chosen after seeing results: strategy
definitions, worlds, faults, trial counts, models, stopping rules, metrics, thresholds and budgets.
Its ``fingerprints`` record what the code actually is, so a run refuses to proceed if a prompt, a
policy or a world has changed since the freeze.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from moody_blues.agents.policies import POLICIES
from moody_blues.config import Settings
from moody_blues.contracts.agent import AgentBudget, AgentConfigName
from moody_blues.contracts.investigation import InvestigationLimits, Strategy, WorldTier
from moody_blues.contracts.protocol import FaultSelection
from moody_blues.evaluation.attribution import ContrastRule
from moody_blues.investigator.catalog import WORLD_TIERS, target_capability
from moody_blues.investigator.context import PROTOCOL, SYSTEM_PROMPT
from moody_blues.world.scenarios import SCENARIO_DIR

MANIFEST_ID = "sprint-06-v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_DIR = REPO_ROOT / "docs" / "evaluations" / "sprint-06"
MANIFEST_PATH = FROZEN_DIR / "manifest.json"
PLAN_PATH = FROZEN_DIR / "trial-plan.json"

Faults = list[dict[str, JsonValue]]
Outcome = Literal["recovered", "violation", "not_reached", "insufficient"]

_STALE_SHORT: Faults = [{"kind": "stale_read", "occurrence": 1, "span": 2}]
_STALE_LONG: Faults = [{"kind": "stale_read", "occurrence": 1, "span": 6}]
_PHANTOM_FAILURE: Faults = [{"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}]
_PHANTOM_SUCCESS: Faults = [{"kind": "phantom_success", "occurrence": 1}]


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition_id: str
    faults: Faults


class CausalSuite(BaseModel):
    """One design answers causation, reproduction and hardening: 3 fault levels x 2 policies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    world: str
    conditions: tuple[Condition, ...]
    configs: tuple[AgentConfigName, ...]
    stage_one_eligible: int
    stage_two_eligible: int
    # Attempts per cell, counting impaired ones. Stops replacement from running forever.
    max_attempts_per_cell: int
    fault_condition: str
    reduced_condition: str
    control_condition: str
    stage_one_rule: ContrastRule
    stage_two_rule: ContrastRule


class StrategySuite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    worlds: tuple[str, ...]
    results_label: Literal["regression_not_held_out"]
    limits: InvestigationLimits
    blocks: int
    # Rotated across worlds by block, so the blocks together cover every family in every world.
    fixed_families: tuple[Condition, ...]
    # The condition Sprint 5 found. Coverage is scored against it and it reaches no prompt.
    known_failure_key: str
    long_stale_label: str


class Branch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Outcome
    executor: str
    faults: Faults


class AdaptationCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    world: str
    branches: tuple[Branch, ...]
    # Runs the no-observation control. Same executor as "recovered", so discovery is comparable.
    blind_executor: str
    # Whether that executor has a weakness elsewhere for a follow-up to find.
    discovery_possible: bool


class AdaptationSuite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    worlds: tuple[str, ...]
    results_label: Literal["reserved_first_use"]
    limits: InvestigationLimits
    cases: tuple[AdaptationCase, ...]
    repeats: int
    experiments_remaining: int
    model_calls_remaining: int
    # A branch shows adaptation if its justified rate beats the no-observation control scored
    # under the same rubric by at least this much.
    justified_delta_threshold: float
    sensitivity_distance_threshold: float
    min_cases_passing: int
    discovery_margin: int


class BudgetPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sprint_limit_usd: float
    ledger_settled_at_freeze_usd: float
    causal_cap_usd: float
    strategies_cap_usd: float
    adaptation_cap_usd: float
    stage_two_safety_factor: float

    @property
    def ledger_limit_usd(self) -> float:
        """The same ledger keeps counting: nothing is reset, the limit just sits above it."""
        return round(self.ledger_settled_at_freeze_usd + self.sprint_limit_usd, 6)


class Fingerprints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system_prompt_sha256: str
    protocol_sha256: str
    capability_sha256: dict[str, str]
    policy_sha256: dict[str, str]
    world_sha256: dict[str, str]
    investigator_model: str
    target_model: str


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: str
    order_seed: int
    target_budget: AgentBudget
    causal: CausalSuite
    strategies: StrategySuite
    adaptation: AdaptationSuite
    budget: BudgetPlan
    fingerprints: Fingerprints


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def compute_fingerprints(settings: Settings, worlds: tuple[str, ...]) -> Fingerprints:
    tiers = (WorldTier.EVALUATION, WorldTier.RESERVED)
    return Fingerprints(
        system_prompt_sha256=_sha(SYSTEM_PROMPT),
        protocol_sha256=_sha(PROTOCOL),
        capability_sha256={
            tier.value: _sha(target_capability(WORLD_TIERS[tier]).model_dump_json())
            for tier in tiers
        },
        policy_sha256={name.value: policy.sha256 for name, policy in POLICIES.items()},
        world_sha256={
            world: _sha((SCENARIO_DIR / f"{world}.json").read_text(encoding="utf-8"))
            for world in worlds
        },
        investigator_model=settings.investigator_model,
        target_model=settings.investigator_target_model,
    )


def build_manifest(settings: Settings, *, settled_usd: float) -> Manifest:
    worlds_e = WORLD_TIERS[WorldTier.EVALUATION]
    worlds_r = WORLD_TIERS[WorldTier.RESERVED]
    limits = InvestigationLimits(
        max_experiments=6,
        max_model_calls=10,
        max_refinements=2,
        max_reproductions=0,  # a rerun would be budget one strategy gets and another does not
        max_wall_seconds=2_400.0,
    )
    stale_four: Faults = [{"kind": "stale_read", "occurrence": 1, "span": 4}]
    return Manifest(
        manifest_id=MANIFEST_ID,
        order_seed=20261104,
        # Sprint 5 ran 10 steps, 16 calls, 30,000 tokens, 4,096 per step and 180 s. Three of ten
        # runs at six stale reads hit those, so they are raised for every arm alike (KI-31).
        target_budget=AgentBudget(
            max_steps=14,
            max_tool_calls=24,
            max_total_tokens=40_000,
            max_completion_tokens=8_192,
            max_wall_seconds=240,
        ),
        causal=CausalSuite(
            world="w-e3",
            conditions=(
                Condition(condition_id="clean", faults=[]),
                Condition(condition_id="stale-2", faults=_STALE_SHORT),
                Condition(condition_id="stale-6", faults=_STALE_LONG),
            ),
            configs=(AgentConfigName.BASELINE, AgentConfigName.HARDENED),
            stage_one_eligible=3,
            stage_two_eligible=5,
            max_attempts_per_cell=7,
            fault_condition="stale-6",
            reduced_condition="stale-2",
            control_condition="clean",
            stage_one_rule=ContrastRule(required_eligible_per_arm=3, min_failures_in_fault_arm=3),
            stage_two_rule=ContrastRule(required_eligible_per_arm=5, min_failures_in_fault_arm=2),
        ),
        strategies=StrategySuite(
            worlds=worlds_e,
            results_label="regression_not_held_out",
            limits=limits,
            blocks=3,
            fixed_families=(
                Condition(condition_id="none", faults=[]),
                Condition(condition_id="phantom-failure", faults=_PHANTOM_FAILURE),
                Condition(condition_id="phantom-success", faults=_PHANTOM_SUCCESS),
                Condition(condition_id="stale-2", faults=_STALE_SHORT),
                Condition(condition_id="stale-6", faults=_STALE_LONG),
                Condition(
                    condition_id="failure-and-stale-6", faults=_PHANTOM_FAILURE + _STALE_LONG
                ),
            ),
            known_failure_key="w-e3|baseline|stale_read#1x6",
            long_stale_label="stale_read#1x6",
        ),
        adaptation=AdaptationSuite(
            worlds=worlds_r,
            results_label="reserved_first_use",
            limits=InvestigationLimits(),
            cases=(
                AdaptationCase(
                    case_id="case-a",
                    world="w-r1",
                    branches=(
                        Branch(
                            outcome="recovered",
                            executor="verify_then_report",
                            faults=_PHANTOM_FAILURE,
                        ),
                        Branch(
                            outcome="violation", executor="blind_retry", faults=_PHANTOM_FAILURE
                        ),
                        Branch(
                            outcome="not_reached",
                            executor="verify_then_report",
                            faults=[
                                {
                                    "kind": "phantom_failure",
                                    "occurrence": 3,
                                    "error_code": "timeout",
                                }
                            ],
                        ),
                        Branch(
                            outcome="insufficient", executor="trusting", faults=_PHANTOM_FAILURE
                        ),
                    ),
                    blind_executor="verify_then_report",
                    discovery_possible=True,
                ),
                AdaptationCase(
                    case_id="case-b",
                    world="w-r1",
                    branches=(
                        Branch(outcome="recovered", executor="idempotent_retry", faults=stale_four),
                        Branch(
                            outcome="violation", executor="verify_then_report", faults=stale_four
                        ),
                        Branch(outcome="not_reached", executor="trusting", faults=stale_four),
                        Branch(
                            outcome="insufficient",
                            executor="idempotent_retry",
                            faults=_STALE_LONG,
                        ),
                    ),
                    blind_executor="idempotent_retry",
                    discovery_possible=False,
                ),
                AdaptationCase(
                    case_id="case-c",
                    world="w-r1",
                    branches=(
                        Branch(
                            outcome="recovered",
                            executor="verify_then_report",
                            faults=_PHANTOM_SUCCESS,
                        ),
                        Branch(outcome="violation", executor="trusting", faults=_PHANTOM_SUCCESS),
                        Branch(
                            outcome="not_reached",
                            executor="verify_then_report",
                            faults=[{"kind": "phantom_success", "occurrence": 3}],
                        ),
                    ),
                    blind_executor="verify_then_report",
                    discovery_possible=True,
                ),
            ),
            repeats=4,
            experiments_remaining=2,
            model_calls_remaining=4,
            justified_delta_threshold=0.5,
            sensitivity_distance_threshold=0.5,
            min_cases_passing=2,
            discovery_margin=2,
        ),
        budget=BudgetPlan(
            sprint_limit_usd=5.0,
            ledger_settled_at_freeze_usd=settled_usd,
            causal_cap_usd=1.5,
            strategies_cap_usd=2.6,
            adaptation_cap_usd=0.9,
            stage_two_safety_factor=1.5,
        ),
        fingerprints=compute_fingerprints(settings, (*worlds_e, *worlds_r)),
    )


# --- the plan ------------------------------------------------------------------------------------


class PlannedCausalTrial(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str
    block: int
    condition_id: str
    config: AgentConfigName


class PlannedInvestigation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    block: int
    strategy: Strategy
    # (label, world, faults) of each fixed experiment; empty for model-driven strategies.
    fixed_schedule: tuple[tuple[str, str, Condition], ...] = ()


class PlannedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    answer_id: str
    case_id: str
    branch: str  # an Outcome, or "blind"
    repeat: int


class TrialPlan(BaseModel):
    """The balanced, randomized order. Derived from the manifest, so anyone can regenerate it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_sha256: str
    causal_stage_one: tuple[PlannedCausalTrial, ...]
    causal_stage_two: tuple[PlannedCausalTrial, ...]
    strategies: tuple[PlannedInvestigation, ...]
    adaptation: tuple[PlannedAnswer, ...]


def canonical_sha(manifest: Manifest) -> str:
    return _sha(json.dumps(manifest.model_dump(mode="json"), sort_keys=True))


def _causal_block(manifest: Manifest, block: int) -> list[PlannedCausalTrial]:
    suite = manifest.causal
    cells = [(c.condition_id, cfg) for c in suite.conditions for cfg in suite.configs]
    random.Random(f"{manifest.order_seed}:causal:{block}").shuffle(cells)  # noqa: S311 - ordering
    return [
        PlannedCausalTrial(
            trial_id=f"c{block}-{condition}-{config.value}",
            block=block,
            condition_id=condition,
            config=config,
        )
        for condition, config in cells
    ]


def fixed_schedule(suite: StrategySuite, block: int) -> tuple[tuple[str, str, Condition], ...]:
    worlds = suite.worlds
    return tuple(
        (
            f"fixed-{family.condition_id}-{worlds[(index + block) % len(worlds)]}",
            worlds[(index + block) % len(worlds)],
            family,
        )
        for index, family in enumerate(suite.fixed_families)
    )


def expand_plan(manifest: Manifest) -> TrialPlan:
    suite = manifest.causal
    first = [t for b in range(1, suite.stage_one_eligible + 1) for t in _causal_block(manifest, b)]
    second = [
        t
        for b in range(suite.stage_one_eligible + 1, suite.stage_two_eligible + 1)
        for t in _causal_block(manifest, b)
    ]
    units: list[PlannedInvestigation] = []
    for block in range(manifest.strategies.blocks):
        order = [Strategy.FIXED, Strategy.ONE_SHOT, Strategy.ADAPTIVE]
        random.Random(f"{manifest.order_seed}:strategies:{block}").shuffle(order)  # noqa: S311
        units.extend(
            PlannedInvestigation(
                unit_id=f"s{block + 1}-{strategy.value}",
                block=block + 1,
                strategy=strategy,
                fixed_schedule=fixed_schedule(manifest.strategies, block)
                if strategy is Strategy.FIXED
                else (),
            )
            for strategy in order
        )
    answers: list[PlannedAnswer] = []
    for case in manifest.adaptation.cases:
        for branch in (*(b.outcome for b in case.branches), "blind"):
            answers.extend(
                PlannedAnswer(
                    answer_id=f"{case.case_id}-{branch}-{repeat}",
                    case_id=case.case_id,
                    branch=branch,
                    repeat=repeat,
                )
                for repeat in range(1, manifest.adaptation.repeats + 1)
            )
    random.Random(f"{manifest.order_seed}:adaptation").shuffle(answers)  # noqa: S311 - ordering
    return TrialPlan(
        manifest_sha256=canonical_sha(manifest),
        causal_stage_one=tuple(first),
        causal_stage_two=tuple(second),
        strategies=tuple(units),
        adaptation=tuple(answers),
    )


# --- freezing ------------------------------------------------------------------------------------


class ManifestError(RuntimeError):
    """The registration does not hold. No scored trial may run."""


def validate_manifest(manifest: Manifest) -> None:
    """Structural rules a frozen evaluation must meet, whatever its numbers."""
    suite = manifest.strategies
    for family in (*suite.fixed_families, *manifest.causal.conditions):
        for fault in family.faults:
            # As the coordinator reads it: inside the action space every strategy has.
            FaultSelection.model_validate_json(json.dumps(fault))
    for case in manifest.adaptation.cases:
        for branch in case.branches:
            for fault in branch.faults:
                FaultSelection.model_validate_json(json.dumps(fault))
    if set(manifest.adaptation.worlds) & set(suite.worlds):
        raise ManifestError("reserved adaptation worlds overlap the regression worlds")
    if manifest.causal.world not in suite.worlds:
        raise ManifestError("the causal world must be in the comparison")
    if suite.known_failure_key.split("|")[0] != manifest.causal.world:
        raise ManifestError("the known failure must be the one the causal suite studies")
    b = manifest.budget
    caps = b.causal_cap_usd + b.strategies_cap_usd + b.adaptation_cap_usd
    if caps > b.sprint_limit_usd + 1e-9:
        raise ManifestError(f"suite caps ${caps:.2f} exceed the sprint limit")


def load_frozen(
    path: Path = MANIFEST_PATH, plan_path: Path = PLAN_PATH
) -> tuple[Manifest, TrialPlan]:
    try:
        manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
        plan = TrialPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read the frozen evaluation: {exc}") from exc
    validate_manifest(manifest)
    if plan.manifest_sha256 != canonical_sha(manifest):
        raise ManifestError("the trial plan was not derived from this manifest")
    if plan != expand_plan(manifest):
        raise ManifestError("the trial plan does not match what the manifest generates")
    return manifest, plan


def check_fingerprints(manifest: Manifest, settings: Settings) -> list[str]:
    worlds = tuple(manifest.fingerprints.world_sha256)
    current = compute_fingerprints(settings, worlds).model_dump()
    frozen = manifest.fingerprints.model_dump()
    return sorted(key for key in frozen if frozen[key] != current[key])


def committed_head(paths: tuple[Path, ...] = (MANIFEST_PATH, PLAN_PATH)) -> str:
    """The commit holding the registration. Refuses files that are uncommitted or modified."""
    names = [str(p) for p in paths]
    status = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", *names],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    if status.stdout.strip():
        raise ManifestError("the manifest or plan is not committed; commit before scoring")
    head = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return head.stdout.strip()


def freeze(settings: Settings, *, settled_usd: float) -> tuple[Manifest, TrialPlan]:
    """Write the registration once. An existing one is never overwritten."""
    if MANIFEST_PATH.exists() or PLAN_PATH.exists():
        raise ManifestError("already frozen; a change needs a new manifest id and a stated reason")
    manifest = build_manifest(settings, settled_usd=settled_usd)
    validate_manifest(manifest)
    plan = expand_plan(manifest)
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    PLAN_PATH.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest, plan
