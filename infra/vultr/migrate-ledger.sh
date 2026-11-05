#!/usr/bin/env bash
# Moves the spend ledger to the VM, once, and proves it arrived unchanged. From then on the VM's
# ledger is the canonical one: do not make live calls from a laptop, or the two will diverge.
#   migrate-ledger.sh <vm-ip>
set -euo pipefail
ip="${1:?vm ip}"
root="$(git rev-parse --show-toplevel)"
cd "$root"
ssh_opts=(-o BatchMode=yes)
remote_ledger=/var/lib/moody-blues/artifacts/live-spend/ledger.jsonl
field() { python3 -I -c "import json,sys; print(json.load(sys.stdin)[sys.argv[1]])" "$1"; }

report="$(uv run moody-blues ledger-verify)"
[[ "$(field status <<<"$report")" == PASS ]] || { echo "local ledger failed verification" >&2; exit 1; }
[[ "$(field open_reservations <<<"$report")" == 0 ]] || { echo "local ledger has open reservations" >&2; exit 1; }
sha="$(field sha256 <<<"$report")"
settled="$(field settled_usd <<<"$report")"

remote_sha="$(ssh "${ssh_opts[@]}" "root@$ip" "[ -f '$remote_ledger' ] && sha256sum '$remote_ledger' | cut -d' ' -f1 || true")"
if [[ -n "$remote_sha" ]]; then
  [[ "$remote_sha" == "$sha" ]] || { echo "the VM already has a different ledger; refusing to overwrite it" >&2; exit 1; }
  echo "ledger already migrated"
else
  ssh "${ssh_opts[@]}" "root@$ip" "install -d -m 0700 -o moody -g moody '$(dirname "$remote_ledger")'"
  scp -q "${ssh_opts[@]}" .artifacts/live-spend/ledger.jsonl "root@$ip:$remote_ledger.incoming"
  ssh "${ssh_opts[@]}" "root@$ip" "chown moody:moody '$remote_ledger.incoming' && chmod 0600 '$remote_ledger.incoming' && mv '$remote_ledger.incoming' '$remote_ledger'"
fi

floor="$(python3 -I -c 'import math,sys; print(f"{math.floor(float(sys.argv[1]) * 100) / 100:.2f}")' "$settled")"
ssh "${ssh_opts[@]}" "root@$ip" "sed -i 's/^MOODY_LIVE_LEDGER_FLOOR_USD=.*/MOODY_LIVE_LEDGER_FLOOR_USD=$floor/' /etc/moody-blues/backend.env && systemctl restart moody-backend"

hosted="$(ssh "${ssh_opts[@]}" "root@$ip" /usr/local/bin/moody-cli ledger-verify)"
[[ "$(field sha256 <<<"$hosted")" == "$sha" ]] || { echo "hash differs after the copy" >&2; exit 1; }
[[ "$(field above_floor <<<"$hosted")" == True ]] || { echo "ledger is below its floor" >&2; exit 1; }
echo "ledger on VM: sha256 $sha, settled \$$settled, floor \$$floor"
