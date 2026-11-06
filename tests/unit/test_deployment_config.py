"""The properties a hosted deployment rests on, read from the files that are actually deployed.

These cannot show a host is configured correctly: only hosted checks can. They stop a later edit
from quietly exposing the backend, adding a second worker or defaulting spending on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra" / "vultr"


def text(*parts: str) -> str:
    return INFRA.joinpath(*parts).read_text(encoding="utf-8")


def env_file(*parts: str) -> dict[str, str]:
    lines = [ln for ln in text(*parts).splitlines() if ln and not ln.startswith("#")]
    return dict(ln.split("=", 1) for ln in lines)


def test_the_backend_binds_loopback_as_one_process() -> None:
    unit = text("systemd", "moody-backend.service")
    start = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    assert "--host 127.0.0.1" in start
    assert "--workers 1" in start
    assert "--no-proxy-headers" in start
    assert "0.0.0.0" not in unit  # noqa: S104 - asserting its absence


def test_the_web_tier_binds_loopback_and_has_no_docker_or_secret() -> None:
    unit = text("systemd", "moody-web.service")
    assert "--hostname 127.0.0.1" in unit
    assert "docker" not in unit.lower().replace("no docker access", "")
    assert "backend.env" not in unit
    template = env_file("config", "web.env.example")
    assert set(template) == {"NODE_ENV", "MOODY_BACKEND_URL", "MOODY_PUBLIC_ORIGIN"}


def test_a_stop_gives_a_running_job_time_to_close() -> None:
    unit = text("systemd", "moody-backend.service")
    stop = re.search(r"TimeoutStopSec=(\d+)", unit)
    graceful = re.search(r"--timeout-graceful-shutdown (\d+)", unit)
    assert stop
    assert graceful
    assert int(graceful.group(1)) > 20  # a cancellation can take 20 s
    assert int(stop.group(1)) > int(graceful.group(1))
    assert "Restart=on-failure" in unit


def test_caddy_proxies_only_to_next_and_trusts_no_forwarded_headers() -> None:
    caddyfile = text("config", "Caddyfile")
    assert re.findall(r"reverse_proxy\s+(\S+)", caddyfile) == ["127.0.0.1:3000"]
    assert ":8000" not in caddyfile
    assert not re.search(r"^\s*trusted_proxies\s", caddyfile, re.MULTILINE)
    assert "flush_interval -1" in caddyfile  # job progress is server-sent events


def test_the_hosted_template_refuses_spending_by_default() -> None:
    env = env_file("config", "backend.env.example")
    assert env["MOODY_ENVIRONMENT"] == "production"
    assert env["MOODY_LIVE_RUNS_ENABLED"] == "false"
    assert env["MOODY_VULTR_API_KEY"] == ""
    assert env["MOODY_OPERATOR_TOKEN"] == ""
    assert float(env["MOODY_LIVE_SPEND_LIMIT_USD"]) < float(env["MOODY_LIVE_LEDGER_FLOOR_USD"])


def test_hosted_state_and_images_are_pinned_outside_the_release() -> None:
    env = env_file("config", "backend.env.example")
    assert env["MOODY_ARTIFACTS_DIR"].startswith("/var/lib/moody-blues")
    assert env["MOODY_CONTAINMENT_REPORT"].startswith("/var/lib/moody-blues")
    assert "@sha256:" in env["MOODY_SANDBOX_IMAGE"]
    assert env["MOODY_VULTR_MODEL"] == "glm-5.3"  # the code default is not in the catalog


def test_the_image_pin_is_the_same_everywhere() -> None:
    from moody_blues.config import Settings

    pin = Settings(_env_file=None).generated_code_image  # pyright: ignore[reportCallIssue]
    assert env_file("config", "backend.env.example")["MOODY_SANDBOX_IMAGE"] == pin
    assert f'IMAGE="{pin}"' in text("bootstrap.sh")


def test_the_firewall_opens_only_ssh_and_web() -> None:
    script = text("provision.sh")
    assert sorted(set(re.findall(r'\\"port\\":\\"(\d+|\$port)\\"', script))) == ["$port", "22"]
    assert "for port in 80 443" in script
    opened = re.findall(r"^ufw allow (.+)$", text("bootstrap.sh"), re.MULTILINE)
    assert opened == [
        'from "$ADMIN_CIDR" to any port 22 proto tcp',
        "80/tcp",
        "443/tcp",
    ]


def test_provisioning_refuses_without_a_matching_confirmation() -> None:
    script = text("provision.sh")
    assert '"$confirm" == "$MB_PLAN@$MB_REGION"' in script
    assert '"$2" == "$id"' in script  # destroy names the exact instance
    assert '\\"backups\\":\\"disabled\\"' in script


def test_the_reviewed_plan_has_real_disk() -> None:
    assert "MB_PLAN=vx1-g-2c-8g\n" not in text("plan.env")  # 1 GB disk at this price


def test_docker_publishes_no_port_and_sets_no_insecure_default() -> None:
    daemon = json.loads(text("config", "docker-daemon.json"))
    assert daemon["no-new-privileges"] is True
    assert daemon["icc"] is False
    assert "hosts" not in daemon  # the socket stays local
    assert "docker run" not in text("bootstrap.sh")


def test_nothing_deployed_can_contain_a_secret_or_local_state() -> None:
    assert "git archive" in text("deploy.sh")  # tracked files only
    assert "rsync" not in text("deploy.sh")
    assert "git status --porcelain" in text("deploy.sh")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert ".artifacts/" in gitignore


def test_the_migration_refuses_to_replace_a_different_ledger() -> None:
    script = text("migrate-ledger.sh")
    assert "refusing to overwrite" in script
    assert "open_reservations" in script


def test_a_release_always_asks_and_ships_only_a_pushed_commit() -> None:
    release = text("release.sh")
    assert "read -r -p" in release  # a person confirms each deployment
    assert "git branch -r --contains" in release  # what ships is on GitHub
    assert "git worktree add --quiet --detach" in release  # the commit, not the current checkout
    assert "infra/vultr/deploy.sh" in release  # one way onto the VM
