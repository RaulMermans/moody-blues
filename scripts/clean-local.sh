#!/usr/bin/env bash
# Removes one thing: the disposable directory `make quickstart` made. It must carry the marker that
# only local-env.sh writes, so this can never reach .artifacts, evidence or a directory it did not make.
set -euo pipefail
cd "$(dirname "$0")/.."

dir=.moody-local
if [[ ! -e "$dir" ]]; then
  echo "Nothing to remove: $dir does not exist."
  exit 0
fi
if [[ -L "$dir" || ! -f "$dir/.moody-disposable" ]]; then
  echo "Refusing: $dir is not a directory this project marked as disposable." >&2
  exit 1
fi
rm -rf -- "$dir"
echo "Removed $dir. Recorded evidence, .artifacts and the spend ledger were not touched."
