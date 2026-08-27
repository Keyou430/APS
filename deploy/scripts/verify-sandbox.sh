#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PROJECT_NAME=hermes-sandbox-verify
cd "$DEPLOY_ROOT"

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --file "$DEPLOY_ROOT/compose.sandbox.yaml" \
    --profile sandbox-validation \
    "$@"
}

cleanup() {
  compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "sandbox-gate=failed check=$1" >&2
  exit 1
}

assert_equal() {
  actual=$1
  expected=$2
  check=$3
  [ "$actual" = "$expected" ] || fail "$check"
}

compose up -d --wait --wait-timeout 60

container_a=$(compose ps --quiet sandbox-probe-a)
container_b=$(compose ps --quiet sandbox-probe-b)
[ -n "$container_a" ] || fail container-a-running
[ -n "$container_b" ] || fail container-b-running

for container in "$container_a" "$container_b"; do
  assert_equal "$(docker inspect --format '{{.Config.User}}' "$container")" "65532:65532" user-non-root
  assert_equal "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$container")" "true" ReadonlyRootfs
  assert_equal "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$container")" "none" NetworkMode
  assert_equal "$(docker inspect --format '{{.HostConfig.PidsLimit}}' "$container")" "64" PidsLimit
  assert_equal "$(docker inspect --format '{{.HostConfig.Memory}}' "$container")" "268435456" Memory
  assert_equal "$(docker inspect --format '{{.HostConfig.NanoCpus}}' "$container")" "500000000" NanoCpus

  cap_drop=$(docker inspect --format '{{json .HostConfig.CapDrop}}' "$container")
  case "$cap_drop" in *ALL*) ;; *) fail CapDrop ;; esac
  security_opt=$(docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$container")
  case "$security_opt" in *no-new-privileges*) ;; *) fail SecurityOpt ;; esac
  tmpfs=$(docker inspect --format '{{json .HostConfig.Tmpfs}}' "$container")
  case "$tmpfs" in *'/workspace'*) ;; *) fail workspace-tmpfs ;; esac
  case "$tmpfs" in *'/tmp'*) ;; *) fail temporary-tmpfs ;; esac

  mounts=$(docker inspect --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' "$container")
  case "$mounts" in *docker.sock*) fail docker-socket ;; esac
done
echo "docker-socket=absent"

if docker exec "$container_a" sh -c 'touch /sandbox-root-write-probe' >/dev/null 2>&1; then
  fail rootfs-write
fi
echo "rootfs-write=blocked"

docker exec "$container_a" sh -c 'printf sandbox-a > /workspace/marker && test -s /workspace/marker'
echo "workspace-write=allowed"

docker exec "$container_b" sh -c 'test ! -e /workspace/marker'
echo "cross-workspace=blocked"

if docker exec "$container_a" python -c \
  'import socket; socket.create_connection(("1.1.1.1", 53), timeout=1)' \
  >/dev/null 2>&1; then
  fail network-egress
fi
echo "network-egress=blocked"

echo "sandbox-gate=passed"
