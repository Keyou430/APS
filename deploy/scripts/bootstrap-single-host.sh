#!/usr/bin/env sh
set -eu

RUNNER_USER=hermes-runner
CONTROL_PORT=${RUNNER_CONTROL_PORT:-9443}
DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_ROOT="$DEPLOY_ROOT/.runtime"
SSH_RUNTIME="$RUNTIME_ROOT/hermes-runner-ssh"
CONTROL_RUNTIME="$RUNTIME_ROOT/hermes-runner-control"
CA_RUNTIME="$RUNTIME_ROOT/single-host-ca"

fail() {
  echo "single-host-bootstrap=failed check=$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || fail root-required
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ] || fail ubuntu-24.04-required

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg openssh-server openssl python3 python3-yaml \
  uidmap dbus-user-session slirp4netns fuse-overlayfs rootlesskit jq

if ! command -v docker >/dev/null 2>&1; then
  if ! apt-cache show docker-ce-rootless-extras >/dev/null 2>&1; then
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
  rm -f "$docker_key"
  trap - EXIT
  fi

  apt-get install -y --no-install-recommends \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin docker-ce-rootless-extras
fi
systemctl unmask docker.service docker.socket containerd.service >/dev/null 2>&1 || true
systemctl enable --now containerd.service docker.service ssh.service
test -S /var/run/docker.sock || fail standard-docker-socket
docker info >/dev/null 2>&1 || fail standard-docker-readiness
deploy_operator=${SUDO_USER:-}
if [ -n "$deploy_operator" ] && [ "$deploy_operator" != root ] && id "$deploy_operator" >/dev/null 2>&1; then
  usermod -aG docker "$deploy_operator"
fi

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --user-group --shell /bin/bash "$RUNNER_USER"
fi
usermod --lock "$RUNNER_USER"
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx sudo; then
  deluser "$RUNNER_USER" sudo >/dev/null
fi
if ! awk -F: -v user="$RUNNER_USER" '$1 == user && $3 >= 65536 { found = 1 } END { exit !found }' /etc/subuid; then
  fail runner-subuid-range
fi
if ! awk -F: -v user="$RUNNER_USER" '$1 == user && $3 >= 65536 { found = 1 } END { exit !found }' /etc/subgid; then
  fail runner-subgid-range
fi

install -d /etc/systemd/system/user@.service.d
install -m 0644 /dev/null /etc/systemd/system/user@.service.d/delegate.conf
printf '%s\n' '[Service]' 'Delegate=cpu cpuset io memory pids' \
  > /etc/systemd/system/user@.service.d/delegate.conf
systemctl daemon-reload

runner_uid=$(id -u "$RUNNER_USER")
runner_home=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
runner_runtime="/run/user/$runner_uid"
runner_bus="unix:path=$runner_runtime/bus"
docker_host="unix://$runner_runtime/docker.sock"

loginctl enable-linger "$RUNNER_USER"
systemctl restart "user@$runner_uid.service"

runner() {
  runuser -u "$RUNNER_USER" -- env \
    HOME="$runner_home" USER="$RUNNER_USER" LOGNAME="$RUNNER_USER" \
    XDG_RUNTIME_DIR="$runner_runtime" DBUS_SESSION_BUS_ADDRESS="$runner_bus" \
    PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$runner_home/.config/docker"
install -m 0600 /dev/null "$runner_home/.config/docker/daemon.json"
printf '%s\n' \
  '{' \
  '  "log-driver": "local",' \
  '  "log-opts": {"max-size": "10m", "max-file": "3"},' \
  '  "live-restore": false' \
  '}' > "$runner_home/.config/docker/daemon.json"
chown "$RUNNER_USER:$RUNNER_USER" "$runner_home/.config/docker/daemon.json"
if command -v dockerd-rootless-setuptool.sh >/dev/null 2>&1; then
  runner dockerd-rootless-setuptool.sh install --force
else
  command -v rootlesskit >/dev/null 2>&1 || fail rootlesskit-missing
  install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 \
    "$runner_home/.config/systemd/user"
  install -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0644 /dev/null \
    "$runner_home/.config/systemd/user/docker.service"
  cat > "$runner_home/.config/systemd/user/docker.service" <<EOF
[Unit]
Description=Rootless Docker
After=network.target

[Service]
Type=notify
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=DOCKERD_ROOTLESS_ROOTLESSKIT_NET=slirp4netns
Environment=DOCKERD_ROOTLESS_ROOTLESSKIT_PORT_DRIVER=none
ExecStart=/usr/bin/rootlesskit --net=slirp4netns --mtu=65520 --copy-up=/etc --copy-up=/run --propagation=rslave /usr/bin/dockerd --host=unix://%t/docker.sock --data-root=%h/.local/share/docker --exec-root=%t/docker --pidfile=%t/docker.pid --storage-driver=vfs --iptables=false --bridge=none
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=on-failure
RestartSec=3
LimitNOFILE=1048576
Delegate=yes

[Install]
WantedBy=default.target
EOF
  chown "$RUNNER_USER:$RUNNER_USER" "$runner_home/.config/systemd/user/docker.service"
fi
runner systemctl --user daemon-reload
runner systemctl --user enable --now docker.service

attempt=1
while ! runner env "DOCKER_HOST=$docker_host" docker info >/dev/null 2>&1; do
  if [ "$attempt" -ge 20 ]; then
    runner systemctl --user status docker.service --no-pager -l || true
    runner journalctl --user -u docker.service -n 240 --no-pager -o cat 2>/dev/null \
      | grep -Ei 'level=(error|fatal)|panic|failed|permission denied|operation not permitted|invalid argument|cannot|unable' \
      | tail -80 || true
    fail rootless-docker-readiness
  fi
  attempt=$((attempt + 1))
  sleep 1
done

bridge_gateway=$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')
case "$bridge_gateway" in
  ''|*[!0-9.]*) fail docker-bridge-gateway ;;
