"""Which target an investigation runs against, and what that selection may unlock.

A selection comes from an operator's command line, never from a request, a page or an agent. It is
checked here against the registered manifest before anything is built, because the choice is what
grants a model: an agent that declares itself scripted is never lent one, and an agent that asks for
one is never run as if it had not. The run's own record still decides what actually happened.
"""

from __future__ import annotations

from moody_blues.contracts.adapter import ADAPTER_PROTOCOL, Capability, TargetType
from moody_blues.contracts.investigation import TargetKind, TargetProvenance
from moody_blues.external.bundle import AgentBundle
from moody_blues.external.driver import InferenceBroker


class TargetSelectionError(ValueError):
    """This target may not be run this way. Says why, and nothing is built."""


def check_model_allowed(model: str, allowlist: tuple[str, ...]) -> None:
    if model not in allowlist:
        raise TargetSelectionError(f"model {model} is not on the host's allowlist")


def external_provenance(
    kind: TargetKind, bundle: AgentBundle, broker: InferenceBroker | None
) -> TargetProvenance:
    """Refuses a selection the registration does not support. Returns what to record."""
    manifest = bundle.manifest
    declares_model = Capability.MODEL in manifest.capabilities
    match kind:
        case TargetKind.INTERNAL_LLM:
            raise TargetSelectionError("an internal target has no bundle")
        case TargetKind.EXTERNAL_SCRIPTED:
            if manifest.target_type is not TargetType.SCRIPTED or declares_model:
                raise TargetSelectionError(f"{manifest.agent_id} is not registered as a script")
            if broker is not None:
                raise TargetSelectionError("a script is never lent a model")
        case TargetKind.EXTERNAL_LLM:
            if manifest.target_type is not TargetType.LLM or not declares_model:
                raise TargetSelectionError(f"{manifest.agent_id} is not registered as an LLM agent")
            if broker is None:
                raise TargetSelectionError("an LLM target needs a broker, fixture or live")
    return TargetProvenance(
        kind=kind,
        agent_id=manifest.agent_id,
        agent_version=manifest.version,
        protocol=ADAPTER_PROTOCOL,
        bundle_sha256=bundle.sha256,
        manifest_sha256=bundle.manifest_sha256,
        model_broker=broker.evidence if broker is not None else "none",
        approved_model=broker.model if broker is not None else None,
        model_identity=broker.identity if broker is not None else None,
    )
