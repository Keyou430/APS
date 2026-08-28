#!/usr/bin/env sh
set -eu

RUNNER_USER=hermes-runner
CONTROL_PORT=${RUNNER_CONTROL_PORT:-9443}
DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SSH_RUNTIME="$DEPLOY_ROOT/.runtime/hermes-runner-ssh"
CONTROL_RUNTIME="$DEPLOY_ROOT/.runtime/hermes-runner-control"

fail() {
  echo "single-host-runner-gate=failed check=$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || fail root-required
systemctl is-active --quiet docker.service || fail standard-docker-inactive
test -S /var/run/docker.sock || fail standard-docker-socket
docker info >/dev/null 2>&1 || fail standard-docker-readiness

runner_uid=$(id -u "$RUNNER_USER")
runner_home=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
runner_runtime="/run/user/$runner_uid"
docker_host="unix://$runner_runtime/docker.sock"
runner() {
  runuser -u "$RUNNER_USER" -- env \
    HOME="$runner_home" USER="$RUNNER_USER" LOGNAME="$RUNNER_USER" \
    XDG_RUNTIME_DIR="$runner_runtime" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$runner_runtime/bus" \
    PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx sudo && fail runner-has-sudo
test -S "$runner_runtime/docker.sock" || fail rootless-docker-socket
runner env "DOCKER_HOST=$docker_host" docker info --format '{{json .SecurityOptions}}' \
  | grep -q 'name=rootless' || fail rootless-security

bridge_gateway=$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')
systemctl is-active --quiet hermes-runner-control.service || fail control-service-inactive
ss -lnt | awk -v endpoint="$bridge_gateway:$CONTROL_PORT" '$4 == endpoint { found = 1 } END { exit !found }' \
  || fail control-bind
if ss -lnt | awk -v port=":$CONTROL_PORT" '$4 ~ "0.0.0.0" port || $4 ~ "\\[::\\]" port { found = 1 } END { exit !found }'; then
  fail control-public-bind
fi

for path in "$SSH_RUNTIME/id_ed25519" "$SSH_RUNTIME/known_hosts" "$SSH_RUNTIME/config" \
  "$CONTROL_RUNTIME/ca.crt" "$CONTROL_RUNTIME/client.crt" "$CONTROL_RUNTIME/client.key"; do
  test -s "$path" || fail runtime-material
done

curl --fail --silent --show-error \
  --resolve "host.docker.internal:$CONTROL_PORT:$bridge_gateway" \
  --cacert "$CONTROL_RUNTIME/ca.crt" \
  --cert "$CONTROL_RUNTIME/client.crt" \
  --key "$CONTROL_RUNTIME/client.key" \
  "https://host.docker.internal:$CONTROL_PORT/health" \
  | grep -q '"status":"ok"' || fail control-mtls-health

temporary_config=$(mktemp)
trap 'rm -f "$temporary_config"' EXIT
sed 's/HostName host.docker.internal/HostName 127.0.0.1/' "$SSH_RUNTIME/config" \
  | sed 's#IdentityFile /opt/data/.ssh/id_ed25519#IdentityFile '"$SSH_RUNTIME/id_ed25519"'#' \
  | sed 's#UserKnownHostsFile /opt/data/.ssh/known_hosts#UserKnownHostsFile '"$SSH_RUNTIME/known_hosts"'#' \
  > "$temporary_config"
if timeout 4 sh -c "sleep 10 | ssh -F '$temporary_config' -o HostKeyAlias=host.docker.internal host.docker.internal docker system dial-stdio" \
  >/dev/null 2>&1; then
  fail ssh-dial-exited-unexpectedly
else
  status=$?
  [ "$status" -eq 124 ] || fail ssh-dial
fi

printf 'single-host-runner-gate=passed gateway=%s port=%s\n' "$bridge_gateway" "$CONTROL_PORT"
