#!/usr/bin/env bash
# Returns the VM to its previous release, or to a named one. State in /var/lib is untouched.
#   rollback.sh <vm-ip> [release-sha]
set -euo pipefail
ip="${1:?vm ip}"
sha="${2:-}"
# shellcheck disable=SC2029  # expanded here on purpose
ssh -o BatchMode=yes "root@$ip" "
  set -e
  sha='$sha'
  [ -n \"\$sha\" ] || sha=\"\$(basename \"\$(cat /opt/moody-blues/previous)\")\"
  bash /opt/moody-blues/current/infra/vultr/remote-switch.sh \"\$sha\"
"
