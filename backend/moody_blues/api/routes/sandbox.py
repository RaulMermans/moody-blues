from __future__ import annotations

from fastapi import APIRouter

from moody_blues.api.deps import SandboxDep
from moody_blues.contracts.sandbox import SandboxRequest, SandboxResult

router = APIRouter(prefix="/sandbox", tags=["sandbox"])

# Fixed, harmless program. The API deliberately does not accept arbitrary code in
# Sprint 1: there is no authentication layer yet.
SMOKE_PROGRAM = """\
import os, platform, sys
print(f"hello from sandbox: python {platform.python_version()} uid={os.getuid()}")
print("stderr channel ok", file=sys.stderr)
"""


@router.post("/smoke", response_model=SandboxResult)
def run_sandbox_smoke(sandbox: SandboxDep) -> SandboxResult:
    """Execute the fixed smoke program in a disposable container."""
    return sandbox.run(SandboxRequest(code=SMOKE_PROGRAM))
