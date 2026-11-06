"""The trusted list of worlds. Adding one is a code change, reviewed like any other.

There is deliberately no dynamic import, entry point, or configuration here. Nothing a request, an
agent or an experiment sends can reach this list, and a selection names an entry, never a module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from moody_blues.contracts.scenario import ScenarioBase
from moody_blues.contracts.world_plugin import SUPPORTED_WORLD_CONTRACTS, WorldProvenance
from moody_blues.world.crm_plugin import CrmPlugin
from moody_blues.world.jobqueue.plugin import JobQueuePlugin
from moody_blues.world.plugin import WorldPlugin


class UnknownWorldError(LookupError):
    pass


class UnsupportedWorldError(ValueError):
    """A plugin, or a recorded version of one, this build cannot stand behind."""


def validate_plugin(plugin: WorldPlugin) -> None:
    d = plugin.descriptor
    if d.contract_version not in SUPPORTED_WORLD_CONTRACTS:
        raise UnsupportedWorldError(f"{d.world_type}: contract {d.contract_version} not supported")
    tools = [t.spec.name for t in plugin.tools()]
    if tuple(tools) != d.tools:
        raise UnsupportedWorldError(f"{d.world_type}: tools differ from its descriptor")
    if d.shape.write_tool not in tools or not set(d.shape.read_tools) <= set(tools):
        raise UnsupportedWorldError(f"{d.world_type}: its tool shape names unknown tools")
    missing = set(plugin.approved_scenarios()) - set(plugin.scenario_ids())
    if missing:
        raise UnsupportedWorldError(f"{d.world_type}: approves unknown scenario {sorted(missing)}")


def build_registry(plugins: Iterable[WorldPlugin]) -> Mapping[str, WorldPlugin]:
    """Validate every plugin. A world may not share an id, a scenario or a tool with another."""
    registry: dict[str, WorldPlugin] = {}
    scenarios: set[str] = set()
    tools: set[str] = set()
    for plugin in plugins:
        validate_plugin(plugin)
        d = plugin.descriptor
        if d.world_type in registry:
            raise UnsupportedWorldError(f"world {d.world_type} is registered twice")
        if scenarios & set(plugin.scenario_ids()):
            raise UnsupportedWorldError(f"{d.world_type}: scenario id already belongs to a world")
        if tools & set(d.tools):
            raise UnsupportedWorldError(f"{d.world_type}: tool name already belongs to a world")
        scenarios |= set(plugin.scenario_ids())
        tools |= set(d.tools)
        registry[d.world_type] = plugin
    return MappingProxyType(registry)


REGISTRY: Mapping[str, WorldPlugin] = build_registry((CrmPlugin(), JobQueuePlugin()))


def world_types() -> tuple[str, ...]:
    return tuple(REGISTRY)


def world_plugin(world_type: str, *, version: str | None = None) -> WorldPlugin:
    """The registered world. ``version`` must share the running plugin's major version."""
    plugin = REGISTRY.get(world_type)
    if plugin is None:
        raise UnknownWorldError(f"unknown world {world_type!r}; known: {', '.join(REGISTRY)}")
    if version is not None:
        running = plugin.descriptor.plugin_version
        if version.split(".")[0] != running.split(".")[0]:
            raise UnsupportedWorldError(f"{world_type} {version} is not compatible with {running}")
    return plugin


def plugin_for(scenario: ScenarioBase) -> WorldPlugin:
    for plugin in REGISTRY.values():
        if plugin.handles(scenario):
            return plugin
    raise UnknownWorldError(f"no world handles {type(scenario).__name__}")


def plugin_for_scenario(scenario_id: str) -> WorldPlugin:
    for plugin in REGISTRY.values():
        if scenario_id in plugin.scenario_ids():
            return plugin
    raise UnknownWorldError(f"no world has scenario {scenario_id!r}")


def load_any_scenario(scenario_id: str) -> ScenarioBase:
    return plugin_for_scenario(scenario_id).load_scenario(scenario_id)


def config_sha256(plugin: WorldPlugin) -> str:
    """Of the world as a whole: its descriptor and tool schemas, not any one scenario."""
    body = {
        "descriptor": plugin.descriptor.model_dump(mode="json"),
        "tools": [t.spec.model_dump(mode="json") for t in plugin.tools()],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def provenance(scenario: ScenarioBase, selected_tools: list[str]) -> WorldProvenance:
    plugin = plugin_for(scenario)
    d = plugin.descriptor
    return WorldProvenance(
        world_type=d.world_type,
        plugin_version=d.plugin_version,
        contract_version=d.contract_version,
        config_sha256=config_sha256(plugin),
        scenario_id=scenario.scenario_id,
        selected_tools=selected_tools,
        invariant_ids=[i.invariant_id for i in d.invariants],
    )
