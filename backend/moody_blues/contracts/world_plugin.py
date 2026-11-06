"""The world plugin contract, version ``mb-world/1``: what identifies a world and its evidence.

A world is a trusted backend component. These types describe it; nothing here loads one. Worlds are
listed by hand in ``world/registry.py``. There is no path from a request, an agent or an experiment
to that list.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from moody_blues.contracts.scenario import FaultKind

WORLD_CONTRACT_VERSION = "mb-world/1"
SUPPORTED_WORLD_CONTRACTS: frozenset[str] = frozenset({WORLD_CONTRACT_VERSION})

WORLD_TYPE_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"


class InvariantDefinition(BaseModel):
    """One thing a world's verifier can find broken."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invariant_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    # ``task``: what this objective requires. ``world``: true of this world, whatever was asked.
    scope: Literal["task", "world"]
    description: str = Field(min_length=1, max_length=300)


class ToolShape(BaseModel):
    """Where a world's responses keep things, so shared code can read a trace without knowing it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    write_tool: str
    read_tools: tuple[str, ...]
    key_argument: str  # the idempotency key on the write
    item_key: str  # ``{"customer": {...}}``
    list_key: str  # ``{"customers": [...]}``
    id_key: str  # the id inside an item
    claim_field: str  # where a final report names the record


class WorldDescriptor(BaseModel):
    """Identity, and everything else about a world that is the same for all of its runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    world_type: str = Field(pattern=WORLD_TYPE_PATTERN)
    name: str = Field(min_length=1, max_length=80)
    plugin_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    contract_version: str
    capabilities: tuple[str, ...]
    tools: tuple[str, ...] = Field(min_length=1)
    fault_kinds: tuple[FaultKind, ...]
    fault_operations: tuple[str, ...]
    invariants: tuple[InvariantDefinition, ...] = Field(min_length=1)
    shape: ToolShape
    record_noun: str = Field(min_length=1, max_length=40)  # customer, job
    store_noun: str = Field(min_length=1, max_length=40)  # CRM, job queue


class WorldProvenance(BaseModel):
    """Which world produced a run, recorded with the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    world_type: str
    plugin_version: str
    contract_version: str
    config_sha256: str  # of the descriptor and the tool schemas, not of any one scenario
    scenario_id: str
    selected_tools: list[str]
    invariant_ids: list[str]


# Evidence written before Sprint 18 has no provenance. Every such record is schema 1 or 2, and those
# versions only ever held the CRM, so this mapping is exact, not a guess. It is applied when reading
# and never written back: the record stays as it was hashed.
LEGACY_WORLD_TYPE = "crm"
LEGACY_PLUGIN_VERSION = "legacy"
