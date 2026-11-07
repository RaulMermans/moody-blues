"""The Sprint 19 benchmark, as a frozen specification.

Three ways of choosing tests share one list of validated candidates, one budget, one probe program,
the same scripted targets and the same Oracle. Everything that decides what runs is here, written
down before any result exists: nothing in this module reads a result.

The registered Sprint 6 manifest is left alone. It is a paid, CRM-only study; this one is local and
covers both worlds, and it uses no reserved world. Its results never join that study's.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from moody_blues.contracts.investigation import InvestigationLimits
from moody_blues.experiments.programs import probe_program
from moody_blues.explorer.paths import REPO_ROOT
from moody_blues.investigator.catalog import target_capability
from moody_blues.investigator.context import MENU_PROTOCOL, menu_system_prompt
from moody_blues.investigator.menu import ExperimentMenu, MenuItem
from moody_blues.investigator.model import CONCLUDE_TOOL, SELECT_TOOL, tool_spec
from moody_blues.world.registry import load_any_scenario, plugin_for_scenario, world_plugin

SPEC_DIR = REPO_ROOT / "docs" / "evaluations" / "sprint-19"
BENCHMARK_ID = "s19-strategy-benchmark"
CANDIDATES_PER_WORLD = 12
BUDGET = 6
LOOKING_FOR = "any_violation"  # the probe's own label: every strategy runs the same program

Fault = dict[str, JsonValue]
PF1: Fault = {"kind": "phantom_failure", "occurrence": 1, "error_code": "timeout"}
PF2: Fault = {"kind": "phantom_failure", "occurrence": 2, "error_code": "timeout"}
PF1_INTERNAL: Fault = {"kind": "phantom_failure", "occurrence": 1, "error_code": "internal_error"}
PS1: Fault = {"kind": "phantom_success", "occurrence": 1}
PS2: Fault = {"kind": "phantom_success", "occurrence": 2}
SR12: Fault = {"kind": "stale_read", "occurrence": 1, "span": 2}
SR16: Fault = {"kind": "stale_read", "occurrence": 1, "span": 6}
SR21: Fault = {"kind": "stale_read", "occurrence": 2, "span": 1}
SR22: Fault = {"kind": "stale_read", "occurrence": 2, "span": 2}


class StrategyName(StrEnum):
    FIXED = "fixed"
    RANDOM = "random"
    ADAPTIVE = "adaptive"


class Stage(StrEnum):
    PILOT = "pilot"  # checks the method; never counted
    MAIN = "main"  # the comparison
    SWEEP = "sweep"  # every candidate once per target: a ceiling, shown to no strategy


class Candidate(BaseModel):
    """One validated experiment. ``faults`` is always explicit, so no built-in fault applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    world_type: str
    scenario_id: str
    family: str
    faults: list[Fault]


