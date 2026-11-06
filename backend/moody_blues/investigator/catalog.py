"""Which worlds an investigation may touch, and what it is told about them.

Tiers keep tuning apart from measurement:

- ``development``: legible names, used by fixtures and demos.
- ``validation``: used while developing the Investigator's prompt.
- ``evaluation``: used up. Sprint 5 evaluated and then diagnosed on these worlds, so results from
  them are regression evidence, not held-out evidence.
- ``reserved``: fresh in Sprint 6. Run only for its registered adaptation test, once. Results must
  not be used to revise the Investigator and then be reported as unseen again.

Validation and evaluation worlds have neutral ids and titles, and are the only ones an
investigation may be given in a live comparison. A ``WorldCard`` says how many seed customers
exist and nothing else: built-in faults, seed contents and any expected outcome stay out.
"""

from __future__ import annotations

from moody_blues.contracts.adapter import AgentManifest
from moody_blues.contracts.agent import AgentConfigName
from moody_blues.contracts.investigation import TargetCapability, WorldCard, WorldTier
from moody_blues.world.crm_plugin import EXPECTATIONS as EXPECTATIONS
from moody_blues.world.crm_plugin import MISSION as MISSION
from moody_blues.world.crm_plugin import PERTURBATIONS as PERTURBATIONS
from moody_blues.world.crm_plugin import WORLD_TYPE as CRM_WORLD_TYPE
from moody_blues.world.plugin import WorldPlugin
from moody_blues.world.registry import plugin_for_scenario, world_plugin

# The CRM's tiers. Registered manifests hash this table, so it stays as it was registered: a new
# world's scenarios are development worlds by ``tier_of``, and never enter it.
WORLD_TIERS: dict[WorldTier, tuple[str, ...]] = {
    WorldTier.DEVELOPMENT: (
        "clean-negative-control",
        "normal-success",
        "phantom-failure",
        "phantom-success",
        "preexisting-email",
    ),
    WorldTier.VALIDATION: ("w-v1", "w-v2", "w-v3"),
    WorldTier.EVALUATION: ("w-e1", "w-e2", "w-e3"),
    WorldTier.RESERVED: ("w-r1", "w-r2", "w-r3"),
}

EXTERNAL_MISSION = (
    "The target is an externally implemented {nature}, reached over a fixed protocol. You know "
    "nothing about how it works beyond what the runs show. Its mission in each world: {task}. "
    "An action's `config` is required by the protocol and has no "
    'effect on this target: always pass "baseline".'
)
_EXTERNAL_NATURE = {
    "scripted": "program that declares itself a fixed script",
    "llm": "agent that declares itself model-driven; any model it uses is reached through the host",
}


def tier_of(world_id: str) -> WorldTier:
    for tier, worlds in WORLD_TIERS.items():
        if world_id in worlds:
            return tier
    if plugin_for_scenario(world_id).descriptor.world_type != CRM_WORLD_TYPE:
        return WorldTier.DEVELOPMENT
    raise LookupError(f"world {world_id!r} is in no tier")


def world_of(world_ids: tuple[str, ...]) -> WorldPlugin:
    """The one world these scenarios belong to. An investigation never spans two."""
    plugins = {plugin_for_scenario(w).descriptor.world_type for w in world_ids}
    if len(plugins) != 1:
        raise ValueError("an investigation runs in exactly one world")
    return world_plugin(plugins.pop())


def world_cards(world_ids: tuple[str, ...]) -> list[WorldCard]:
    return world_of(world_ids).capability(world_ids).worlds


def target_capability(world_ids: tuple[str, ...]) -> TargetCapability:
    """Built by the selected world, so nothing about any other world can reach the model."""
    return world_of(world_ids).capability(world_ids)


def external_capability(
    manifest: AgentManifest, granted_tools: list[str], world_ids: tuple[str, ...]
) -> TargetCapability:
    """What may be known about an external target, from its registration and the host's grant.

    Only fixed strings and the host's own tool list: nothing an agent wrote reaches the model, not
    even its display name. Tools it was not granted are left out, because it cannot call them.
    """
    world = world_of(world_ids)
    internal = world.capability(world_ids)
    claim_tool = internal.tools[-1].name
    return internal.model_copy(
        update={
            "mission": EXTERNAL_MISSION.format(
                nature=_EXTERNAL_NATURE[manifest.target_type.value], task=world.external_task()
            ),
            "tools": [t for t in internal.tools if t.name in granted_tools or t.name == claim_tool],
            "configs": [AgentConfigName.BASELINE],
        }
    )
