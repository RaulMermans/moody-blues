#!/usr/bin/env python3
"""Rewrites backend.env for the live switch. Runs as root on the VM, sent by live-switch.sh.

    live-env.py on <limit-usd>    the inference key arrives on stdin, never as an argument
    live-env.py off               removes the key

The new file replaces the old one atomically, and no other line changes. If the backend does not come
back from `on`, the old file returns. `off` never goes back: a failed restart must not restore the key.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ENV_FILE = Path(os.environ.get("MOODY_BACKEND_ENV_FILE", "/etc/moody-blues/backend.env"))
HEALTH_URL = "http://127.0.0.1:8000/health"
HEALTH_ATTEMPTS = 30
KEY = "MOODY_VULTR_API_KEY"
OFF_LIMIT = "5"


def quoted(value: str) -> str:
    """One form that systemd's EnvironmentFile and bash's `source` both read back unchanged."""
    if re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return value
    return '"' + re.sub(r'([\\"$`])', r"\\\1", value) + '"'


def updated(text: str, changes: dict[str, str]) -> str:
    """Changes the named lines, drops their duplicates, adds any that are missing. Keeps the rest."""
    remaining = dict(changes)
    lines: list[str] = []
    for line in text.splitlines():
        name = line.split("=", 1)[0]
        if name not in changes:
            lines.append(line)
        elif name in remaining:
            lines.append(f"{name}={remaining.pop(name)}")
    lines.extend(f"{name}={value}" for name, value in remaining.items())
    return "\n".join(lines) + "\n"


def replace(path: Path, text: str) -> None:
    """Same directory, so the rename is atomic; owner and mode are set before any content exists."""
    info = path.stat()
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".backend-env-")
    try:
        os.fchown(descriptor, info.st_uid, info.st_gid)
        os.fchmod(descriptor, info.st_mode & 0o777)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def backend_serves() -> bool:
    if subprocess.run(["systemctl", "restart", "moody-backend"], check=False).returncode != 0:
        return False
    for _ in range(HEALTH_ATTEMPTS):
        probe = ["curl", "-fsS", "--max-time", "2", "-o", "/dev/null", HEALTH_URL]
        if subprocess.run(probe, check=False, stderr=subprocess.DEVNULL).returncode == 0:
            return True
        time.sleep(float(os.environ.get("MOODY_HEALTH_WAIT_SECONDS", "2")))
    return False


def read_key() -> str:
    key = sys.stdin.buffer.read().decode("utf-8").rstrip("\r\n")
    if not key or any(ord(character) < 32 or ord(character) == 127 for character in key):
        raise SystemExit("no usable key on stdin; nothing changed")
    return key


def turn_on(limit: str) -> None:
    if not re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?", limit):
        raise SystemExit("limit must be a number; nothing changed")
    key = read_key()
    before = ENV_FILE.read_text(encoding="utf-8")
    replace(
        ENV_FILE,
        updated(
            before,
            {
                KEY: quoted(key),
                "MOODY_LIVE_RUNS_ENABLED": "true",
                "MOODY_LIVE_SPEND_LIMIT_USD": limit,
            },
        ),
    )
    if not backend_serves():
        replace(ENV_FILE, before)
        backend_serves()
        raise SystemExit("the backend did not come back; the previous settings were restored")
    print(f"live runs on, ledger limit ${limit}")


def turn_off() -> None:
    text = ENV_FILE.read_text(encoding="utf-8")
    replace(
        ENV_FILE,
        updated(
            text,
            {KEY: "", "MOODY_LIVE_RUNS_ENABLED": "false", "MOODY_LIVE_SPEND_LIMIT_USD": OFF_LIMIT},
        ),
    )
    if not backend_serves():
        raise SystemExit("the key is removed and live runs are off, but the backend did not come back")
    print("live runs off, key removed")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "on" and len(sys.argv) == 3:
        turn_on(sys.argv[2])
    elif mode == "off" and len(sys.argv) == 2:
        turn_off()
    else:
        raise SystemExit("on <limit-usd> or off")


if __name__ == "__main__":
    main()
