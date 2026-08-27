import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "deploy" / "compose.sandbox.yaml"
VERIFY_PATH = ROOT / "deploy" / "scripts" / "verify-sandbox.sh"
VERIFY_HERMES_BACKEND_PATH = ROOT / "deploy" / "scripts" / "verify-hermes-docker-backend.sh"
VERIFY_HERMES_TOOLS_PATH = ROOT / "deploy" / "scripts" / "verify-hermes-tool-runner.sh"
BOOTSTRAP_RUNNER_PATH = ROOT / "deploy" / "scripts" / "bootstrap-hermes-runner.sh"
VERIFY_RUNNER_HOST_PATH = ROOT / "deploy" / "scripts" / "verify-hermes-runner-host.sh"
HERMES_CONFIG_PATH = ROOT / "deploy" / "hermes" / "config.yaml"
RUNNER_CONFIG_PATH = ROOT / "deploy" / "hermes" / "tool-runner-config.yaml"
PRIMARY_HERMES_COMPOSE_PATH = ROOT / "deploy" / "compose.hermes.yaml"
UP_SCRIPT_PATH = ROOT / "deploy" / "scripts" / "up.sh"
UP_POWERSHELL_SCRIPT_PATH = ROOT / "deploy" / "scripts" / "up.ps1"
REFRESH_ATTESTATION_SCRIPT_PATH = ROOT / "deploy" / "scripts" / "refresh-hermes-sandbox-attestation.sh"
PREPARE_HERMES_SOURCE_SCRIPT_PATH = ROOT / "deploy" / "scripts" / "prepare-hermes-source.sh"
RUNNER_CONTROL_SERVICE_PATH = ROOT / "deploy" / "runner" / "hermes-runner-control.service"
RUNNER_REAPER_PATH = ROOT / "deploy" / "runner" / "reap-hermes-runner.sh"
RUNNER_REAPER_SERVICE_PATH = ROOT / "deploy" / "runner" / "hermes-runner-reaper.service"
RUNNER_REAPER_TIMER_PATH = ROOT / "deploy" / "runner" / "hermes-runner-reaper.timer"
RUNNER_DOCKER_DIAL_PATH = ROOT / "deploy" / "runner" / "docker-dial-stdio"
REMOTE_DOCKER_POLICY_PATH = ROOT / "deploy" / "hermes" / "platform_policy" / "sitecustomize.py"
MINIMUM_PLATFORM_TOOLSETS = (
    "platform_toolsets:\n"
    "  api_server:\n"
    "    - terminal\n"
    "    - file"
)
PRIMARY_API_TOOLSETS = ["terminal", "file", "skills", "dingtalk_documents", "web"]


def configured_api_toolsets(path: Path) -> list[str]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return config["platform_toolsets"]["api_server"]


def test_sandbox_compose_declares_fail_closed_container_policy() -> None:
    assert COMPOSE_PATH.exists(), "sandbox Compose blueprint must exist"
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "sandbox-probe-a:" in compose
    assert "sandbox-probe-b:" in compose
    assert compose.count('profiles: ["sandbox-validation"]') == 2
    assert compose.count('user: "65532:65532"') == 2
    assert compose.count("read_only: true") == 2
    assert compose.count("network_mode: none") == 2
    assert compose.count("- ALL") == 2
    assert compose.count("- no-new-privileges:true") == 2
    assert compose.count("pids_limit: 64") == 2
    assert compose.count("mem_limit: 256m") == 2
    assert compose.count('cpus: "0.50"') == 2
    assert compose.count("/workspace:rw,nosuid,nodev,noexec,size=64m") == 2
    assert compose.count("/tmp:rw,nosuid,nodev,noexec,size=16m") == 2
    assert "docker.sock" not in compose

    hermes_config = HERMES_CONFIG_PATH.read_text(encoding="utf-8")
    assert MINIMUM_PLATFORM_TOOLSETS in hermes_config
    assert configured_api_toolsets(HERMES_CONFIG_PATH) == PRIMARY_API_TOOLSETS


def test_sandbox_verifier_exercises_runtime_isolation_and_cleanup() -> None:
    assert VERIFY_PATH.exists(), "sandbox runtime verifier must exist"
    verifier = VERIFY_PATH.read_text(encoding="utf-8")

    for required_check in (
        "ReadonlyRootfs",
        "CapDrop",
        "SecurityOpt",
        "NetworkMode",
        "PidsLimit",
        "Memory",
        "NanoCpus",
        "rootfs-write=blocked",
        "workspace-write=allowed",
        "cross-workspace=blocked",
        "docker-socket=absent",
        "sandbox-gate=passed",
    ):
        assert required_check in verifier
    assert "trap cleanup EXIT" in verifier
    assert 'cd "$DEPLOY_ROOT"' in verifier


