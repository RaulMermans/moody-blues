#!/usr/bin/env bash
# Checks what must exist before anything else can run. Needs nothing but bash, so it can explain a
# missing tool that `make doctor` would itself need. Changes nothing.
#   check-prereqs.sh [--no-docker]   --no-docker: tools only, for `make setup`
set -uo pipefail

MIN_NODE_MAJOR=20
MIN_NODE_MINOR=9
PNPM_MAJOR=10
MIN_DOCKER_MEMORY_GIB=2
MIN_FREE_DISK_GIB=5

failed=0
ok() { printf '[PASS] %-14s %s\n' "$1" "$2"; }
warn() { printf '[WARN] %-14s %s\n' "$1" "$2"; }
bad() { printf '[FAIL] %-14s %s\n' "$1" "$2"; failed=1; }

case "$(uname -s)" in
  Darwin) ok platform "macOS $(sw_vers -productVersion 2>/dev/null) on $(uname -m)" ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      warn platform "WSL2 has not been tested; see docs/supported-platforms.md"
    else
      ok platform "Linux on $(uname -m)"
    fi
    ;;
  *) bad platform "$(uname -s) is not supported; see docs/supported-platforms.md" ;;
esac

if command -v uv >/dev/null 2>&1; then
  ok uv "$(uv --version) (it installs Python 3.12 itself)"
else
  bad uv "not found. Install: https://docs.astral.sh/uv/getting-started/installation/"
fi

if command -v node >/dev/null 2>&1; then
  version="$(node --version | tr -d v)"
  major="${version%%.*}"
  rest="${version#*.}"
  minor="${rest%%.*}"
  if ((major > MIN_NODE_MAJOR || (major == MIN_NODE_MAJOR && minor >= MIN_NODE_MINOR))); then
    ok node "v$version"
  else
    bad node "v$version is too old: $MIN_NODE_MAJOR.$MIN_NODE_MINOR or newer is required"
  fi
else
  bad node "not found. Install Node $MIN_NODE_MAJOR.$MIN_NODE_MINOR or newer: https://nodejs.org/"
fi

if command -v pnpm >/dev/null 2>&1; then
  version="$(pnpm --version 2>/dev/null)"
  if [[ "${version%%.*}" == "$PNPM_MAJOR" ]]; then
    ok pnpm "$version"
  else
    bad pnpm "$version found, but pnpm $PNPM_MAJOR is required: corepack enable, or https://pnpm.io/installation"
  fi
else
  bad pnpm "not found. Install pnpm $PNPM_MAJOR: corepack enable, or https://pnpm.io/installation"
fi

free_kib="$(df -Pk . | awk 'NR==2 {print $4}')"
free_gib=$((free_kib / 1024 / 1024))
if ((free_gib >= MIN_FREE_DISK_GIB)); then
  ok disk "$free_gib GiB free"
else
  warn disk "$free_gib GiB free; dependencies and the sandbox image need about $MIN_FREE_DISK_GIB GiB"
fi

if [[ "${1:-}" != "--no-docker" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    bad docker "not found. Install Docker Engine, Docker Desktop, Colima or OrbStack"
  elif ! memory="$(docker info --format '{{.MemTotal}}' 2>/dev/null)"; then
    bad docker "the daemon is not reachable. Start Docker, then run this again"
  else
    gib=$((memory / 1024 / 1024 / 1024))
    # A daemon reporting 1.9 GiB rounds down here, so compare in MiB.
    if ((memory / 1024 / 1024 >= MIN_DOCKER_MEMORY_GIB * 1000)); then
      ok docker "daemon reachable, about $gib GiB of memory, $(docker info --format '{{.NCPU}}') CPUs"
    else
      bad docker "the daemon has under $MIN_DOCKER_MEMORY_GIB GiB of memory. Give it more, then run this again"
    fi
  fi
fi

exit "$failed"
