"""The contract: both sides agree, what ships is what was declared, nothing is repaired."""

from __future__ import annotations

import ast
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest
from pydantic import ValidationError

from moody_blues.contracts.adapter import (
    ADAPTER_PROTOCOL,
    MAX_AGENT_MESSAGE_BYTES,
    AdapterRejection,
    AdapterRejectionCode,
    ExecutionContext,
    FinalMessage,
    HelloMessage,
    TaskSpec,
    ToolDefinition,
    ToolResultMessage,
    WelcomeMessage,
)
from moody_blues.contracts.agent import AgentRunReport
from moody_blues.contracts.experiment_evidence import ExperimentEvidence, TargetRunEvidence
from moody_blues.contracts.world import ToolResponse
from moody_blues.external.bundle import ManifestError, build_bundle
from moody_blues.external.protocol import parse_line
from moody_blues.world.scenarios import load_scenario
from moody_blues_sdk import AgentAdapter, AgentResult, protocol
from moody_blues_sdk.client import Exchange
from moody_blues_sdk.runtime import _context, _hello  # pyright: ignore[reportPrivateUsage]
from tests.external.conftest import EXAMPLES, REPO, fixture_manifest

SDK = REPO / "sdk" / "python" / "moody_blues_sdk"


def _imports(root: Path) -> set[str]:
    found: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_sdk_needs_nothing_but_the_standard_library() -> None:
    assert _imports(SDK) - sys.stdlib_module_names == {"moody_blues_sdk"}


def test_example_imports_the_sdk_and_nothing_of_moody_blues() -> None:
    outside = _imports(EXAMPLES / "acme_crm_agent") - sys.stdlib_module_names
    assert outside == {"moody_blues_sdk"}


class _Sample(AgentAdapter):
    agent_id = "sample-agent"
    name = "Sample"


def test_sdk_constants_match_the_contract() -> None:
    assert protocol.PROTOCOL_VERSION == ADAPTER_PROTOCOL
    assert protocol.MAX_MESSAGE_BYTES == MAX_AGENT_MESSAGE_BYTES


def _on_wire(message: dict[str, Any]) -> bytes:
    return json.dumps({"protocol": protocol.PROTOCOL_VERSION, **message}).encode()


def test_sdk_hello_is_a_valid_hello() -> None:
    assert isinstance(parse_line(_on_wire(_hello(_Sample()))), HelloMessage)


@pytest.mark.parametrize(
    "result",
    [
        AgentResult.completed(customer_id="cus_x", message="done", evidence=("call_0001",)),
        AgentResult.not_completed(message="no"),
        AgentResult.failed("agent_error", message="boom"),
        AgentResult("cancelled", error_class="cancelled"),
    ],
)
def test_sdk_final_is_a_valid_final(result: AgentResult) -> None:
    assert isinstance(parse_line(_on_wire(result.to_message())), FinalMessage)


def test_sdk_reads_what_the_host_sends() -> None:
    objective = load_scenario("normal-success").objective
    context = ExecutionContext(
        run_id="run_1",
        correlation_id="cor_1",
        scenario_ref="wrld_1",
        task=TaskSpec(mission="Mission: do it", objective=objective),
        tools=[ToolDefinition(name="t", description="d", parameters={}, access="read")],
        scopes=["crm:read"],
        deadline_seconds=10.0,
        max_tool_calls=3,
        capabilities=["tools"],
    )
    wire = json.loads(WelcomeMessage(context=context).model_dump_json())
    cancel = Event()
    read = _context(wire["context"], cast(Exchange, None), cancel)
    assert read.task.customer.email == objective.customer.email
    assert read.model is None
    assert read.tools[0].access == "read"


def test_tool_result_carries_the_gateway_response_unchanged() -> None:
    response = ToolResponse(call_id="call_0001", tool="get_customer", ok=True, data={"a": 1})
    message = ToolResultMessage(
        call_id="tool-1",
        evidence_ref="call_0001",
        response=response,
        rejection=None,
        calls_remaining=3,
    )
    assert json.loads(message.model_dump_json())["response"] == response.model_dump(mode="json")


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b"\xff\xfe", AdapterRejectionCode.INVALID_ENCODING),
        (b"not json", AdapterRejectionCode.MALFORMED_JSON),
        (b"[1]", AdapterRejectionCode.MALFORMED_JSON),
        (b'{"protocol":"mb-agent/1","type":"final","x":NaN}', AdapterRejectionCode.MALFORMED_JSON),
        (b'{"type":"final","type":"hello"}', AdapterRejectionCode.MALFORMED_JSON),
        (b'{"type":"final"}', AdapterRejectionCode.UNSUPPORTED_PROTOCOL),
        (b'{"protocol":"mb-exp/1","type":"final"}', AdapterRejectionCode.UNSUPPORTED_PROTOCOL),
        (b'{"protocol":"mb-agent/1","type":"sql"}', AdapterRejectionCode.UNKNOWN_MESSAGE),
        (b'{"protocol":"mb-agent/1","type":"tool_result"}', AdapterRejectionCode.UNKNOWN_MESSAGE),
        (b'{"protocol":"mb-agent/1","type":["final"]}', AdapterRejectionCode.UNKNOWN_MESSAGE),
        (b'{"protocol":"mb-agent/1","type":"final"}', AdapterRejectionCode.SCHEMA_VIOLATION),
        (
            b'{"protocol":"mb-agent/1","type":"final","completion":"finished","verdict":"PASS"}',
            AdapterRejectionCode.SCHEMA_VIOLATION,
        ),
        (
            b'{"protocol":"mb-agent/1","type":"tool_call","call_id":"a b","tool":"t",'
            b'"arguments":{}}',
            AdapterRejectionCode.SCHEMA_VIOLATION,
        ),
    ],
)
def test_bad_lines_are_rejected_and_never_repaired(line: bytes, code: AdapterRejectionCode) -> None:
    parsed = parse_line(line)
    assert isinstance(parsed, AdapterRejection)
    assert parsed.code is code