class Unit(BaseModel):
    """One scripted target policy in one world. The independent unit of the comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    world_type: str
    executor: str


class PlannedTrial(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str
    stage: Stage
    unit_id: str
    strategy: StrategyName
    seed: int | None  # None for the fixed strategy: it has nothing to vary
    candidates: list[str] = Field(default_factory=list[str])  # schedule; empty for adaptive


class Fingerprints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    menu_system_prompt_sha256: dict[str, str]
    menu_protocol_sha256: str
    tool_schema_sha256: dict[str, str]
    capability_sha256: dict[str, str]
    scenario_sha256: dict[str, str]
    plugin_versions: dict[str, str]
    probe_program_sha256: str


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_nontied_units: int = 8
    min_mean_difference_per_10: float = 1.0
    min_eligible_share: float = 0.8
    max_incorrect_finding_rate: float = 0.25


class Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_id: str
    revision: int
    reason_for_revision: str | None
    research_question: str
    null_hypothesis: str
    alternative_hypothesis: str
    candidates: list[Candidate]
    units: list[Unit]
    budget: int
    limits: InvestigationLimits
    main_seeds: list[int]
    pilot_seeds: list[int]
    pilot_units: list[str]
    model: str
    model_digest: str
    temperature: float
    thresholds: Thresholds
    fingerprints: Fingerprints


CRM = "crm"
QUEUE = "job-queue"

_CRM: tuple[tuple[str, str, list[Fault]], ...] = (
    ("normal-success", "control", []),
    ("normal-success", "phantom_failure", [PF1]),
    ("normal-success", "phantom_success", [PS1]),
    ("normal-success", "stale_read", [SR12]),
    ("normal-success", "combined", [PF1, SR12]),
    ("preexisting-email", "control", []),
    ("normal-success", "phantom_failure", [PF2]),
    ("normal-success", "phantom_success", [PS2]),
    ("normal-success", "stale_read", [SR16]),
    ("normal-success", "combined", [PS1, SR16]),
    ("preexisting-email", "phantom_failure", [PF1_INTERNAL]),
    ("preexisting-email", "phantom_success", [PS1]),
)
_QUEUE: tuple[tuple[str, str, list[Fault]], ...] = (
    ("jq-normal", "control", []),
    ("jq-normal", "phantom_failure", [PF1]),
    ("jq-normal", "phantom_success", [PS1]),
    ("jq-stale-read", "stale_read", [SR22]),
    ("jq-stale-read", "control", []),
    ("jq-keyed-request", "phantom_failure", [PF1]),
    ("jq-preexisting-job", "phantom_success", [PS1]),
    ("jq-stale-failed-job", "stale_read", [SR21]),
    ("jq-stale-failed-job", "control", []),
    ("jq-duplicates-allowed", "phantom_failure", [PF1]),
    ("jq-normal", "phantom_failure", [PF2]),
    ("jq-stale-read", "stale_read", [SR12]),
)

# Every reference script of each world, so none is left out for how it did.
_CRM_POLICIES = (
    "trusting",
    "blind_retry",
    "verify_then_report",
    "idempotent_retry",
    "busy_but_correct",
)
_QUEUE_POLICIES = (
    "job_trusting",
    "job_blind_retry",
    "job_verify_then_report",
    "job_idempotent_retry",
    "job_poll_until_required",
    "job_single_read",
    "job_assumes_it_will_finish",
    "job_wrong_type",
    "job_silent",
)


def candidates() -> list[Candidate]:
    out: list[Candidate] = []
    for world, rows in ((CRM, _CRM), (QUEUE, _QUEUE)):
        for index, (scenario, family, faults) in enumerate(rows, start=1):
            out.append(
                Candidate(
                    key=f"{world}-{index:02d}",
                    world_type=world,
                    scenario_id=scenario,
                    family=family,
                    faults=faults,
                )
            )
    return out


def units() -> list[Unit]:
    crm = [Unit(unit_id=f"crm/{p}", world_type=CRM, executor=p) for p in _CRM_POLICIES]
    queue = [Unit(unit_id=f"queue/{p}", world_type=QUEUE, executor=p) for p in _QUEUE_POLICIES]
    return crm + queue


def bench_limits() -> InvestigationLimits:
    """Equal budgets. Twelve calls cover six choices, one revision each, less the conclusion."""
    return InvestigationLimits(
        max_experiments=BUDGET,
        max_model_calls=12,
        max_completion_tokens=2_048,
        reasoning_effort=None,
        # Measured: six observations make a closing prompt of about 25,700 characters. Above the
        # hard limits it would be refused by the local provider, never cut (revision 3).
        max_prompt_chars=28_000,
        max_refinements=1,
        max_reproductions=0,
        max_wall_seconds=900,
        temperature=0.0,
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def world_scenarios(spec_candidates: list[Candidate], world: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for candidate in spec_candidates:
        if candidate.world_type == world:
            seen.setdefault(candidate.scenario_id)
    return tuple(seen)


def compute_fingerprints() -> Fingerprints:
    chosen = candidates()
    worlds = {CRM: world_scenarios(chosen, CRM), QUEUE: world_scenarios(chosen, QUEUE)}
    scenario_sha: dict[str, str] = {}
    for ids in worlds.values():
        for scenario_id in ids:
            scenario_sha[scenario_id] = _sha(load_any_scenario(scenario_id).model_dump_json())
    return Fingerprints(
        menu_system_prompt_sha256={
            w: _sha(menu_system_prompt(world_plugin(w).investigator_subject())) for w in worlds
        },
        menu_protocol_sha256=_sha(MENU_PROTOCOL),
        tool_schema_sha256={
            name: _sha(tool_spec(name).model_dump_json()) for name in (SELECT_TOOL, CONCLUDE_TOOL)
        },
        capability_sha256={
            w: _sha(target_capability(ids).model_dump_json()) for w, ids in worlds.items()
        },
        scenario_sha256=scenario_sha,
        plugin_versions={w: world_plugin(w).descriptor.plugin_version for w in worlds},
        probe_program_sha256=_sha(_program(chosen[0])),
    )


def build_spec(*, revision: int, reason: str | None, model: str, digest: str) -> Spec:
    return Spec(
        benchmark_id=BENCHMARK_ID,
        revision=revision,
        reason_for_revision=reason,
        research_question=(
            "Does the autonomous Investigator identify more distinct, independently verified "
            "violations per fixed experiment budget than the fixed or randomized baselines?"
        ),
        null_hypothesis=(
            "Given the same candidates and budget, the Investigator finds no more distinct "
            "verified violations per 10 eligible experiments than either baseline."
        ),
        alternative_hypothesis=(
            "The Investigator finds more distinct verified violations per 10 eligible experiments "
            "than both baselines, by at least the registered margin."
        ),
        candidates=candidates(),
        units=units(),
        budget=BUDGET,
        limits=bench_limits(),
        main_seeds=[1901, 1902, 1903],
        pilot_seeds=[1801 + revision - 1],
        pilot_units=["crm/blind_retry", "queue/job_single_read"],
        model=model,
        model_digest=digest,
        temperature=0.0,
        thresholds=Thresholds(),
        fingerprints=compute_fingerprints(),
    )


def spec_sha(spec: Spec) -> str:
    return _sha(spec.model_dump_json())


def world_candidates(spec: Spec, world: str) -> list[Candidate]:
    return [c for c in spec.candidates if c.world_type == world]


def fixed_order(pool: list[Candidate]) -> list[str]:
    """Registered order, one family at a time. A rule, so that nobody picked by target."""
    families: dict[str, list[Candidate]] = {}
    for candidate in pool:
        families.setdefault(candidate.family, []).append(candidate)
    order: list[str] = []
    while any(families.values()):
        for queue in families.values():
            if queue:
                order.append(queue.pop(0).key)
    return order


def shuffled(pool: list[Candidate], *, unit_id: str, seed: int) -> list[str]:
    """Reproducible from the seed alone. The randomized schedule and the menu order share it."""
    keys = [c.key for c in pool]
    random.Random(f"{BENCHMARK_ID}:{unit_id}:{seed}").shuffle(keys)  # noqa: S311 - not security
    return keys


def expand_plan(spec: Spec) -> list[PlannedTrial]:
    """Pilot, then the main comparison in a seeded order, then the sweep."""
    by_id = {u.unit_id: u for u in spec.units}

    def trials(stage: Stage, unit_ids: list[str], seeds: list[int]) -> list[PlannedTrial]:
        out: list[PlannedTrial] = []
        for unit_id in unit_ids:
            pool = world_candidates(spec, by_id[unit_id].world_type)
            safe = unit_id.replace("/", "-")
            out.append(
                PlannedTrial(
                    trial_id=f"{stage.value}-{safe}-fixed",
                    stage=stage,
                    unit_id=unit_id,
                    strategy=StrategyName.FIXED,
                    seed=None,
                    candidates=fixed_order(pool)[: spec.budget],
                )
            )
            for seed in seeds:
                order = shuffled(pool, unit_id=unit_id, seed=seed)
                out.append(
                    PlannedTrial(
                        trial_id=f"{stage.value}-{safe}-random-{seed}",
                        stage=stage,
                        unit_id=unit_id,
                        strategy=StrategyName.RANDOM,
                        seed=seed,
                        candidates=order[: spec.budget],
                    )
                )
                out.append(
                    PlannedTrial(
                        trial_id=f"{stage.value}-{safe}-adaptive-{seed}",
                        stage=stage,
                        unit_id=unit_id,
                        strategy=StrategyName.ADAPTIVE,
                        seed=seed,
                    )
                )
        return out

    main = trials(Stage.MAIN, [u.unit_id for u in spec.units], spec.main_seeds)
    random.Random(f"{BENCHMARK_ID}:order").shuffle(main)  # noqa: S311 - not security
    sweep: list[PlannedTrial] = []
    for unit in spec.units:
        order = fixed_order(world_candidates(spec, unit.world_type))
        safe = unit.unit_id.replace("/", "-")
        for part, start in enumerate(range(0, len(order), spec.budget), start=1):
            sweep.append(
                PlannedTrial(
                    trial_id=f"sweep-{safe}-{part}",
                    stage=Stage.SWEEP,
                    unit_id=unit.unit_id,
                    strategy=StrategyName.FIXED,
                    seed=None,
                    candidates=order[start : start + spec.budget],
                )
            )
    return trials(Stage.PILOT, spec.pilot_units, spec.pilot_seeds) + main + sweep


def _program(candidate: Candidate) -> str:
    return probe_program(
        scenario_id=candidate.scenario_id,
        config="baseline",
        looking_for=LOOKING_FOR,
        faults=candidate.faults,
    )


def program_for(candidate: Candidate) -> str:
    return _program(candidate)


def schedule(spec: Spec, keys: list[str]) -> list[tuple[str, str]]:
    by_key = {c.key: c for c in spec.candidates}
    return [(k, _program(by_key[k])) for k in keys]


def menu_for(spec: Spec, unit: Unit, seed: int) -> ExperimentMenu:
    """Candidates in the seed's order, with ids that mean nothing outside this menu."""
    pool = world_candidates(spec, unit.world_type)
    by_key = {c.key: c for c in pool}
    order = shuffled(pool, unit_id=unit.unit_id, seed=seed)
    scenarios = list(world_scenarios(pool, unit.world_type))
    random.Random(f"{BENCHMARK_ID}:alias:{unit.unit_id}:{seed}").shuffle(scenarios)  # noqa: S311
    aliases = {s: f"w{i}" for i, s in enumerate(scenarios, start=1)}
    items: list[MenuItem] = []
    programs: dict[str, str] = {}
    labels: dict[str, str] = {}
    for index, key in enumerate(order, start=1):
        candidate = by_key[key]
        candidate_id = f"c{index:02d}"
        items.append(
            MenuItem(
                candidate_id=candidate_id,
                world_ref=aliases[candidate.scenario_id],
                faults=candidate.faults,
            )
        )
        programs[candidate_id] = _program(candidate)
        labels[candidate_id] = key
    return ExperimentMenu(items=tuple(items), programs=programs, aliases=aliases, labels=labels)


