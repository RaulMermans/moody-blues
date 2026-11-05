#!/usr/bin/env bash
# Vultr lifecycle for the single MOODY BLUES VM.
#
#   provision.sh plan                          read-only; public API; no credential; no charge
#   provision.sh status                        read-only; needs VULTR_API_KEY
#   provision.sh apply  --confirm <plan>@<region> --admin-cidr <ip>/32 --ssh-key <file.pub>   CHARGEABLE
#   provision.sh destroy --confirm <instance-id>                                              IRREVERSIBLE
#
# VULTR_API_KEY is the *account* key (my.vultr.com > Account > API), never the inference key.
# It is read from the environment, given to curl on a file descriptor, and never written anywhere.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=infra/vultr/plan.env
source "$here/plan.env"
api="https://api.vultr.com/v2"
state="${MB_STATE_FILE:-$here/../../.artifacts/vultr-state.json}"

die() { echo "error: $*" >&2; exit 1; }
need_key() { [[ -n "${VULTR_API_KEY:-}" ]] || die "VULTR_API_KEY (account key) is not set"; }
json() { python3 -I -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {'d': d}))" "$1"; }

call() { # call METHOD PATH [JSON]; fails on any non-2xx
  local method="$1" path="$2" body="${3:-}" out code
  out="$(mktemp)"
  code="$(curl -sS --max-time 30 -o "$out" -w '%{http_code}' -X "$method" "$api$path" \
    -K <(printf 'header = "Authorization: Bearer %s"\n' "$VULTR_API_KEY") \
    -H 'Content-Type: application/json' ${body:+--data "$body"})"
  if [[ "$code" != 2* ]]; then
    echo "error: $method $path answered HTTP $code: $(head -c 300 "$out")" >&2
    rm -f "$out"
    return 1
  fi
  cat "$out"
  rm -f "$out"
}

state_get() { python3 -I -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],''))" "$state" "$1"; }

state_put() { # state_put key value; keeps what was created so a failed apply can still be destroyed
  python3 -I - "$state" "$1" "$2" <<'PY'
import json, os, sys
path, key, value = sys.argv[1:4]
data = json.load(open(path)) if os.path.exists(path) else {}
data[key] = value
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(data, open(path, "w"), indent=1)
PY
}

plan() {
  PLANS="$(curl -sS --max-time 30 "$api/plans?per_page=500")" python3 -I - \
    "$MB_PLAN" "$MB_REGION" "$MB_HOURLY_CEILING_USD" <<'PY'
import json, os, sys

plan, region, ceiling = sys.argv[1], sys.argv[2], float(sys.argv[3])
found = [p for p in json.loads(os.environ["PLANS"])["plans"] if p["id"] == plan]
if not found:
    sys.exit(f"plan {plan} no longer exists")
p = found[0]
hourly, monthly = p["hourly_cost"], p["monthly_cost"]
where = "available" if region in p["locations"] else "NOT AVAILABLE"
print(f"plan      {plan}: {p['vcpu_count']} vCPU, {p['ram']} MB, {p['disk']} GB, {p['bandwidth']} GB transfer")
print(f"region    {region}: {where}")
print(f"price     ${hourly}/hour, capped at ${monthly}/month (list price, before any tax)")
print(f"per day   ${hourly * 24:.2f}")
if hourly > ceiling:
    sys.exit(f"price is above the reviewed ceiling of ${ceiling}/hour")
if region not in p["locations"]:
    sys.exit(1)
if p["disk"] < 40:
    sys.exit("plan has too little disk for Docker and the application")
PY
  cat <<T

creates   1 SSH key, 1 firewall group (22 from one address; 80 and 443 from anywhere), 1 instance
off       automatic backups, IPv6, DDoS protection, block storage, load balancer, snapshots
billing   a stopped instance still bills; only destroy stops the charge
T
}

