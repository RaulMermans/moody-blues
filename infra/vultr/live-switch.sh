#!/usr/bin/env bash
# The owner's switch for chargeable missions. The key goes over SSH on stdin, never as an argument.
#   live-switch.sh <vm-ip> on <limit-usd>     needs the owner's approval of that limit
#   live-switch.sh <vm-ip> off                removes the key and turns live runs off
set -euo pipefail
ip="${1:?vm ip}"
mode="${2:?on or off}"
root="$(git rev-parse --show-toplevel)"
env_file=/etc/moody-blues/backend.env

case "$mode" in
  on)
    limit="${3:?limit in USD}"
    [[ "$limit" =~ ^[0-9]+(\.[0-9]{1,2})?$ ]] || { echo "limit must be a number" >&2; exit 1; }
    grep '^MOODY_VULTR_API_KEY=' "$root/.env" | cut -d= -f2- | ssh -o BatchMode=yes "root@$ip" "
      set -e
      IFS= read -r key
      [ -n \"\$key\" ]
      sed -i \"s|^MOODY_VULTR_API_KEY=.*|MOODY_VULTR_API_KEY=\$key|\" $env_file
      sed -i 's/^MOODY_LIVE_RUNS_ENABLED=.*/MOODY_LIVE_RUNS_ENABLED=true/' $env_file
      sed -i 's/^MOODY_LIVE_SPEND_LIMIT_USD=.*/MOODY_LIVE_SPEND_LIMIT_USD=$limit/' $env_file
      systemctl restart moody-backend
    "
    echo "live runs on, ledger limit \$$limit" ;;
  off)
    ssh -o BatchMode=yes "root@$ip" "
      set -e
      sed -i 's|^MOODY_VULTR_API_KEY=.*|MOODY_VULTR_API_KEY=|' $env_file
      sed -i 's/^MOODY_LIVE_RUNS_ENABLED=.*/MOODY_LIVE_RUNS_ENABLED=false/' $env_file
      sed -i 's/^MOODY_LIVE_SPEND_LIMIT_USD=.*/MOODY_LIVE_SPEND_LIMIT_USD=5/' $env_file
      systemctl restart moody-backend
    "
    echo "live runs off, key removed" ;;
  *) echo "on or off" >&2; exit 1 ;;
esac