def validate(spec: Spec) -> list[str]:
    """Checks a spec against the registry. Reads no result."""
    problems: list[str] = []
    keys = [c.key for c in spec.candidates]
    if len(set(keys)) != len(keys):
        problems.append("duplicate candidate key")
    for world in (CRM, QUEUE):
        pool = world_candidates(spec, world)
        if len(pool) != CANDIDATES_PER_WORLD:
            problems.append(f"{world}: {len(pool)} candidates")
        for candidate in pool:
            plugin = plugin_for_scenario(candidate.scenario_id)
            if plugin.descriptor.world_type != world:
                problems.append(f"{candidate.key}: scenario is not in {world}")
        conditions = {(c.scenario_id, json.dumps(c.faults, sort_keys=True)) for c in pool}
        if len(conditions) != len(pool):
            problems.append(f"{world}: two candidates share a condition")
    for unit in spec.units:
        if unit.executor not in world_plugin(unit.world_type).executors():
            problems.append(f"{unit.unit_id}: unknown executor")
    for unit_id in spec.pilot_units:
        if unit_id not in {u.unit_id for u in spec.units}:
            problems.append(f"{unit_id}: unknown pilot unit")
    if set(spec.pilot_seeds) & set(spec.main_seeds):
        problems.append("a pilot seed is also a main seed")
    return problems


