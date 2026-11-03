from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from moody_blues.contracts.common import ExecutionStatus
from moody_blues.contracts.experiment import ExperimentRecord, ExperimentRequest
from moody_blues.contracts.inference import InferenceRequest, ToolSpec
from moody_blues.contracts.sandbox import MAX_CODE_BYTES, SandboxRequest, SandboxResult
from tests.conftest import limits


def _result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "sbx_1",
        "status": ExecutionStatus.SUCCEEDED,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "duration_ms": 5,
        "image": "python:3.12-slim",
        "limits": limits(),
        "cleaned_up": True,
    }
    return base | overrides


def test_sandbox_result_valid() -> None:
    r = SandboxResult.model_validate(_result())
    assert SandboxResult.model_validate_json(r.model_dump_json()) == r


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": ExecutionStatus.SUCCEEDED, "exit_code": 1},
        {"status": ExecutionStatus.TIMED_OUT, "timed_out": False, "exit_code": 137},
        {"status": ExecutionStatus.FAILED, "timed_out": True, "exit_code": 137},
        {"status": ExecutionStatus.PENDING, "exit_code": None},
        {"duration_ms": -1},
    ],
)
def test_sandbox_result_rejects_inconsistent(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SandboxResult.model_validate(_result(**overrides))


def test_sandbox_request_limits() -> None:
    with pytest.raises(ValidationError):
        SandboxRequest(code="")
    with pytest.raises(ValidationError):
        SandboxRequest(code="x" * (MAX_CODE_BYTES + 1))
    with pytest.raises(ValidationError):
        limits(wall_timeout_seconds=0)
    assert limits().network_enabled is False


def test_tool_spec_name_validated() -> None:
    with pytest.raises(ValidationError):
        ToolSpec(name="bad name!", description="x", parameters={})


def test_inference_request_requires_messages() -> None:
    with pytest.raises(ValidationError):
        InferenceRequest(messages=[])


def test_experiment_request() -> None:
    req = ExperimentRequest.model_validate(
        {"target": {"name": "crm-agent", "objective": "update a contact", "tools": ["crm.update"]}}
    )
    rec = ExperimentRecord(request=req)
    assert rec.status is ExecutionStatus.PENDING
    assert rec.experiment_id.startswith("exp_")
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate({"target": {"name": "", "objective": "x"}})
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate(
            {"target": {"name": "a", "objective": "b"}, "max_iterations": 0}
        )