def test_tool_runner_config_enables_only_minimum_tools_and_uses_ephemeral_docker() -> None:
    assert RUNNER_CONFIG_PATH.exists(), "dedicated tool-runner config must exist"
    config = RUNNER_CONFIG_PATH.read_text(encoding="utf-8")

    for expected in (
        "backend: docker",
        "docker_forward_env: []",
        "cwd: /workspace",
        "container_cpu: 0.5",
        "container_memory: 256",
        "container_disk: 0",
        "container_persistent: false",
        "docker_volumes: []",
        "docker_mount_cwd_to_workspace: false",
        "docker_network: false",
        "docker_run_as_host_user: false",
        "- 10000:10000",
        "docker_persist_across_processes: false",
        "docker_orphan_reaper: true",
        "/workspace:rw,exec,nosuid,nodev,size=64m,uid=10000,gid=10000,mode=0700",
        MINIMUM_PLATFORM_TOOLSETS,
    ):
        assert expected in config
    assert configured_api_toolsets(RUNNER_CONFIG_PATH) == ["terminal", "file"]


def test_pinned_backend_verifier_requires_remote_strict_policy() -> None:
    assert VERIFY_HERMES_BACKEND_PATH.exists(), "pinned backend verifier must exist"
    verifier = VERIFY_HERMES_BACKEND_PATH.read_text(encoding="utf-8")

    for required_check in (
        '"--user",',
        '"10000:10000",',
        "HERMES_REMOTE_DOCKER_STRICT",
        "get_credential_file_mounts",
        "get_skills_directory_mount",
        "get_cache_directory_mounts",
        '"--cap-add" not in docker_environment._BASE_SECURITY_ARGS',
        "docker_environment._PRIVDROP_CAP_ARGS == []",
        "DockerEnvironment",
        "network=False",
        "persistent_filesystem=False",
        "persist_across_processes=False",
        "run_as_host_user=False",
        "/workspace:rw,exec,nosuid,nodev,size=64m,uid=10000,gid=10000,mode=0700",
        "cleanup(force_remove=True)",
        '"backend": "hermes-docker"',
        '"cap_add_absent"',
        'host.get("CapAdd")',
        'assert attestation["network_mode"] == "none"',
        '"sandbox-gate": "passed"',
        'test "$(id -u)" = "10000"',
        'test "${HOME:-}" = "/opt/data"',
        'test -r "$HOME/.ssh/id_ed25519"',
        "runtime-user-gate=passed",
    ):
        assert required_check in verifier

    assert "DOCKER_SOCKET" not in verifier
    assert "--volume" not in verifier

    primary_compose = PRIMARY_HERMES_COMPOSE_PATH.read_text(encoding="utf-8")
    assert "docker.sock" not in primary_compose


def test_tool_runner_verifier_exercises_real_tools_and_scope_isolation() -> None:
    assert VERIFY_HERMES_TOOLS_PATH.exists(), "tool runner verifier must exist"
    verifier = VERIFY_HERMES_TOOLS_PATH.read_text(encoding="utf-8")

    for expected in (
        "terminal_tool",
        "write_file_tool",
        "read_file_tool",
        "get_active_env",
        "cleanup_vm",
        'labels.get("hermes-task-id") == task_id',
        'config.get("User") == "10000:10000"',
        'host.get("CapAdd")',
        'host.get("NetworkMode") == "none"',
        'host.get("ReadonlyRootfs") is True',
        'host.get("Tmpfs", {}).get("/workspace")',
        "workspace_tmpfs_options == {",
        '"rw"',
        '"exec"',
        '"size=64m"',
        '"uid=10000"',
        '"gid=10000"',
        '"mode=0700"',
        '"nosuid"',
        '"nodev"',
        '"process" not in registry._tools',
        '"execute_code" not in tool_names',
        "yaml.safe_load",
        'configured_toolsets == ["terminal", "file"]',
        "model_tools.get_tool_definitions(configured_toolsets",
        'terminal_properties == {"command", "pty", "timeout", "workdir"}',
        "cross-workspace=blocked",
        "hermes-tool-runner-gate=passed",
    ):
        assert expected in verifier