def test_a_rejection_does_not_echo_what_the_agent_sent() -> None:
    secret = "SENSITIVE-VALUE"
    line = json.dumps(
        {"protocol": ADAPTER_PROTOCOL, "type": "final", "completion": secret, "extra": secret}
    ).encode()
    parsed = parse_line(line)
    assert isinstance(parsed, AdapterRejection)
    assert secret not in parsed.detail


def test_bundle_is_deterministic_and_changes_with_the_code(tmp_path: Path) -> None:
    first = build_bundle(EXAMPLES / "careful.agent.toml")
    assert first.sha256 == build_bundle(EXAMPLES / "careful.agent.toml").sha256
    package = tmp_path / "acme"
    package.mkdir()
    (package / "__init__.py").write_text("X = 1\n")
    manifest = tmp_path / "m.agent.toml"
    manifest.write_text(
        (EXAMPLES / "careful.agent.toml")
        .read_text()
        .replace('"acme_crm_agent"', '"acme"')
        .replace("acme_crm_agent.policies", "acme")
    )
    before = build_bundle(manifest).sha256
    (package / "__init__.py").write_text("X = 2\n")
    assert build_bundle(manifest).sha256 != before


def _manifest(tmp_path: Path, **changes: str) -> Path:
    text = (EXAMPLES / "careful.agent.toml").read_text()
    for old, new in changes.items():
        text = text.replace(old.replace("__", " = "), new)
    path = tmp_path / "x.agent.toml"
    path.write_text(text)
    (tmp_path / "acme_crm_agent").mkdir(exist_ok=True)
    return path


@pytest.mark.parametrize(
    "broken",
    [
        'protocol = "mb-agent/1"\n= broken',
        'protocol = "mb-agent/2"',
        'protocol = "mb-agent/1"\nsecret_key = "x"',
    ],
)
def test_bad_manifests_are_refused(tmp_path: Path, broken: str) -> None:
    path = _manifest(tmp_path)
    path.write_text(path.read_text().replace('protocol = "mb-agent/1"', broken))
    with pytest.raises(ManifestError):
        build_bundle(path)


def test_entrypoint_must_be_in_the_package(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    path.write_text(path.read_text().replace("acme_crm_agent.policies", "os.path"))
    with pytest.raises(ManifestError, match="entrypoint"):
        build_bundle(path)


def test_a_package_cannot_replace_the_sdk(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    path.write_text(path.read_text().replace("acme_crm_agent", "moody_blues_sdk"))
    with pytest.raises(ManifestError, match="supplied by MOODY BLUES"):
        build_bundle(path)


def test_symlinks_inside_a_package_are_refused(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    (tmp_path / "acme_crm_agent" / "secrets.py").symlink_to("/etc/hosts")
    with pytest.raises(ManifestError, match="symbolic"):
        build_bundle(path)


def test_oversized_bundles_are_refused(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    (tmp_path / "acme_crm_agent" / "big.txt").write_bytes(os.urandom(4_100_000))
    with pytest.raises(ManifestError, match="limit"):
        build_bundle(path)


def test_only_source_files_are_shipped(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    package = tmp_path / "acme_crm_agent"
    (package / "__init__.py").write_text("")
    (package / ".env").write_text("KEY=secret")
    (package / "key.pem").write_text("secret")
    (package / "data.sqlite").write_text("secret")
    names = zipfile.ZipFile(io.BytesIO(build_bundle(path).archive)).namelist()
    assert "acme_crm_agent/__init__.py" in names
    assert not [n for n in names if n.endswith((".env", ".pem", ".sqlite"))]


def test_fixture_manifest_builds(tmp_path: Path) -> None:
    assert build_bundle(fixture_manifest(tmp_path, "Succeeds")).manifest.agent_id == "fixture-agent"


# --- evidence versions ------------------------------------------------------------------------


def _bundles() -> list[Path]:
    return sorted((REPO / "evidence" / "recorded").glob("inv_*.json"))


def test_recorded_bundles_still_validate_and_carry_no_external_field() -> None:
    from moody_blues.contracts.explorer import InvestigationBundle

    assert _bundles()
    for path in _bundles():
        bundle = InvestigationBundle.model_validate_json(path.read_text("utf-8"))
        assert all(r.external is None for r in bundle.runs)
        assert all('"external"' not in json.dumps(r.model_dump(mode="json")) for r in bundle.runs)


def test_an_external_run_cannot_lack_provenance_or_be_filed_as_version_1() -> None:
    fields = TargetRunEvidence.model_fields
    assert "external" in fields
    assert ExperimentEvidence.model_fields["schema_version"].default == 1
    assert AgentRunReport.model_fields["external"].default is None
    with pytest.raises(ValidationError):
        TargetRunEvidence.model_validate({"target_kind": "external_agent"})
