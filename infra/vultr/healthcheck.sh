#!/usr/bin/env bash
# Writes one line to the journal. Exits non-zero if anything is wrong, so `systemctl --failed` shows it.
# It never restarts or deletes anything: evidence is removed by a person, deliberately.
set -uo pipefail
problems=()
curl -fsS --max-time 5 http://127.0.0.1:8000/health >/dev/null || problems+=(backend)
curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:3000/ || problems+=(web)
used="$(df --output=pcent /var/lib/moody-blues | tail -1 | tr -dc '0-9')"
[[ "$used" -lt 80 ]] || problems+=("disk_${used}pct")
leftovers="$(docker ps -aq --filter label=io.moody-blues.sandbox --filter status=exited --filter status=created | wc -l)"
[[ "$leftovers" -eq 0 ]] || problems+=("stopped_sandboxes_${leftovers}")
if [[ ${#problems[@]} -eq 0 ]]; then
  echo "moody-health ok disk=${used}% artifacts=$(du -sm /var/lib/moody-blues | cut -f1)MB"
else
  echo "moody-health FAIL ${problems[*]}" >&2
  exit 1
fi