def test_primary_services_use_private_runner_transports_without_a_socket_mount() -> None:
    compose = PRIMARY_HERMES_COMPOSE_PATH.read_text(encoding="utf-8")
    hermes_config = HERMES_CONFIG_PATH.read_text(encoding="utf-8")

    for expected in (
        "DOCKER_HOST: ssh://hermes-runner@192.168.3.107",
        "./.runtime/hermes-runner-ssh:/opt/data/.ssh:ro",
        'HERMES_REMOTE_DOCKER_STRICT: "1"',
        "HERMES_WRITE_SAFE_ROOT: /opt/data:/workspace",
        "./hermes/platform_policy:/opt/platform-policy:ro",
        'SANDBOX_RUNNER_ENABLED: "true"',
        'HERMES_HTTP_TIMEOUT_SECONDS: "120"',
        'SANDBOX_MAX_ACTIVE_RUNS_GLOBAL: "8"',
        'SANDBOX_MAX_ACTIVE_RUNS_PER_ORGANIZATION: "4"',
        'SANDBOX_MAX_ACTIVE_RUNS_PER_USER: "2"',
        "SANDBOX_RUNNER_URL: https://192.168.3.107:9443",
        "./.runtime/hermes-runner-control:/run/hermes-runner-control:ro",
    ):
        assert expected in compose
    assert "DOCKER_SSH_COMMAND" not in compose
    assert "docker.sock" not in compose

    policy = REMOTE_DOCKER_POLICY_PATH.read_text(encoding="utf-8")
    assert "HERMES_REMOTE_DOCKER_STRICT" in policy
    assert "_BASE_SECURITY_ARGS" in policy
    assert "_PRIVDROP_CAP_ARGS" in policy
    assert "get_credential_file_mounts" in policy
    assert "get_skills_directory_mount" in policy
    assert "get_cache_directory_mounts" in policy
    assert "_resolve_container_task_id" in policy

    for expected in (
        "backend: docker",
        "docker_forward_env: []",
        "cwd: /workspace",
        "container_disk: 0",
        "container_persistent: false",
        "docker_mount_cwd_to_workspace: false",
        "docker_network: false",
        "docker_run_as_host_user: false",
        "docker_persist_across_processes: false",
        MINIMUM_PLATFORM_TOOLSETS,
    ):
        assert expected in hermes_config
    assert configured_api_toolsets(HERMES_CONFIG_PATH) == PRIMARY_API_TOOLSETS


def test_hermes_build_context_requires_tag_and_peeled_commit_checksum() -> None:
    compose = PRIMARY_HERMES_COMPOSE_PATH.read_text(encoding="utf-8")

    assert "context: ./.runtime/hermes-source" in compose
    assert "dockerfile: Dockerfile" in compose
    assert PREPARE_HERMES_SOURCE_SCRIPT_PATH.exists()
    prepare = PREPARE_HERMES_SOURCE_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "https://codeload.github.com/NousResearch/hermes-agent/tar.gz/" in prepare
    assert "9de9c25f620ff7f1ce0fd5457d596052d5159596" in prepare
    assert "--strip-components=1" in prepare


def test_api_startup_requires_a_fresh_sandbox_attestation() -> None:
    compose = PRIMARY_HERMES_COMPOSE_PATH.read_text(encoding="utf-8")

    assert "SANDBOX_ATTESTATION_FILE: /run/hermes-sandbox/attestation.json" in compose
    assert "./.runtime/sandbox-attestation.json:/run/hermes-sandbox/attestation.json:ro" in compose
    assert "validate_sandbox_attestation.py < \"$${SANDBOX_ATTESTATION_FILE}\"" in compose


def test_hermes_startup_refreshes_attestation_before_api_startup() -> None:
    assert REFRESH_ATTESTATION_SCRIPT_PATH.exists()
    refresh = REFRESH_ATTESTATION_SCRIPT_PATH.read_text(encoding="utf-8")
    shell_up = UP_SCRIPT_PATH.read_text(encoding="utf-8")
    powershell_up = UP_POWERSHELL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "verify-hermes-docker-backend.sh" in refresh
    assert "validate_sandbox_attestation.py" in refresh
    assert "sandbox-attestation.json" in refresh
    assert "verifier_output=$(mktemp" in refresh
    assert "if ! sh -c \"$compose exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-docker-backend.sh\"" in refresh
    assert "> \"$verifier_output\"; then" in refresh
    assert "sed -n '/^{/p' \"$verifier_output\"" in refresh
    assert "mv \"$temporary_attestation\" \"$attestation_path\"" in refresh
    assert "refresh-hermes-sandbox-attestation.sh" in shell_up
    assert "Refresh-HermesSandboxAttestation" in powershell_up
    assert "prepare-hermes-source.sh" in shell_up
    assert "Prepare-HermesSource" in powershell_up


