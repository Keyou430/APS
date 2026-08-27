#!/usr/bin/env sh
set -eu

SANDBOX_IMAGE=${HERMES_SANDBOX_IMAGE:-python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de}
TASK_ID="platform-sandbox-probe-$(date +%s)-$$"

[ "${HERMES_REMOTE_DOCKER_STRICT:-}" = "1" ] || {
  echo "sandbox-gate=failed check=remote-strict-policy-disabled" >&2
  exit 1
}
[ -n "${DOCKER_HOST:-}" ] || {
  echo "sandbox-gate=failed check=remote-docker-host-unavailable" >&2
  exit 1
}
test "$(id -u)" = "10000"
test "${HOME:-}" = "/opt/data"
test -r "$HOME/.ssh/id_ed25519"
test -r "$HOME/.ssh/known_hosts"
echo "runtime-user-gate=passed"

cleanup() {
  containers=$(docker ps -aq --filter "label=hermes-task-id=$TASK_ID")
  if [ -n "$containers" ]; then
    docker rm -f $containers >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

python - "$TASK_ID" "$SANDBOX_IMAGE" <<'PY'
import json
import subprocess
import sys

from tools import credential_files
from tools.environments import docker as docker_environment
from tools.environments.docker import DockerEnvironment


task_id, image = sys.argv[1:]

assert credential_files.get_credential_file_mounts() == []
assert credential_files.get_skills_directory_mount() == []
assert credential_files.get_cache_directory_mounts() == []
assert "--cap-add" not in docker_environment._BASE_SECURITY_ARGS
assert docker_environment._PRIVDROP_CAP_ARGS == []

environment = DockerEnvironment(
    image=image,
    cwd="/workspace",
    timeout=10,
    cpu=0.5,
    memory=256,
    disk=0,
    persistent_filesystem=False,
    task_id=task_id,
    volumes=[],
    forward_env=[],
    env={},
    network=False,
    host_cwd=None,
    auto_mount_cwd=False,
    run_as_host_user=False,
    extra_args=[
        "--user",
        "10000:10000",
        "--read-only",
        "--tmpfs",
        "/workspace:rw,exec,nosuid,nodev,size=64m,uid=10000,gid=10000,mode=0700",
    ],
    persist_across_processes=False,
)

try:
    container_id = environment._container_id
    if not container_id:
        raise AssertionError("Hermes Docker backend did not create a container")

    inspect = json.loads(
        subprocess.check_output(["docker", "inspect", container_id], text=True)
    )[0]
    host = inspect["HostConfig"]
    config = inspect["Config"]

    uid = environment.execute("id -u")
    workspace = environment.execute("printf probe > /workspace/marker && test -s /workspace/marker")
    rootfs = environment.execute("touch /sandbox-root-write-probe")
    network = environment.execute(
        "python -c 'import socket; socket.create_connection((\"1.1.1.1\", 53), 1)'"
    )
    visible_env = environment.execute("env")

    sensitive_names = (
        "XIAOMI_API_KEY=",
        "HERMES_API_KEY=",
        "HERMES_API_SERVER_KEY=",
        "JWT_SECRET_KEY=",
    )
    mounts = inspect.get("Mounts", [])
    attestation = {
        "backend": "hermes-docker",
        "cap_add_absent": not (host.get("CapAdd") or []),
        "cap_drop_all": "ALL" in (host.get("CapDrop") or []),
        "docker_socket_absent": all(
            mount.get("Destination") != "/var/run/docker.sock" for mount in mounts
        ),
        "memory_bytes": host.get("Memory"),
        "nano_cpus": host.get("NanoCpus"),
        "network_mode": host.get("NetworkMode"),
        "no_new_privileges": any(
            "no-new-privileges" in option for option in (host.get("SecurityOpt") or [])
        ),
        "pids_limit": host.get("PidsLimit"),
        "rootfs_write_blocked": rootfs.get("returncode") != 0,
        "running_as_uid": uid.get("output", "").strip(),
        "sensitive_env_absent": all(
            name not in visible_env.get("output", "") for name in sensitive_names
        ),
        "workspace_write_allowed": workspace.get("returncode") == 0,
        "network_egress_blocked": network.get("returncode") != 0,
        "readonly_rootfs": host.get("ReadonlyRootfs"),
        "sandbox-gate": "passed",
    }

    assert config.get("User") == "10000:10000"
    assert mounts == []
    assert attestation["cap_add_absent"]
    assert attestation["cap_drop_all"]
    assert attestation["docker_socket_absent"]
    assert attestation["memory_bytes"] == 268435456
    assert attestation["nano_cpus"] == 500000000
    assert attestation["network_mode"] == "none"
    assert attestation["no_new_privileges"]
    assert attestation["pids_limit"] == 256
    assert attestation["readonly_rootfs"] is True
    assert attestation["rootfs_write_blocked"]
    assert attestation["running_as_uid"] == "10000"
    assert attestation["sensitive_env_absent"]
    assert attestation["workspace_write_allowed"]
    assert attestation["network_egress_blocked"]
    print(json.dumps(attestation, sort_keys=True))
finally:
    environment.cleanup(force_remove=True)
    if not environment.wait_for_cleanup(timeout=30):
        raise RuntimeError("Hermes Docker backend cleanup timed out")
PY

if docker ps -aq --filter "label=hermes-task-id=$TASK_ID" | grep -q .; then
  echo "sandbox-gate=failed check=container-cleanup" >&2
  exit 1
fi

echo "hermes-backend-cleanup=passed"
