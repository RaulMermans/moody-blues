#!/usr/bin/env bash
# One-time host setup. Runs as root on the VM; safe to run again.
#   ADMIN_CIDR=a.b.c.d/32 bash bootstrap.sh
set -euo pipefail
: "${ADMIN_CIDR:?set ADMIN_CIDR to the one address allowed to use SSH}"

NODE_VERSION=20.20.0
UV_VERSION=0.11.14
PNPM_VERSION=10.26.0
IMAGE="python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DEBIAN_FRONTEND=noninteractive

[[ "$(uname -m)" == x86_64 ]] || { echo "expected an AMD64 host" >&2; exit 1; }

apt-get update -q
apt-get install -yq ca-certificates curl gnupg ufw docker.io unattended-upgrades xz-utils

# Caddy's own signed repository: it is the public edge, so it should not lag.
if [[ ! -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]]; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    -o /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
fi
apt-get install -yq caddy

# Node from nodejs.org, checked against its published sums.
if [[ "$(/usr/local/bin/node --version 2>/dev/null || true)" != "v$NODE_VERSION" ]]; then
  work="$(mktemp -d)"
  tarball="node-v$NODE_VERSION-linux-x64.tar.xz"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$tarball" -o "$work/$tarball"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" -o "$work/sums"
  (cd "$work" && grep " $tarball\$" sums | sha256sum -c -)
  tar -xJf "$work/$tarball" -C /usr/local --strip-components=1 --exclude=README.md --exclude=LICENSE --exclude=CHANGELOG.md
  rm -rf "$work"
fi
npm install -g "pnpm@$PNPM_VERSION" --silent

if [[ "$(/usr/local/bin/uv --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]]; then
  curl -fsSL "https://astral.sh/uv/$UV_VERSION/install.sh" \
    | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

# Two users. Only the backend can reach Docker, and the web tier holds no secret.
id moody >/dev/null 2>&1 || useradd --system --home-dir /var/lib/moody-blues --shell /usr/sbin/nologin moody
id moody-web >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin moody-web
usermod -aG docker moody

install -d -m 0755 /opt/moody-blues /opt/moody-blues/releases
install -d -m 0750 -o moody -g moody /var/lib/moody-blues
install -d -m 0700 -o moody -g moody /var/lib/moody-blues/artifacts /var/lib/moody-blues/artifacts/containment
install -d -m 0750 -o root -g moody /etc/moody-blues

if [[ ! -f /etc/moody-blues/backend.env ]]; then
  install -m 0640 -o root -g moody "$here/config/backend.env.example" /etc/moody-blues/backend.env
  # Created here, so it never crosses a network. Read it with: grep TOKEN /etc/moody-blues/backend.env
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
  sed -i "s|^MOODY_OPERATOR_TOKEN=.*|MOODY_OPERATOR_TOKEN=$token|" /etc/moody-blues/backend.env
fi

install -m 0644 "$here/config/docker-daemon.json" /etc/docker/daemon.json
install -d /etc/systemd/journald.conf.d
install -m 0644 "$here/config/journald.conf" /etc/systemd/journald.conf.d/moody.conf
systemctl restart systemd-journald
systemctl enable docker
systemctl restart docker
systemctl enable --now unattended-upgrades

# Pulled once, here, by digest. The application never pulls.
docker pull "$IMAGE"
docker image inspect "$IMAGE" >/dev/null

# SSH: keys only.
install -d /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
  > /etc/ssh/sshd_config.d/50-moody.conf
sshd -t
systemctl reload ssh

# Host firewall, under the Vultr firewall group. Docker publishes no port, so it cannot bypass this.
rule='-A ufw-before-input -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -m hashlimit --hashlimit-name mb_web --hashlimit-mode srcip --hashlimit-above 30/second --hashlimit-burst 120 -j DROP'
grep -qF 'mb_web' /etc/ufw/before.rules || sed -i "/^# allow all on loopback/i # moody-blues: new connections per source\n$rule\n" /etc/ufw/before.rules
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$ADMIN_CIDR" to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw reload

install -m 0755 "$here/moody-cli" /usr/local/bin/moody-cli
echo "bootstrap complete: $(docker --version); $(caddy version | cut -d' ' -f1); node $(/usr/local/bin/node --version)"
