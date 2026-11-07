#!/usr/bin/env bash
# Builds an unpacked release, then hands it to remote-switch.sh. Runs as root on the VM.
#   remote-install.sh <release-sha> <public-host>
set -euo pipefail
sha="${1:?release sha}"
host="${2:?public host}"
base=/opt/moody-blues
release="$base/releases/$sha"
cd "$release"

export UV_PYTHON_PREFERENCE=only-system PATH="/usr/local/bin:$PATH"
uv sync --frozen --no-dev
(
  cd frontend
  pnpm install --frozen-lockfile
  NEXT_TELEMETRY_DISABLED=1 pnpm build
)
echo "$sha" > "$release/REVISION" # shown by /health, so what is live can be read from outside
chown -R root:root "$release"
chmod -R go-w "$release"
chown -R moody-web:moody-web frontend/.next

cat > /etc/moody-blues/web.env <<ENV
NODE_ENV=production
NEXT_TELEMETRY_DISABLED=1
MOODY_BACKEND_URL=http://127.0.0.1:8000
MOODY_PUBLIC_ORIGIN=https://$host
ENV
chmod 0644 /etc/moody-blues/web.env

install -d /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironment=MOODY_PUBLIC_HOST=%s\n' "$host" > /etc/systemd/system/caddy.service.d/moody.conf

bash "$release/infra/vultr/remote-switch.sh" "$sha"

# Keep the three newest releases, and always the current and previous ones.
keep="$(readlink -f "$base/current"); $(cat "$base/previous" 2>/dev/null || true)"
ls -1dt "$base"/releases/* | tail -n +4 | while read -r old; do
  [[ "$keep" == *"$old"* ]] || rm -rf -- "$old"
done