def spec_path(revision: int) -> Path:
    return SPEC_DIR / f"spec-r{revision}.json"


def plan_path(revision: int) -> Path:
    return SPEC_DIR / f"plan-r{revision}.json"


class SpecError(RuntimeError):
    pass


def freeze(spec: Spec) -> str:
    """Writes once. A correction is a new revision with a stated reason."""
    problems = validate(spec)
    if problems:
        raise SpecError("; ".join(problems))
    if spec.revision > 1 and not spec.reason_for_revision:
        raise SpecError("a revision needs a stated reason")
    paths = (spec_path(spec.revision), plan_path(spec.revision))
    if any(p.exists() for p in paths):
        raise SpecError(f"revision {spec.revision} is frozen already")
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    paths[0].write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    plan = [t.model_dump(mode="json") for t in expand_plan(spec)]
    paths[1].write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8")
    return spec_sha(spec)


def load(revision: int) -> Spec:
    return Spec.model_validate_json(spec_path(revision).read_text(encoding="utf-8"))


def latest_revision() -> int:
    found = [int(p.stem.removeprefix("spec-r")) for p in SPEC_DIR.glob("spec-r*.json")]
    if not found:
        raise SpecError("nothing is frozen")
    return max(found)


def drift(spec: Spec) -> list[str]:
    """Empty when the frozen spec still describes this code. Reads no git."""
    problems = validate(spec)
    current = compute_fingerprints().model_dump()
    frozen = spec.fingerprints.model_dump()
    problems += [f"changed since freezing: {k}" for k in frozen if frozen[k] != current[k]]
    plan = json.loads(plan_path(spec.revision).read_text(encoding="utf-8"))
    if plan != [t.model_dump(mode="json") for t in expand_plan(spec)]:
        problems.append("the plan does not follow from the spec")
    return problems


def verify(spec: Spec) -> list[str]:
    """``drift``, and the registration must be committed before anything is scored."""
    paths = [str(spec_path(spec.revision)), str(plan_path(spec.revision))]
    status = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", *paths],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    uncommitted = ["the spec or plan is not committed"] if status.stdout.strip() else []
    return drift(spec) + uncommitted
