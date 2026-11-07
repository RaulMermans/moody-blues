#!/usr/bin/env bash
# Keep the public site on the latest main: push local main if it is ahead, wait for GitHub CI on origin/main,
# then deploy it through release.sh. The owner approved deploying every green commit on main (2026-11-07), so
# this answers release.sh's confirmation itself. It deploys only a commit whose CI passed, and only from this
# laptop, the one address allowed to SSH to the VM.
#   ship.sh            deploy origin/main if it is green and not already live
#   ship.sh --dry-run  say what it would do
set -euo pipefail
mode="${1:-}"
host="${MOODY_PUBLIC_HOST:-45-63-119-197.sslip.io}"
site="https://$host"

cd "$(git rev-parse --show-toplevel)"
git fetch --quiet origin

if [[ "$(git branch --show-current)" == "main" ]] && [[ -n "$(git rev-list origin/main..main)" ]]; then
  if [[ "$mode" == "--dry-run" ]]; then
    echo "Would push local main first."
  else
    git push origin main
    git fetch --quiet origin
  fi
fi

sha="$(git rev-parse origin/main)"
short="${sha:0:7}"
live="$(curl -s -m 20 "$site/api/status" | sed -n 's/.*"revision":"\([0-9a-f]*\)".*/\1/p')"
echo "origin/main: $short $(git log -1 --format=%s "$sha")"
echo "live:        ${live:0:7}"
[[ "$live" != "$sha" ]] || { echo "Already live. Nothing to do."; exit 0; }

run="$(gh run list --workflow CI --commit "$sha" --event push --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
for _ in $(seq 1 30); do
  [[ -n "$run" ]] && break
  echo "Waiting for CI to start on $short..."
  sleep 10
  run="$(gh run list --workflow CI --commit "$sha" --event push --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
done
[[ -n "$run" ]] || { echo "refused: no CI run found for $short. Nothing was deployed." >&2; exit 1; }

if [[ "$mode" == "--dry-run" ]]; then
  echo "CI run $run: $(gh run view "$run" --json status,conclusion --jq '.status + " " + .conclusion')"
  echo "Dry run: would deploy $short once that run passes. Nothing was deployed."
  exit 0
fi

echo "Waiting for CI run $run on $short..."
gh run watch "$run" --exit-status >/dev/null || {
  echo "refused: CI failed for $short. Nothing was deployed. https://github.com/RaulMermans/moody-blues/actions/runs/$run" >&2
  exit 1
}
echo "CI passed. Deploying $short."
echo "$short" | infra/vultr/release.sh "$sha"