apply() {
  local confirm="" cidr="" pub=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --confirm) confirm="$2"; shift 2 ;;
      --admin-cidr) cidr="$2"; shift 2 ;;
      --ssh-key) pub="$2"; shift 2 ;;
      *) die "unknown option $1" ;;
    esac
  done
  [[ "$confirm" == "$MB_PLAN@$MB_REGION" ]] || die "--confirm must be exactly $MB_PLAN@$MB_REGION"
  [[ "$cidr" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/32$ ]] || die "--admin-cidr must be one address, a.b.c.d/32"
  [[ -f "$pub" && "$pub" == *.pub ]] || die "--ssh-key must be a public key file"
  [[ ! -e "$state" ]] || die "$state exists: this VM may already be running. Run status, or destroy first"
  need_key
  plan

  local ssh_id fw_id instance_id port
  ssh_id="$(call POST /ssh-keys "$(python3 -I -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "ssh_key": open(sys.argv[2]).read().strip()}))' "$MB_LABEL" "$pub")" | json 'd["ssh_key"]["id"]')"
  state_put ssh_key_id "$ssh_id"
  fw_id="$(call POST /firewalls "{\"description\":\"$MB_LABEL\"}" | json 'd["firewall_group"]["id"]')"
  state_put firewall_group_id "$fw_id"
  call POST "/firewalls/$fw_id/rules" "{\"ip_type\":\"v4\",\"protocol\":\"tcp\",\"subnet\":\"${cidr%/*}\",\"subnet_size\":32,\"port\":\"22\",\"notes\":\"admin ssh\"}" >/dev/null
  for port in 80 443; do
    call POST "/firewalls/$fw_id/rules" "{\"ip_type\":\"v4\",\"protocol\":\"tcp\",\"subnet\":\"0.0.0.0\",\"subnet_size\":0,\"port\":\"$port\",\"notes\":\"public web\"}" >/dev/null
  done
  instance_id="$(call POST /instances "{\"region\":\"$MB_REGION\",\"plan\":\"$MB_PLAN\",\"os_id\":$MB_OS_ID,\"label\":\"$MB_LABEL\",\"hostname\":\"$MB_LABEL\",\"tags\":[\"$MB_TAG\"],\"sshkey_id\":[\"$ssh_id\"],\"firewall_group_id\":\"$fw_id\",\"backups\":\"disabled\",\"enable_ipv6\":false,\"ddos_protection\":false,\"activation_email\":false}" | json 'd["instance"]["id"]')"
  state_put instance_id "$instance_id"
  echo "instance $instance_id created; billing has started. Run: provision.sh status"
}

status() {
  need_key
  [[ -e "$state" ]] || die "no state file: nothing was provisioned from this checkout"
  call GET "/instances/$(state_get instance_id)" | python3 -I -c '
import json, sys
i = json.load(sys.stdin)["instance"]
for k in ("id", "label", "region", "plan", "status", "power_status", "server_status", "main_ip", "firewall_group_id"):
    print(f"{k:18} {i.get(k)}")'
}

destroy() {
  [[ "${1:-}" == "--confirm" && -n "${2:-}" ]] || die "usage: destroy --confirm <instance-id>"
  need_key
  [[ -e "$state" ]] || die "no state file"
  local id; id="$(state_get instance_id)"
  [[ "$2" == "$id" ]] || die "--confirm does not match the instance in $state"
  call DELETE "/instances/$id" >/dev/null
  echo "instance $id destroyed; billing stopped"
  local fw ssh_id; fw="$(state_get firewall_group_id)"; ssh_id="$(state_get ssh_key_id)"
  # The firewall group stays attached for a moment after the instance goes.
  for _ in 1 2 3 4 5 6; do call DELETE "/firewalls/$fw" >/dev/null 2>&1 && { fw=""; break; }; sleep 10; done
  [[ -z "$fw" ]] || echo "warning: firewall group $fw remains (free); delete it in the console" >&2
  call DELETE "/ssh-keys/$ssh_id" >/dev/null || echo "warning: SSH key $ssh_id remains (free)" >&2
  rm -f "$state"
  echo "done. Check the console shows no instance, snapshot or block storage."
}

cmd="${1:-}"; shift || true
case "$cmd" in
  plan) plan ;;
  status) status ;;
  apply) apply "$@" ;;
  destroy) destroy "$@" ;;
  *) die "usage: provision.sh plan|status|apply|destroy" ;;
esac
