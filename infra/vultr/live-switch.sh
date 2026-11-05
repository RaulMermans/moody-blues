#!/usr/bin/env bash
# The owner's switch for chargeable missions. The key travels over SSH on stdin: never as an argument
# here or on the VM, where any process could read it. live-env.py does the rewrite.
#   live-switch.sh <vm-ip> on <limit-usd>     needs the owner's approval of that limit
#   live-switch.sh <vm-ip> off                removes the key and turns live runs off
set -euo pipefail
ip="${1:?vm ip}"
mode="${2:?on or off}"
root="$(git rev-parse --show-toplevel)"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Code only, sent as text so the switch works whichever release the VM is on.
remote="python3 -I -c $(printf '%q' "$(cat "$here/live-env.py")")"

case "$mode" in
  on)
    limit="${3:?limit in USD}"
    [[ "$limit" =~ ^[0-9]+(\.[0-9]{1,2})?$ ]] || { echo "limit must be a number" >&2; exit 1; }
    grep '^MOODY_VULTR_API_KEY=' "$root/.env" | cut -d= -f2- \
      | ssh -o BatchMode=yes "root@$ip" "$remote on $limit" ;;
  off)
    ssh -o BatchMode=yes "root@$ip" "$remote off" </dev/null ;;
  *) echo "on or off" >&2; exit 1 ;;
esac
