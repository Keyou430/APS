from dataclasses import dataclass
from typing import Any, Mapping


MAX_MEMORY_BYTES = 256 * 1024 * 1024
MAX_NANO_CPUS = 500_000_000
MAX_PIDS = 256
REQUIRED_UID = 10000


class SandboxAdmissionError(ValueError):
    """Raised when a runner attestation does not satisfy the platform policy."""


@dataclass(frozen=True)
class SandboxAttestation:
    backend: str
    cap_add_absent: bool
    cap_drop_all: bool
    docker_socket_absent: bool
    memory_bytes: int
    nano_cpus: int
    network_egress_blocked: bool
    network_mode: str
    no_new_privileges: bool
    pids_limit: int
    readonly_rootfs: bool
    rootfs_write_blocked: bool
    running_as_uid: int
    sensitive_env_absent: bool
    workspace_write_allowed: bool


def _require_true(payload: Mapping[str, Any], field: str) -> bool:
    if type(payload.get(field)) is not bool or payload[field] is not True:
        raise SandboxAdmissionError(f"Sandbox attestation rejected field: {field}")
    return True


def _require_bounded_int(
    payload: Mapping[str, Any], field: str, *, maximum: int
) -> int:
    value = payload.get(field)
    if type(value) is not int or value <= 0 or value > maximum:
        raise SandboxAdmissionError(f"Sandbox attestation rejected field: {field}")
    return value


def validate_sandbox_attestation(payload: Mapping[str, Any]) -> SandboxAttestation:
    if not isinstance(payload, Mapping):
        raise SandboxAdmissionError("Sandbox attestation must be an object")

    if payload.get("backend") != "hermes-docker":
        raise SandboxAdmissionError("Sandbox attestation rejected field: backend")
    if payload.get("network_mode") != "none":
        raise SandboxAdmissionError("Sandbox attestation rejected field: network_mode")
    if payload.get("sandbox-gate") != "passed":
        raise SandboxAdmissionError("Sandbox attestation rejected field: sandbox-gate")

    raw_uid = payload.get("running_as_uid")
    if not isinstance(raw_uid, str) or not raw_uid.isdigit():
        raise SandboxAdmissionError("Sandbox attestation rejected field: running_as_uid")
    running_as_uid = int(raw_uid)
    if running_as_uid != REQUIRED_UID:
        raise SandboxAdmissionError("Sandbox attestation rejected field: running_as_uid")

    return SandboxAttestation(
        backend="hermes-docker",
        cap_add_absent=_require_true(payload, "cap_add_absent"),
        cap_drop_all=_require_true(payload, "cap_drop_all"),
        docker_socket_absent=_require_true(payload, "docker_socket_absent"),
        memory_bytes=_require_bounded_int(
            payload, "memory_bytes", maximum=MAX_MEMORY_BYTES
        ),
        nano_cpus=_require_bounded_int(payload, "nano_cpus", maximum=MAX_NANO_CPUS),
        network_egress_blocked=_require_true(payload, "network_egress_blocked"),
        network_mode="none",
        no_new_privileges=_require_true(payload, "no_new_privileges"),
        pids_limit=_require_bounded_int(payload, "pids_limit", maximum=MAX_PIDS),
        readonly_rootfs=_require_true(payload, "readonly_rootfs"),
        rootfs_write_blocked=_require_true(payload, "rootfs_write_blocked"),
        running_as_uid=running_as_uid,
        sensitive_env_absent=_require_true(payload, "sensitive_env_absent"),
        workspace_write_allowed=_require_true(payload, "workspace_write_allowed"),
    )
