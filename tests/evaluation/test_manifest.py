"""Registration: what is frozen, how the plan is derived, and when a run must refuse."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from pydantic import JsonValue

from moody_blues.config import Settings
from moody_blues.contracts.investigation import Strategy, WorldTier
from moody_blues.contracts.scenario import FaultSpec
from moody_blues.evaluation import manifest as registered
from moody_blues.evaluation.followup import build_followup
from moody_blues.evaluation.manifest import (
    Manifest,
    ManifestError,
    TrialPlan,
    canonical_sha,
    check_fingerprints,
    expand_plan,
    fixed_schedule,
    load_frozen,
    validate_manifest,
)
from moody_blues.evaluation.trials import fault_labels
from moody_blues.investigator.catalog import WORLD_TIERS, target_capability
from moody_blues.world.scenarios import load_scenario


def _write(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> tuple[Path, Path]:
    m, p = tmp_path / "manifest.json", tmp_path / "plan.json"
    m.write_text(manifest.model_dump_json(), "utf-8")
    p.write_text(plan.model_dump_json(), "utf-8")
    return m, p


def test_a_valid_registration_loads(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> None:
    assert load_frozen(*_write(tmp_path, manifest, plan)) == (manifest, plan)


def test_the_plan_is_reproducible_from_the_manifest(manifest: Manifest) -> None:
    assert expand_plan(manifest) == expand_plan(manifest)


def test_a_changed_manifest_is_refused_against_its_plan(
    tmp_path: Path, manifest: Manifest, plan: TrialPlan
) -> None:
    changed = manifest.model_copy(update={"order_seed": 1})
    with pytest.raises(ManifestError, match="not derived"):
        load_frozen(*_write(tmp_path, changed, plan))


def test_a_reordered_plan_is_refused(tmp_path: Path, manifest: Manifest, plan: TrialPlan) -> None:
    reordered = plan.model_copy(update={"strategies": tuple(reversed(plan.strategies))})
    with pytest.raises(ManifestError, match="does not match"):
        load_frozen(*_write(tmp_path, manifest, reordered))


def test_an_unreadable_registration_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "manifest.json"
    bad.write_text("{", "utf-8")
    with pytest.raises(ManifestError, match="cannot read"):
        load_frozen(bad, bad)


def test_freezing_never_overwrites(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "m.json"
    target.write_text("{}", "utf-8")
    monkeypatch.setattr(registered, "MANIFEST_PATH", target)
    with pytest.raises(ManifestError, match="already frozen"):
        registered.freeze(Settings(_env_file=None), settled_usd=0.0)  # type: ignore[call-arg]


def test_a_changed_prompt_or_world_is_detected(manifest: Manifest) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert check_fingerprints(manifest, settings) == []
    edited = manifest.fingerprints.model_copy(update={"system_prompt_sha256": "0" * 64})
    assert check_fingerprints(manifest.model_copy(update={"fingerprints": edited}), settings) == [
        "system_prompt_sha256"
    ]
    worlds = dict(manifest.fingerprints.world_sha256) | {"w-e3": "0" * 64}
    edited = manifest.fingerprints.model_copy(update={"world_sha256": worlds})
    assert check_fingerprints(manifest.model_copy(update={"fingerprints": edited}), settings) == [
        "world_sha256"
    ]


def test_a_different_model_is_detected(manifest: Manifest) -> None:
    other = Settings(_env_file=None, investigator_target_model="other")  # type: ignore[call-arg]
    assert check_fingerprints(manifest, other) == ["target_model"]


def test_suite_caps_cannot_exceed_the_sprint_limit(manifest: Manifest) -> None:
    budget = manifest.budget.model_copy(update={"causal_cap_usd": 4.0})
    with pytest.raises(ManifestError, match="exceed"):
        validate_manifest(manifest.model_copy(update={"budget": budget}))


def test_reserved_worlds_may_not_overlap_the_comparison(manifest: Manifest) -> None:
    suite = manifest.adaptation.model_copy(update={"worlds": ("w-e1",)})
    with pytest.raises(ManifestError, match="overlap"):
        validate_manifest(manifest.model_copy(update={"adaptation": suite}))


def test_a_fault_outside_the_action_space_is_refused(manifest: Manifest) -> None:
    family = manifest.strategies.fixed_families[0].model_copy(
        update={"faults": [{"kind": "stale_read", "occurrence": 1, "span": 7}]}
    )
    suite = manifest.strategies.model_copy(update={"fixed_families": (family,)})
    with pytest.raises(ValueError, match="span"):
        validate_manifest(manifest.model_copy(update={"strategies": suite}))


def test_the_ledger_limit_sits_above_what_is_already_spent(manifest: Manifest) -> None:
    assert manifest.budget.ledger_limit_usd == pytest.approx(7.5)


def test_the_hash_covers_the_whole_manifest(manifest: Manifest) -> None:
    budget = manifest.target_budget.model_copy(update={"max_steps": 13})
    assert canonical_sha(manifest) != canonical_sha(
        manifest.model_copy(update={"target_budget": budget})
    )


# --- matched conditions --------------------------------------------------------------------------


def test_blocks_cover_every_family_in_every_world_once(manifest: Manifest) -> None:
    suite = manifest.strategies
    cells = Counter(
        (world, condition.condition_id)
        for block in range(suite.blocks)
        for _, world, condition in fixed_schedule(suite, block)
    )
    assert len(cells) == len(suite.worlds) * len(suite.fixed_families)
    assert set(cells.values()) == {1}


def test_the_known_failure_is_in_the_grid_exactly_once(manifest: Manifest) -> None:
    """It must be reachable, and the grid must not be weighted towards it."""
    suite = manifest.strategies
    keys = [
        "|".join(
            (
                world,
                "baseline",
                ",".join(
                    fault_labels([FaultSpec.model_validate(_spec(f)) for f in condition.faults])
                )
                or "none",
            )
        )
        for block in range(suite.blocks)
        for _, world, condition in fixed_schedule(suite, block)
    ]
    assert keys.count(suite.known_failure_key) == 1


def _spec(fault: dict[str, JsonValue]) -> dict[str, JsonValue]:
    base = (
        {"operation": "read"} if fault["kind"] == "stale_read" else {"operation": "create_customer"}
    )
    extra = {"error_message": "x"} if fault["kind"] == "phantom_failure" else {}
    return base | extra | fault


def test_every_strategy_gets_the_same_worlds_budget_and_order_balance(
    manifest: Manifest, plan: TrialPlan
) -> None:
    counts = Counter(u.strategy for u in plan.strategies)
    assert counts == dict.fromkeys(Strategy, manifest.strategies.blocks)
    for block in range(1, manifest.strategies.blocks + 1):
        assert {u.strategy for u in plan.strategies if u.block == block} == set(Strategy)
    assert len(next(u for u in plan.strategies if u.strategy is Strategy.FIXED).fixed_schedule) == (
        manifest.strategies.limits.max_experiments
    )


def test_the_order_of_strategies_varies_between_blocks(plan: TrialPlan) -> None:
    orders = {tuple(u.strategy for u in plan.strategies if u.block == block) for block in (1, 2, 3)}
    assert len(orders) > 1


def test_no_strategy_gets_automatic_reruns(manifest: Manifest) -> None:
    assert manifest.strategies.limits.max_reproductions == 0


def test_causal_cells_are_balanced_in_every_block(manifest: Manifest, plan: TrialPlan) -> None:
    cells = len(manifest.causal.conditions) * len(manifest.causal.configs)
    for block in (1, 2, 3):
        trials = [t for t in plan.causal_stage_one if t.block == block]
        assert len({(t.condition_id, t.config) for t in trials}) == cells
    assert len(plan.causal_stage_two) == 2 * cells
    assert plan.causal_stage_one[:cells] != plan.causal_stage_one[cells : 2 * cells]


def test_the_control_differs_from_the_fault_arm_only_by_the_fault(manifest: Manifest) -> None:
    suite = manifest.causal
    conditions = {c.condition_id: c for c in suite.conditions}
    assert conditions[suite.control_condition].faults == []
    assert conditions[suite.fault_condition].faults[0]["span"] == 6
    assert conditions[suite.reduced_condition].faults[0]["span"] == 2


# --- reserved worlds -----------------------------------------------------------------------------


def test_reserved_worlds_are_neutral_and_carry_nothing_built_in() -> None:
    for world in WORLD_TIERS[WorldTier.RESERVED]:
        scenario = load_scenario(world)
        assert scenario.description == ""
        assert scenario.title.startswith("World ")
        assert scenario.faults == []


def test_reserved_worlds_are_not_used_outside_their_suite(manifest: Manifest) -> None:
    reserved = set(WORLD_TIERS[WorldTier.RESERVED])
    assert not reserved & set(manifest.strategies.worlds)
    assert manifest.causal.world not in reserved


def test_both_comparison_prompts_describe_the_same_capability(manifest: Manifest) -> None:
    worlds = manifest.strategies.worlds
    text = target_capability(worlds).model_dump_json()
    assert "1-6" in text  # the six-read severity is offered to every generating strategy
    assert all(world in text for world in worlds)


# --- the follow-up study -------------------------------------------------------------------------


def test_the_followup_changes_only_the_world_conditions_and_cap(manifest: Manifest) -> None:
    followup = build_followup(manifest)
    validate_manifest(followup)
    assert followup.target_budget == manifest.target_budget
    assert followup.fingerprints == manifest.fingerprints
    assert followup.budget.ledger_limit_usd == manifest.budget.ledger_limit_usd
    assert followup.causal.stage_one_rule == manifest.causal.stage_one_rule
    assert followup.causal.stage_two_rule == manifest.causal.stage_two_rule
    assert followup.causal.max_attempts_per_cell == manifest.causal.max_attempts_per_cell
    assert followup.manifest_id != manifest.manifest_id


def test_followup_contrasts_each_change_one_factor(manifest: Manifest) -> None:
    conditions = {c.condition_id: c.faults for c in build_followup(manifest).causal.conditions}
    full = conditions["full"]
    assert conditions["clean"] == []
    assert conditions["phantom-only"] == [full[0]]
    assert conditions["stale-only"] == [full[1]]
    assert conditions["reduced"][0] == full[0]
    assert conditions["reduced"][1]["span"] == 2
