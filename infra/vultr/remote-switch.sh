#!/usr/bin/env bash
# Points `current` at a release and proves it serves; on failure goes back. Runs as root on the VM.
#   remote-switch.sh <release-sha>
set -euo pipefail
sha="${1:?release sha}"
base=/opt/moody-blues
target="$base/releases/$sha"
[[ -d "$target/.venv" && -d "$target/frontend/.next" ]] || { echo "release $sha is not built" >&2; exit 1; }

# Restarting mid-job would end it as outcome_uncertain, so refuse instead.
token="$(sed -n 's/^MOODY_OPERATOR_TOKEN=//p' /etc/moody-blues/backend.env)"
if systemctl is-active --quiet moody-backend; then
  active="$(curl -fsS --max-time 5 -K <(printf 'header = "Authorization: Bearer %s"\n' "$token") \
    http://127.0.0.1:8000/operator/status \
    | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["active_job_id"] or "")' || true)"
  [[ -z "$active" ]] || { echo "job $active is running; wait or cancel it first" >&2; exit 1; }
fi

previous="$(readlink -f "$base/current" 2>/dev/null || true)"

point_at() {
  ln -sfn "$1" "$base/current.next"
  mv -T "$base/current.next" "$base/current"
}

restart() {
  install -m 0644 "$base/current/infra/vultr/systemd/"* /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable moody-backend moody-web moody-healthcheck.timer >/dev/null
  systemctl restart moody-backend
  systemctl restart moody-web
  install -m 0644 "$base/current/infra/vultr/config/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload-or-restart caddy
}

serving() {
  local i
  for i in $(seq 1 30); do
    curl -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1 \
      && curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:3000/ 2>/dev/null && break
    sleep 2
    [[ "$i" -lt 30 ]] || return 1
  done
  # Anything other than loopback here means a private service is listening in public.
  if ss -H -ltn '( sport = :8000 or sport = :3000 )' | awk '{print $4}' | grep -qv '^127\.0\.0\.1:'; then
    echo "a private service is not bound to loopback" >&2
    return 1
  fi
  /usr/local/bin/moody-cli recorded-verify >/dev/null
  /usr/local/bin/moody-cli investigator-preflight >/dev/null
}

point_at "$target"
restart
if serving; then
  # Only now: started earlier, its first run lands while the services are still restarting.
  systemctl start moody-healthcheck.timer
  [[ -z "$previous" || "$previous" == "$target" ]] || echo "$previous" > "$base/previous"
  echo "serving $sha"
  exit 0
fi

echo "release $sha failed its checks" >&2
if [[ -n "$previous" && "$previous" != "$target" ]]; then
  point_at "$previous"
  restart
  serving && echo "back on $(basename "$previous")" >&2
fi
exit 1
