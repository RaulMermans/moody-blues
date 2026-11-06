#!/usr/bin/env bash
# One deployment of one commit: shows it, asks, ships it with deploy.sh, then checks the public site.
# A deployment needs the owner's approval, so this always asks and never runs on its own.
#   release.sh <git-ref> [--dry-run]
set -euo pipefail
ref="${1:?usage: release.sh <git-ref> [--dry-run]}"
mode="${2:-}"
ip="${MOODY_VM_IP:-45.63.119.197}"
host="${MOODY_PUBLIC_HOST:-45-63-119-197.sslip.io}"
site="https://$host"
# A public page whose wording shows whether the KI-51 fix is live.
ki51_page="$site/investigations/inv_4e32358d2ff9"

cd "$(git rev-parse --show-toplevel)"
git fetch --quiet origin
sha="$(git rev-parse --verify "$ref^{commit}")"
short="${sha:0:7}"
# What runs in public must be reviewable on GitHub, not only on this laptop.
[[ -n "$(git branch -r --contains "$sha")" ]] || {
  echo "refused: $short is not on origin. Push it first." >&2
  exit 1
}

code() { curl -s -o /dev/null -m 20 -w '%{http_code}' "$1" || true; }
wrong_status() { curl -s -m 20 "$ki51_page" | grep -c 'wrong status' || true; }

echo "Site:      $site"
echo "Now live:  / $(code "$site/"), 'wrong status' on the KI-51 page: $(wrong_status)"
echo "Would ship: $short $(git log -1 --format=%s "$sha")"
echo "Reached by: $(git branch -r --contains "$sha" | grep -v HEAD | tr -d ' ' | paste -sd ' ' -)"
[[ "$mode" != "--dry-run" ]] || { echo "Dry run: nothing was deployed."; exit 0; }

read -r -p "This replaces the public site. Type $short to deploy it: " answer
[[ "$answer" == "$short" ]] || { echo "Cancelled. Nothing was deployed."; exit 1; }

# deploy.sh ships HEAD of its checkout, so a detached tree decides exactly what goes out.
tree="$(mktemp -d /tmp/mb-release.XXXXXX)"
trap 'git worktree remove --force "$tree" 2>/dev/null || true; rm -rf "$tree"' EXIT
git worktree add --quiet --detach "$tree" "$sha"
(cd "$tree" && infra/vultr/deploy.sh "$ip" "$host")

ok=false
for _ in $(seq 1 24); do
  [[ "$(code "$site/")" == "200" ]] && { ok=true; break; }
  sleep 5
done
problems=()
$ok || problems+=("/ did not return 200")
[[ "$(code "$site/containment")" == "200" ]] || problems+=("/containment did not return 200")
curl -s -m 20 "$site/api/status" | grep -q '"backend":"connected"' || problems+=("backend not connected")
[[ "$(code "$ki51_page")" == "200" ]] || problems+=("the KI-51 page did not return 200")
[[ "$(wrong_status)" == "0" ]] || problems+=("'wrong status' still on the KI-51 page")

if ((${#problems[@]})); then
  printf 'FAILED: %s\n' "${problems[@]}" >&2
  echo "Roll back with: infra/vultr/rollback.sh $ip" >&2
  exit 1
fi
echo "PASS: $short is live at $site"
echo "Next: MOODY_HOSTED_URL=$site MOODY_HOSTED_TARGET=vultr make test-hosted"
echo "Undo: infra/vultr/rollback.sh $ip"
