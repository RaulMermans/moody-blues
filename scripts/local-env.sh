#!/usr/bin/env bash
# Prints the environment for local, disposable work, to be evaluated by a make recipe:
#   eval "$(scripts/local-env.sh)"
# An explicit MOODY_ARTIFACTS_DIR, in the environment or in .env, is left alone: that is a choice.
# The default directory has its own empty ledger, so live runs stay off there: a chargeable mission
# must never get a fresh budget by accident. The token only opens this machine's own local runs.
set -euo pipefail
cd "$(dirname "$0")/.."

from_env_file() {
  [[ -f .env ]] || return 0
  grep -E "^$1=." .env | tail -n 1 | cut -d= -f2- || true
}

dir="${MOODY_ARTIFACTS_DIR:-$(from_env_file MOODY_ARTIFACTS_DIR)}"
if [[ -n "$dir" ]]; then
  exit 0
fi

dir="$PWD/.moody-local"
mkdir -p "$dir"
touch "$dir/.moody-disposable"
printf 'export MOODY_ARTIFACTS_DIR=%q\n' "$dir"
printf 'export MOODY_LIVE_RUNS_ENABLED=false\n'

if [[ -z "${MOODY_OPERATOR_TOKEN:-$(from_env_file MOODY_OPERATOR_TOKEN)}" ]]; then
  token_file="$dir/operator-token"
  if [[ ! -s "$token_file" ]]; then
    (umask 077 && LC_ALL=C tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 48 >"$token_file")
  fi
  printf 'export MOODY_OPERATOR_TOKEN=%q\n' "$(cat "$token_file")"
fi
