"""Developer CLI: ``uv run moody-blues <command>``.

Commands:
  doctor        Check local prerequisites and configuration (no chargeable calls).
  docker-smoke  Run the fixed smoke program in a real disposable container.
  vultr-smoke   LIVE: basic inference + tool calling against Vultr (chargeable).
  vultr-models  LIVE: list models visible to the configured key.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from moody_blues.config import Settings
from moody_blues.contracts.sandbox import SandboxRequest
from moody_blues.inference import smoke as vultr_smoke
from moody_blues.sandbox.base import SandboxError
from moody_blues.sandbox.docker_runner import DockerSandboxRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO_ROOT / ".artifacts"

OK, WARN, FAIL = "PASS", "WARN", "FAIL"


def _version(cmd: Sequence[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0] if out.returncode == 0 and text else None


def doctor(settings: Settings) -> int:
    rows: list[tuple[str, str, str]] = []

    def check(name: str, status: str, detail: str) -> None:
        rows.append((status, name, detail))

    py = sys.version_info
    check(
        "python",
        OK if py >= (3, 12) else FAIL,
        f"{platform.python_version()} (>=3.12 required)",
    )
    for tool, args, required in [
        ("uv", ["uv", "--version"], True),
        ("node", ["node", "--version"], True),
        ("pnpm", ["pnpm", "--version"], True),
        ("docker-cli", ["docker", "--version"], True),
        ("git", ["git", "--version"], False),
    ]:
        v = _version(args)
        check(tool, OK if v else (FAIL if required else WARN), v or "not found on PATH")

    node_v = _version(["node", "--version"])
    if node_v and int(node_v.lstrip("v").split(".")[0]) < 20:
        check("node-version", FAIL, f"{node_v} (>=20 required by Next.js)")

    runner = DockerSandboxRunner.from_settings(settings)
    try:
        runner.ping()
        check(
            "docker-daemon",
            OK,
            f"reachable at {runner.docker_host} (via {runner.docker_host_source})",
        )
        try:
            runner._docker().images.get(settings.sandbox_image)  # pyright: ignore[reportPrivateUsage]
            check("sandbox-image", OK, f"{settings.sandbox_image} present")
        except Exception:  # noqa: BLE001 - diagnostic only, reported as WARN
            check("sandbox-image", WARN, f"{settings.sandbox_image} not pulled (auto-pulled)")
        leftovers = runner.list_sandbox_containers()
        check(
            "sandbox-cleanup",
            OK if not leftovers else WARN,
            f"{len(leftovers)} leftover sandbox containers",
        )
    except SandboxError as exc:
        check("docker-daemon", FAIL, exc.detail.message)

    fe = REPO_ROOT / "frontend"
    check(
        "frontend-deps",
        OK if (fe / "node_modules").is_dir() else WARN,
        "installed" if (fe / "node_modules").is_dir() else "run `make setup`",
    )
    pw = _version(["pnpm", "--dir", str(fe), "exec", "playwright", "--version"])
    check("playwright", OK if pw else WARN, pw or "not installed (`make setup`)")

    env_file = REPO_ROOT / ".env"
    check(
        "env-file",
        OK if env_file.exists() else WARN,
        ".env present" if env_file.exists() else "no .env (defaults used; see .env.example)",
    )
    if settings.vultr_configured:
        check(
            "vultr-config",
            OK,
            f"key set, model={settings.vultr_model}, base={settings.vultr_base_url} "
            "-- NOT live-verified; run `make vultr-smoke`",
        )
    else:
        check("vultr-config", WARN, "BLOCKED_BY_CREDENTIALS: MOODY_VULTR_API_KEY not set")

    width = max(len(n) for _, n, _ in rows)
    for status, name, detail in rows:
        print(f"[{status:<4}] {name:<{width}}  {detail}")
    failed = [n for s, n, _ in rows if s == FAIL]
    print(f"\n{'FAILED: ' + ', '.join(failed) if failed else 'All required checks passed.'}")
    return 1 if failed else 0


def docker_smoke(settings: Settings) -> int:
    from moody_blues.api.routes.sandbox import SMOKE_PROGRAM

    runner = DockerSandboxRunner.from_settings(settings)
    try:
        result = runner.run(SandboxRequest(code=SMOKE_PROGRAM))
    except SandboxError as exc:
        print(json.dumps({"status": "BLOCKED_BY_LOCAL_DEPENDENCY", "error": exc.detail.message}))
        return 2
    print(result.model_dump_json(indent=2))
    return 0 if result.exit_code == 0 and result.cleaned_up else 1


def _vultr(settings: Settings, checks: list[str], artifact: str) -> int:
    code, report = vultr_smoke.run(checks, settings)
    text = vultr_smoke.render(report)
    print(text)
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / artifact).write_text(text + "\n")
    return code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="moody-blues")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("docker-smoke")
    vs = sub.add_parser("vultr-smoke")
    vs.add_argument(
        "--check",
        action="append",
        choices=sorted(vultr_smoke.CHECKS),
        help="run only this check (repeatable); default: all",
    )
    sub.add_parser("vultr-models")
    args = parser.parse_args(argv)

    settings = Settings()
    match args.command:
        case "doctor":
            return doctor(settings)
        case "docker-smoke":
            return docker_smoke(settings)
        case "vultr-smoke":
            return _vultr(settings, args.check or list(vultr_smoke.CHECKS), "vultr-smoke.json")
        case "vultr-models":
            return _vultr(settings, ["list_models"], "vultr-models.json")
        case _:
            parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
