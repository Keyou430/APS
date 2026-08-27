#!/usr/bin/env sh
set -eu

[ "${HERMES_REMOTE_DOCKER_STRICT:-}" = "1" ] || {
  echo "hermes-tool-runner-gate=failed check=remote-strict-policy-disabled" >&2
  exit 1
}
test "$(id -u)" = "10000"
test "${HOME:-}" = "/opt/data"
test -r "$HOME/.ssh/id_ed25519"
test -r "$HOME/.ssh/known_hosts"
echo "runtime-user-gate=passed"

python - <<'PY'
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import gateway.run  # Applies the live gateway config-to-environment bridge.
import model_tools
import yaml
from tools.file_tools import clear_file_ops_cache, read_file_tool, write_file_tool
from tools.registry import registry
from tools.terminal_tool import cleanup_vm, get_active_env, terminal_tool


with (Path.home() / "config.yaml").open(encoding="utf-8") as config_file:
    configured_toolsets = yaml.safe_load(config_file)["platform_toolsets"]["api_server"]
assert configured_toolsets == ["terminal", "file"]
definitions = model_tools.get_tool_definitions(configured_toolsets, quiet_mode=True)
tool_names = {item["function"]["name"] for item in definitions}
assert tool_names == {"patch", "read_file", "search_files", "terminal", "write_file"}
assert "process" not in registry._tools
assert "execute_code" not in tool_names
terminal_definition = next(
    item["function"] for item in definitions if item["function"]["name"] == "terminal"
)
terminal_properties = set(terminal_definition["parameters"]["properties"])
assert terminal_properties == {"command", "pty", "timeout", "workdir"}

tasks = [f"tool-scope-a-{uuid4().hex}", f"tool-scope-b-{uuid4().hex}"]
environments = []

try:
    for index, task_id in enumerate(tasks):
        terminal_result = json.loads(terminal_tool(command="id -u", task_id=task_id))
        assert terminal_result.get("exit_code") == 0
        assert terminal_result.get("output", "").strip() == "10000"

        marker = f"SCOPE_{index}"
        write_result = json.loads(write_file_tool("scope.txt", marker, task_id=task_id))
        assert not write_result.get("error")
        assert marker in read_file_tool("scope.txt", task_id=task_id)

        environment = get_active_env(task_id)
        assert environment is not None
        assert environment.__class__.__name__ == "DockerEnvironment"
        environments.append(environment)

        inspect = json.loads(
            subprocess.check_output(
                ["docker", "inspect", environment._container_id], text=True
            )
        )[0]
        host = inspect["HostConfig"]
        config = inspect["Config"]
        labels = config.get("Labels") or {}
        workspace_tmpfs = host.get("Tmpfs", {}).get("/workspace") or ""
        assert labels.get("hermes-task-id") == task_id
        assert config.get("User") == "10000:10000"
        assert not (host.get("CapAdd") or [])
        assert "ALL" in (host.get("CapDrop") or [])
        assert inspect.get("Mounts", []) == []
        assert host.get("NetworkMode") == "none"
        assert host.get("ReadonlyRootfs") is True
        assert host.get("Memory") == 268435456
        assert host.get("NanoCpus") == 500000000
        assert host.get("PidsLimit") == 256
        workspace_tmpfs_options = set(filter(None, workspace_tmpfs.split(",")))
        assert workspace_tmpfs_options == {
            "rw",
            "exec",
            "nosuid",
            "nodev",
            "size=64m",
            "uid=10000",
            "gid=10000",
            "mode=0700",
        }

    assert environments[0]._container_id != environments[1]._container_id
    first = read_file_tool("scope.txt", task_id=tasks[0])
    second = read_file_tool("scope.txt", task_id=tasks[1])
    assert "SCOPE_0" in first and "SCOPE_1" not in first
    assert "SCOPE_1" in second and "SCOPE_0" not in second
    print("terminal-gate=passed file-gate=passed cross-workspace=blocked")
finally:
    for task_id in tasks:
        environment = get_active_env(task_id)
        clear_file_ops_cache(task_id)
        cleanup_vm(task_id, force_remove=True)
        if environment is not None and hasattr(environment, "wait_for_cleanup"):
            if not environment.wait_for_cleanup(timeout=30):
                raise RuntimeError("tool environment cleanup timed out")
        remaining = subprocess.check_output(
            ["docker", "ps", "-aq", "--filter", f"label=hermes-task-id={task_id}"],
            text=True,
        ).strip()
        if remaining:
            raise RuntimeError("tool environment cleanup left a container")

print("hermes-tool-runner-gate=passed cleanup=passed")
PY
