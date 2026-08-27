import importlib
import importlib.util
from pathlib import Path

import pytest


SAFE_ATTESTATION = {
    "backend": "hermes-docker",
    "cap_drop_all": True,
    "cap_add_absent": True,
    "docker_socket_absent": True,
    "memory_bytes": 268435456,
    "nano_cpus": 500000000,
    "network_egress_blocked": True,
    "network_mode": "none",
    "no_new_privileges": True,
    "pids_limit": 256,
    "readonly_rootfs": True,
    "rootfs_write_blocked": True,
    "running_as_uid": "10000",
    "sandbox-gate": "passed",
    "sensitive_env_absent": True,
    "workspace_write_allowed": True,
}


def load_attestation_module():
    spec = importlib.util.find_spec("app.services.sandbox_attestation")
    if spec is None:
        pytest.fail("platform sandbox attestation validator must exist", pytrace=False)
    return importlib.import_module("app.services.sandbox_attestation")


def test_safe_sandbox_attestation_is_admitted() -> None:
    attestation_module = load_attestation_module()
    admitted = attestation_module.validate_sandbox_attestation(SAFE_ATTESTATION)

    assert admitted.backend == "hermes-docker"
    assert admitted.running_as_uid == 10000


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("backend", "local"),
        ("cap_drop_all", False),
        ("cap_add_absent", False),
        ("docker_socket_absent", False),
        ("memory_bytes", 268435457),
        ("nano_cpus", 500000001),
        ("network_egress_blocked", False),
        ("network_mode", "bridge"),
        ("no_new_privileges", False),
        ("pids_limit", 257),
        ("readonly_rootfs", False),
        ("rootfs_write_blocked", False),
        ("running_as_uid", "0"),
        ("sandbox-gate", "failed"),
        ("sensitive_env_absent", False),
        ("workspace_write_allowed", False),
    ],
)
def test_unsafe_sandbox_attestation_is_rejected(
    field: str, unsafe_value: object
) -> None:
    attestation_module = load_attestation_module()
    payload = dict(SAFE_ATTESTATION)
    payload[field] = unsafe_value

    with pytest.raises(attestation_module.SandboxAdmissionError):
        attestation_module.validate_sandbox_attestation(payload)


def test_incomplete_or_loosely_typed_attestation_is_rejected() -> None:
    attestation_module = load_attestation_module()
    missing = dict(SAFE_ATTESTATION)
    missing.pop("network_mode")
    loosely_typed = dict(SAFE_ATTESTATION, pids_limit="256")

    with pytest.raises(attestation_module.SandboxAdmissionError):
        attestation_module.validate_sandbox_attestation(missing)
    with pytest.raises(attestation_module.SandboxAdmissionError):
        attestation_module.validate_sandbox_attestation(loosely_typed)


def test_attestation_cli_is_fail_closed() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_sandbox_attestation.py"
    assert script.exists(), "sandbox attestation validation CLI must exist"
    source = script.read_text(encoding="utf-8")

    assert "validate_sandbox_attestation" in source
    assert '"sandbox-admission": "passed"' in source
    assert "json.load(sys.stdin)" in source
