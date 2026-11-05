#!/usr/bin/env bash
# Ships the committed HEAD to the VM. Needs owner approval: this is an external deployment.
#   deploy.sh <vm-ip> <public-host>
set -euo pipefail
ip="${1:?vm ip}"
host="${2:?public host}"
root="$(git rev-parse --show-toplevel)"
cd "$root"

[[ -z "$(git status --porcelain)" ]] || { echo "working tree is not clean" >&2; exit 1; }
sha="$(git rev-parse HEAD)"
ssh_opts=(-o StrictHostKeyChecking=accept-new -o BatchMode=yes)
release="/opt/moody-blues/releases/$sha"

# git archive holds tracked files only, so .env, .artifacts and the ledger cannot ride along.
ssh "${ssh_opts[@]}" "root@$ip" "mkdir -p '$release'"
git archive --format=tar HEAD | ssh "${ssh_opts[@]}" "root@$ip" "tar -x -C '$release'"
ssh "${ssh_opts[@]}" "root@$ip" "bash '$release/infra/vultr/remote-install.sh' '$sha' '$host'"
echo "deployed $sha to https://$host"