def test_remote_policy_preserves_per_session_container_identity() -> None:
    spec = importlib.util.spec_from_file_location(
        "hermes_remote_policy", REMOTE_DOCKER_POLICY_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._isolated_task_id("session-a") == "session-a"
    assert module._isolated_task_id("session-b") == "session-b"
    with pytest.raises(RuntimeError, match="task id"):
        module._isolated_task_id(None)
    with pytest.raises(RuntimeError, match="task id"):
        module._isolated_task_id("")


def test_remote_policy_exposes_foreground_terminal_only() -> None:
    spec = importlib.util.spec_from_file_location(
        "hermes_remote_policy", REMOTE_DOCKER_POLICY_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    schema = {
        "name": "terminal",
        "description": "Use process(action='poll') after background=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
                "background": {"type": "boolean"},
                "notify_on_complete": {"type": "boolean"},
                "watch_patterns": {"type": "array"},
            },
            "required": ["command"],
        },
    }

    restricted = module._foreground_terminal_schema(schema)

    assert restricted["description"] == module.FOREGROUND_TERMINAL_DESCRIPTION
    assert set(restricted["parameters"]["properties"]) == {"command", "timeout"}
    assert "process" not in restricted["description"]
    assert "background" in schema["parameters"]["properties"]

    policy = REMOTE_DOCKER_POLICY_PATH.read_text(encoding="utf-8")
    assert 'registry.deregister("process")' in policy
    assert 'if name == "process"' in policy
    assert "background terminal execution is disabled" in policy


def test_runner_bootstrap_installs_only_a_private_rootless_daemon() -> None:
    assert BOOTSTRAP_RUNNER_PATH.exists(), "dedicated runner bootstrap must exist"
    bootstrap = BOOTSTRAP_RUNNER_PATH.read_text(encoding="utf-8")

    for expected in (
        "Ubuntu 24.04",
        "uidmap",
        "slirp4netns",
        "fuse-overlayfs",
        "useradd --create-home",
        "usermod --lock",
        "loginctl enable-linger",
        "dockerd-rootless-setuptool.sh install",
        "systemctl mask docker.service docker.socket containerd.service",
        "DOCKER_HOST=unix:///run/user/",
        '"group": "$RUNNER_USER"',
        'grep -q "name=rootless"',
        'test ! -S /var/run/docker.sock',
        "runner-bootstrap=passed",
    ):
        assert expected in bootstrap

    assert "XIAOMI_API_KEY" not in bootstrap
    assert "HERMES_API_KEY" not in bootstrap


def test_runner_host_verifier_checks_rootless_boundary() -> None:
    assert VERIFY_RUNNER_HOST_PATH.exists(), "runner host verifier must exist"
    verifier = VERIFY_RUNNER_HOST_PATH.read_text(encoding="utf-8")

    for expected in (
        "test ! -S /var/run/docker.sock",
        "systemctl is-enabled docker.socket",
        "systemctl is-enabled docker.service",
        "systemctl is-enabled containerd.service",
        "DOCKER_HOST=unix:///run/user/",
        'grep -q "name=rootless"',
        "cgroup.controllers",
        "runner_sudo=absent",
        "docker_tcp=absent",
        "runner-host-gate=passed",
    ):
        assert expected in verifier

    assert "XIAOMI_API_KEY" not in verifier
    assert "HERMES_API_KEY" not in verifier


def test_runner_control_units_are_unprivileged_and_label_scoped() -> None:
    control = RUNNER_CONTROL_SERVICE_PATH.read_text(encoding="utf-8")
    reaper = RUNNER_REAPER_PATH.read_text(encoding="utf-8")
    reaper_service = RUNNER_REAPER_SERVICE_PATH.read_text(encoding="utf-8")
    reaper_timer = RUNNER_REAPER_TIMER_PATH.read_text(encoding="utf-8")

    for unit in (control, reaper_service):
        assert "User=hermes-runner" in unit
        assert "NoNewPrivileges=true" in unit
        assert "/run/user/1001" not in unit
    assert "ProtectSystem=strict" in control
    assert "--client-ca" in control
    assert "$(id -u)" in control
    assert "DOCKER_HOST=" in control
    assert "label=hermes-task-id" in reaper
    assert "docker system prune" not in reaper
    assert "docker container prune" not in reaper
    assert "OnUnitActiveSec=5min" in reaper_timer
    assert 'RUNNER_UID=$(id -u)' in reaper
    assert 'DOCKER_HOST="unix:///run/user/$RUNNER_UID/docker.sock"' in reaper


def test_runner_ssh_wrapper_allows_only_docker_dial_stdio() -> None:
    wrapper = RUNNER_DOCKER_DIAL_PATH.read_text(encoding="utf-8")

    assert "SSH_ORIGINAL_COMMAND" in wrapper
    assert '"docker system dial-stdio"' in wrapper
    assert "exec /usr/bin/docker system dial-stdio" in wrapper
    assert 'RUNNER_UID=$(id -u)' in wrapper
    assert 'DOCKER_HOST="unix:///run/user/$RUNNER_UID/docker.sock"' in wrapper
    assert "/run/user/1001" not in wrapper
    assert "eval" not in wrapper
