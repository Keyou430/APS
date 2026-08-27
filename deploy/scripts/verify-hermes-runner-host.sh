#!/usr/bin/env sh
set -eu

RUNNER_USER=${RUNNER_USER:-hermes-runner}

fail() {
  echo "runner-host-gate=failed check=$1" >&2
  exit 1
}

assert_equal() {
  actual=$1
  expected=$2
  check=$3
  [ "$actual" = "$expected" ] || fail "$check"
}

[ "$(id -u)" -eq 0 ] || fail root-required
runner_uid=$(id -u "$RUNNER_USER")
runner_home=$(getent passwd "$RUNNER_USER" | cut -d: -f6)
runner_runtime="/run/user/$runner_uid"
docker_host="unix:///run/user/$runner_uid/docker.sock"

if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx sudo; then
  fail runner-has-sudo
fi
echo "runner_sudo=absent"

awk -F: -v user="$RUNNER_USER" '$1 == user && $3 >= 65536 { found = 1 } END { exit !found }' /etc/subuid \
  || fail subuid-range
awk -F: -v user="$RUNNER_USER" '$1 == user && $3 >= 65536 { found = 1 } END { exit !found }' /etc/subgid \
  || fail subgid-range

assert_equal "$(systemctl is-enabled docker.socket 2>/dev/null || true)" masked rootful-socket-not-masked
assert_equal "$(systemctl is-enabled docker.service 2>/dev/null || true)" masked rootful-service-not-masked
assert_equal "$(systemctl is-enabled containerd.service 2>/dev/null || true)" masked rootful-containerd-not-masked
test ! -S /var/run/docker.sock || fail rootful-socket-present
echo "rootful_docker=absent"

assert_equal "$(stat -c %a "$runner_runtime")" 700 runner-runtime-mode
test -S "$runner_runtime/docker.sock" || fail rootless-socket-absent
assert_equal "$(stat -c %U "$runner_runtime/docker.sock")" "$RUNNER_USER" rootless-socket-owner

runner() {
  runuser -u "$RUNNER_USER" -- env \
    HOME="$runner_home" \
    USER="$RUNNER_USER" \
    LOGNAME="$RUNNER_USER" \
    XDG_RUNTIME_DIR="$runner_runtime" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$runner_runtime/bus" \
    PATH=/usr/local/bin:/usr/bin:/bin \
    "DOCKER_HOST=unix:///run/user/$runner_uid/docker.sock" \
    "$@"
}

runner docker info --format '{{json .SecurityOptions}}' | grep -q "name=rootless" \
  || fail daemon-not-rootless
docker_root=$(runner docker info --format '{{.DockerRootDir}}')
case "$docker_root" in
  "$runner_home"/*) ;;
  *) fail docker-root-outside-runner-home ;;
esac

controllers_path="/sys/fs/cgroup/user.slice/user-$runner_uid.slice/user@$runner_uid.service/cgroup.controllers"
controllers=$(cat "$controllers_path")
for controller in cpu memory pids; do
  echo "$controllers" | tr ' ' '\n' | grep -qx "$controller" \
    || fail "cgroup-$controller-not-delegated"
done

if ss -lnt 2>/dev/null | grep -Eq ':(2375|2376)[[:space:]]'; then
  fail docker-tcp-listener
fi
echo "docker_tcp=absent"

printf 'runner-host-gate=passed user=%s uid=%s docker_host=%s\n' \
  "$RUNNER_USER" "$runner_uid" "$docker_host"
