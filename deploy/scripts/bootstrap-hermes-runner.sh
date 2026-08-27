#!/usr/bin/env sh
set -eu

RUNNER_USER=${RUNNER_USER:-hermes-runner}
RUNNER_HOSTNAME=${RUNNER_HOSTNAME:-hermes}

fail() {
  echo "runner-bootstrap=failed check=$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || fail root-required

. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ] || fail "Ubuntu 24.04-required"

export DEBIAN_FRONTEND=noninteractive
hostnamectl set-hostname "$RUNNER_HOSTNAME"

apt-get update
apt-get install -y ca-certificates curl gnupg uidmap dbus-user-session slirp4netns fuse-overlayfs jq

install -m 0755 -d /etc/apt/keyrings
docker_key=$(mktemp)
trap 'rm -f "$docker_key"' EXIT
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$docker_key"
gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg "$docker_key"
chmod a+r /etc/apt/keyrings/docker.gpg

architecture=$(dpkg --print-architecture)
printf '%s\n' \
  "deb [arch=$architecture signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin \
  docker-ce-rootless-extras

systemctl disable --now docker.service docker.socket containerd.service >/dev/null 2>&1 || true
systemctl mask docker.service docker.socket containerd.service >/dev/null
rm -f /var/run/docker.sock

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --user-group --shell /bin/bash "$RUNNER_USER"
fi
usermod --lock "$RUNNER_USER"

if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx sudo; then
  deluser "$RUNNER_USER" sudo >/dev/null
fi

awk -F: -v user="$RUNNER_USER" '$1 == user && $3 >= 65536 { found = 1 } END { exit !found }' /etc/subuid \
  || fail subuid-range
awk -F: -v user="$RUNNER_USER" '$1 == user && $3 >= 65536 { found = 1 } END { exit !found }' /etc/subgid \
  || fail subgid-range

install -d /etc/systemd/system/user@.service.d
cat > /etc/systemd/system/user@.service.d/delegate.conf <<'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
systemctl daemon-reload

runner_uid=$(id -u "$RUNNER_USER")
runner_home=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
runner_runtime="/run/user/$runner_uid"
runner_bus="unix:path=$runner_runtime/bus"

loginctl enable-linger "$RUNNER_USER"
systemctl restart "user@$runner_uid.service"

runner() {
  runuser -u "$RUNNER_USER" -- env \
    HOME="$runner_home" \
    USER="$RUNNER_USER" \
    LOGNAME="$RUNNER_USER" \
    XDG_RUNTIME_DIR="$runner_runtime" \
    DBUS_SESSION_BUS_ADDRESS="$runner_bus" \
    PATH=/usr/local/bin:/usr/bin:/bin \
    "$@"
}

runner dockerd-rootless-setuptool.sh install --force
runner systemctl --user stop docker.service

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$runner_home/.config/docker"
cat > "$runner_home/.config/docker/daemon.json" <<EOF
{
  "group": "$RUNNER_USER",
  "log-driver": "local",
  "log-opts": {
    "max-size": "10m"
  },
  "live-restore": false
}
EOF
chown "$RUNNER_USER:$RUNNER_USER" "$runner_home/.config/docker/daemon.json"
chmod 0600 "$runner_home/.config/docker/daemon.json"

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$runner_home/.config/environment.d"
printf 'DOCKER_HOST=unix:///run/user/%s/docker.sock\n' "$runner_uid" \
  > "$runner_home/.config/environment.d/10-docker.conf"
chown "$RUNNER_USER:$RUNNER_USER" "$runner_home/.config/environment.d/10-docker.conf"
chmod 0600 "$runner_home/.config/environment.d/10-docker.conf"

runner systemctl --user daemon-reload
runner systemctl --user enable --now docker.service

docker_host="unix:///run/user/$runner_uid/docker.sock"
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if runner env "DOCKER_HOST=$docker_host" docker info >/dev/null 2>&1; then
    break
  fi
  [ "$attempt" -lt 10 ] || fail rootless-daemon-readiness
  sleep 1
done

test ! -S /var/run/docker.sock || fail rootful-socket-present
[ "$(systemctl is-enabled docker.socket 2>/dev/null || true)" = masked ] \
  || fail rootful-socket-not-masked
[ "$(systemctl is-enabled docker.service 2>/dev/null || true)" = masked ] \
  || fail rootful-service-not-masked
id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx sudo && fail runner-has-sudo

runner env "DOCKER_HOST=$docker_host" docker info --format '{{json .SecurityOptions}}' \
  | grep -q "name=rootless" || fail daemon-not-rootless

controllers=$(cat "/sys/fs/cgroup/user.slice/user-$runner_uid.slice/user@$runner_uid.service/cgroup.controllers")
for controller in cpu memory pids; do
  echo "$controllers" | tr ' ' '\n' | grep -qx "$controller" || fail "cgroup-$controller-not-delegated"
done

printf 'runner-bootstrap=passed user=%s uid=%s docker_host=%s\n' \
  "$RUNNER_USER" "$runner_uid" "$docker_host"
