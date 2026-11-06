"""The plugin contract: an explicit registry, validated identity, nothing loaded dynamically."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from moody_blues.contracts.job_queue import JobScenario
from moody_blues.contracts.scenario import Scenario
from moody_blues.contracts.world_plugin import WORLD_CONTRACT_VERSION, WorldDescriptor
from moody_blues.world import registry as registry_module
from moody_blues.world.crm_plugin import DESCRIPTOR as CRM
from moody_blues.world.crm_plugin import CrmPlugin
from moody_blues.world.jobqueue.plugin import JobQueuePlugin
from moody_blues.world.registry import (
    REGISTRY,
    UnknownWorldError,
    UnsupportedWorldError,
    build_registry,
    config_sha256,
    load_any_scenario,
    plugin_for,
    plugin_for_scenario,
    validate_plugin,
    world_plugin,
    world_types,
)

GOLDEN = Path(__file__).parent / "golden" / "crm_e44393a.json"


@dataclass
class _Patched:
    """A real plugin under a different descriptor. A test double: never registered."""

    inner: Any
    descriptor: WorldDescriptor

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def test_crm_and_job_queue_are_registered_and_valid() -> None:
    assert world_types() == ("crm", "job-queue")
    for name in world_types():
        plugin = world_plugin(name)
        validate_plugin(plugin)
        assert plugin.descriptor.contract_version == WORLD_CONTRACT_VERSION


def test_an_unknown_world_is_refused() -> None:
    with pytest.raises(UnknownWorldError, match="unknown world"):
        world_plugin("kubernetes")


def test_an_unsupported_contract_version_is_refused() -> None:
    bad = _Patched(CrmPlugin(), CRM.model_copy(update={"contract_version": "mb-world/99"}))
    with pytest.raises(UnsupportedWorldError, match="not supported"):
        validate_plugin(bad)  # pyright: ignore[reportArgumentType]


def test_an_incompatible_plugin_version_is_refused() -> None:
    assert world_plugin("crm", version="1.4.0").descriptor.world_type == "crm"
    with pytest.raises(UnsupportedWorldError, match="not compatible"):
        world_plugin("crm", version="2.0.0")


def test_a_descriptor_cannot_claim_tools_the_world_does_not_have() -> None:
    bad = _Patched(CrmPlugin(), CRM.model_copy(update={"tools": ("create_customer",)}))
    with pytest.raises(UnsupportedWorldError, match="differ"):
        validate_plugin(bad)  # pyright: ignore[reportArgumentType]


def test_worlds_cannot_share_an_id_a_scenario_or_a_tool() -> None:
    with pytest.raises(UnsupportedWorldError, match="registered twice"):
        build_registry((CrmPlugin(), CrmPlugin()))
    twin = _Patched(CrmPlugin(), CRM.model_copy(update={"world_type": "crm-two"}))
    with pytest.raises(UnsupportedWorldError):
        build_registry((CrmPlugin(), twin))  # pyright: ignore[reportArgumentType]


def test_the_registry_cannot_be_changed_at_runtime() -> None:
    with pytest.raises(TypeError):
        REGISTRY["agent-world"] = CrmPlugin()  # type: ignore[index]


def test_no_dynamic_import_reaches_a_world() -> None:
    """World selection is a dictionary lookup. There is no path from text to a module."""
    root = Path(registry_module.__file__).parent
    for path in [root / "registry.py", root / "verification.py", root / "plugin.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            a.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for a in node.names
        }
        assert "importlib" not in names
        assert not any(
            isinstance(n, ast.Call) and getattr(n.func, "id", "") in {"__import__", "eval", "exec"}
            for n in ast.walk(tree)
        )


def test_scenarios_resolve_to_their_own_world() -> None:
    assert isinstance(load_any_scenario("phantom-failure"), Scenario)
    assert isinstance(load_any_scenario("jq-phantom-failure"), JobScenario)
    assert plugin_for_scenario("jq-normal").descriptor.world_type == "job-queue"
    assert plugin_for(load_any_scenario("normal-success")).descriptor.world_type == "crm"
    with pytest.raises(UnknownWorldError):
        plugin_for_scenario("no-such-world")


def test_the_config_hash_is_stable_and_per_world() -> None:
    crm, jobs = config_sha256(CrmPlugin()), config_sha256(JobQueuePlugin())
    assert crm == config_sha256(CrmPlugin())
    assert crm != jobs


def test_the_crm_world_is_byte_for_byte_what_it_was_at_e44393a() -> None:
    """Compatibility as a measurement. The file was written by the code before the refactor."""
    import hashlib

    from moody_blues.agents.policies import POLICIES
    from moody_blues.agents.tooling import agent_tool_specs
    from moody_blues.experiments.workspace import sha256_text
    from moody_blues.investigator.catalog import target_capability
    from moody_blues.investigator.context import PROTOCOL, SYSTEM_PROMPT, system_prompt
    from moody_blues.services.world_runner import run_reference_case
    from moody_blues.world.reference import REFERENCE_CASES
    from moody_blues.world.scenarios import load_scenario, scenario_ids

    def sha(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert {c.case_id: run_reference_case(c).fingerprint for c in REFERENCE_CASES} == golden[
        "reference_fingerprints"
    ]
    assert {i: sha256_text(load_scenario(i).model_dump_json()) for i in scenario_ids()} == golden[
        "scenario_sha256"
    ]
    specs = [s.model_dump(mode="json") for s in agent_tool_specs()]
    assert sha(json.dumps(specs, sort_keys=True)) == golden["agent_tool_specs_sha256"]
    assert {k.value: v.sha256 for k, v in POLICIES.items()} == golden["policy_sha256"]
    assert sha(SYSTEM_PROMPT) == golden["investigator_system_prompt_sha256"]
    assert (
        sha(system_prompt("a synthetic CRM world")) == golden["investigator_system_prompt_sha256"]
    )
    assert sha(PROTOCOL) == golden["investigator_protocol_sha256"]
    capability = target_capability(("normal-success", "phantom-failure"))
    assert sha(capability.model_dump_json()) == golden["target_capability_sha256"]