esac

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$runner_home/runner-control/tls"
install -m 0755 "$DEPLOY_ROOT/runner/docker-dial-stdio" "$runner_home/runner-control/docker-dial-stdio"
install -m 0755 "$DEPLOY_ROOT/runner/reap-hermes-runner.sh" "$runner_home/runner-control/reap-hermes-runner.sh"
install -m 0755 "$DEPLOY_ROOT/runner/hermes_runner_control.py" "$runner_home/runner-control/hermes_runner_control.py"
chown -R "$RUNNER_USER:$RUNNER_USER" "$runner_home/runner-control"

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$runner_home/.ssh"
install -d -m 0700 "$SSH_RUNTIME" "$CONTROL_RUNTIME" "$CA_RUNTIME"
if [ ! -s "$SSH_RUNTIME/id_ed25519" ]; then
  ssh-keygen -q -t ed25519 -N '' -C hermes-single-host -f "$SSH_RUNTIME/id_ed25519"
fi
ssh-keygen -A
host_key=$(awk '{print $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub)
printf 'host.docker.internal %s\n' "$host_key" > "$SSH_RUNTIME/known_hosts"
cat > "$SSH_RUNTIME/config" <<'EOF'
Host host.docker.internal
  HostName host.docker.internal
  User hermes-runner
  IdentityFile /opt/data/.ssh/id_ed25519
  IdentitiesOnly yes
  BatchMode yes
  PasswordAuthentication no
  KbdInteractiveAuthentication no
  StrictHostKeyChecking yes
  UserKnownHostsFile /opt/data/.ssh/known_hosts
EOF
chmod 0600 "$SSH_RUNTIME/id_ed25519" "$SSH_RUNTIME/config"
chmod 0644 "$SSH_RUNTIME/id_ed25519.pub" "$SSH_RUNTIME/known_hosts"
chown -R 10000:10000 "$SSH_RUNTIME"

authorized_keys="$runner_home/.ssh/authorized_keys"
temporary_keys=$(mktemp)
if [ -f "$authorized_keys" ]; then
  grep -v 'hermes-single-host' "$authorized_keys" > "$temporary_keys" || true
fi
public_key=$(cat "$SSH_RUNTIME/id_ed25519.pub")
printf 'restrict,command="%s/runner-control/docker-dial-stdio" %s\n' \
  "$runner_home" "$public_key" >> "$temporary_keys"
install -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0600 "$temporary_keys" "$authorized_keys"
rm -f "$temporary_keys"

regenerate_tls=0
for path in "$CA_RUNTIME/ca.key" "$CA_RUNTIME/ca.crt" \
  "$runner_home/runner-control/tls/server.key" "$runner_home/runner-control/tls/server.crt" \
  "$CONTROL_RUNTIME/client.key" "$CONTROL_RUNTIME/client.crt"; do
  [ -s "$path" ] || regenerate_tls=1
done
if [ "$regenerate_tls" -eq 0 ]; then
  openssl x509 -in "$runner_home/runner-control/tls/server.crt" -noout -ext subjectAltName \
    | grep -q "DNS:host.docker.internal" || regenerate_tls=1
  openssl x509 -in "$runner_home/runner-control/tls/server.crt" -noout -ext subjectAltName \
    | grep -q "IP Address:$bridge_gateway" || regenerate_tls=1
fi

if [ "$regenerate_tls" -eq 1 ]; then
  rm -f "$CA_RUNTIME"/* "$runner_home/runner-control/tls"/* "$CONTROL_RUNTIME"/*
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$CA_RUNTIME/ca.key" >/dev/null 2>&1
  openssl req -x509 -new -sha256 -days 825 -key "$CA_RUNTIME/ca.key" \
    -subj '/CN=Hermes Single Host Runner CA' -out "$CA_RUNTIME/ca.crt"

  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -out "$runner_home/runner-control/tls/server.key" >/dev/null 2>&1
  openssl req -new -sha256 -key "$runner_home/runner-control/tls/server.key" \
    -subj '/CN=host.docker.internal' \
    -addext "subjectAltName=DNS:host.docker.internal,IP:$bridge_gateway" \
    -addext 'extendedKeyUsage=serverAuth' \
    -out "$CA_RUNTIME/server.csr"
  openssl x509 -req -sha256 -days 825 -in "$CA_RUNTIME/server.csr" \
    -CA "$CA_RUNTIME/ca.crt" -CAkey "$CA_RUNTIME/ca.key" -CAcreateserial \
    -copy_extensions copy -out "$runner_home/runner-control/tls/server.crt"

  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -out "$CONTROL_RUNTIME/client.key" >/dev/null 2>&1
  openssl req -new -sha256 -key "$CONTROL_RUNTIME/client.key" \
    -subj '/CN=hermes-platform-api' -addext 'extendedKeyUsage=clientAuth' \
    -out "$CA_RUNTIME/client.csr"
  openssl x509 -req -sha256 -days 825 -in "$CA_RUNTIME/client.csr" \
    -CA "$CA_RUNTIME/ca.crt" -CAkey "$CA_RUNTIME/ca.key" -CAcreateserial \
    -copy_extensions copy -out "$CONTROL_RUNTIME/client.crt"
fi

install -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0644 "$CA_RUNTIME/ca.crt" \
  "$runner_home/runner-control/tls/ca.crt"
chown "$RUNNER_USER:$RUNNER_USER" "$runner_home/runner-control/tls/server.key" \
  "$runner_home/runner-control/tls/server.crt"
chmod 0600 "$runner_home/runner-control/tls/server.key"
chmod 0644 "$runner_home/runner-control/tls/server.crt"
install -o 10001 -g 10001 -m 0444 "$CA_RUNTIME/ca.crt" "$CONTROL_RUNTIME/ca.crt"
chown 10001:10001 "$CONTROL_RUNTIME/client.key" "$CONTROL_RUNTIME/client.crt"
chmod 0400 "$CONTROL_RUNTIME/client.key"
chmod 0444 "$CONTROL_RUNTIME/client.crt"
chown 10001:10001 "$CONTROL_RUNTIME"
chmod 0500 "$CONTROL_RUNTIME"
chmod 0600 "$CA_RUNTIME/ca.key"

cat > /etc/hermes-runner-control.env <<EOF
RUNNER_DOCKER_HOST=$docker_host
RUNNER_CONTROL_BIND=$bridge_gateway
RUNNER_CONTROL_PORT=$CONTROL_PORT
EOF
chmod 0600 /etc/hermes-runner-control.env
install -m 0644 "$DEPLOY_ROOT/runner/hermes-runner-control-single-host.service" \
  /etc/systemd/system/hermes-runner-control.service

install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0700 "$runner_home/.config/systemd/user"
install -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0644 \
  "$DEPLOY_ROOT/runner/hermes-runner-reaper.service" \
  "$runner_home/.config/systemd/user/hermes-runner-reaper.service"
install -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0644 \
  "$DEPLOY_ROOT/runner/hermes-runner-reaper.timer" \
  "$runner_home/.config/systemd/user/hermes-runner-reaper.timer"

systemctl daemon-reload
systemctl enable --now hermes-runner-control.service
runner systemctl --user daemon-reload
runner systemctl --user enable --now hermes-runner-reaper.timer

RUNNER_CONTROL_PORT="$CONTROL_PORT" sh "$DEPLOY_ROOT/scripts/verify-single-host-runner.sh"
printf 'single-host-bootstrap=passed runner=%s gateway=%s port=%s\n' \
  "$RUNNER_USER" "$bridge_gateway" "$CONTROL_PORT"
if [ -n "$deploy_operator" ] && [ "$deploy_operator" != root ]; then
  printf 'single-host-bootstrap=notice operator=%s action="reconnect SSH before running up-single-host.sh"\n' \
    "$deploy_operator"
fi
