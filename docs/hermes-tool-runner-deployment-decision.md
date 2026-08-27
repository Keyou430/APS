# Hermes Tool Runner Deployment Decision

## Decision Boundary

The pinned Hermes `v0.18.2` Docker backend can create a hardened per-task container, but the
`/v1/runs` completion, failure, and stop paths do not call `agent.close()` or
`cleanup_vm(force_remove=True)`. They remove the in-process run references and rely on inactivity
or orphan reaping. That is not a guaranteed per-run cleanup contract.

The primary platform API and Hermes services must remain free of Docker socket mounts. A separate
runner/control boundary must own Docker access, create the upstream sandbox, and force cleanup for
every completion, denial, cancellation, timeout, or process failure.

## Original Host Evidence

The private deployment host currently reports:

- Docker is rootful with AppArmor, seccomp, cgroup v2, and overlay2.
- `dockerd-rootless-setuptool.sh`, `rootlesskit`, and `slirp4netns` are installed.
- `newuidmap` and `newgidmap` are missing.
- User namespaces are enabled.
- No `hermes-runner` operating-system user exists.
- `/var/run/docker.sock` is root-owned and group-restricted.

No host configuration was changed while collecting this evidence.

## Selected Deployment: Dedicated Runner VM

The selected boundary is a separate Ubuntu 24.04 KVM VM at private address
`192.168.3.107`, not an LXC container and not the shared platform host. It runs a locked,
non-sudo `hermes-runner` account with a rootless Docker daemon. The rootful Docker service,
socket, and containerd service are masked; the only Docker socket is private beneath the runner
runtime directory.

The runner has a narrow mTLS control service that can only delete containers selected by the exact
`hermes-task-id` label, plus a label-scoped stale-container reaper. It does not expose Docker's
HTTP API, shell execution, or a generic container endpoint. The primary Hermes service reaches
the rootless Docker daemon only through a forced-command SSH key that permits
`docker system dial-stdio`; no primary service receives a Docker socket mount.

The VM's live gates passed: rootless daemon admission, no rootful socket, no Docker TCP listener,
non-root sandbox execution, read-only rootfs, no network, strict limits, isolated workspaces,
forced child cleanup, mTLS refusal without a client certificate, and idempotent exact-label cleanup.
Provider and platform credentials were not copied to the VM or sandbox containers.

## Options

### A. Dedicated Runner Host

Use a separate VM or host running rootless Docker. The platform reaches a private runner endpoint
over mutually authenticated TLS or a private SSH/TLS tunnel. This provides the clearest host-level
blast-radius boundary and is the recommended production option when infrastructure is available.

Completed: runner host allocation, private network route, and runtime-only credential provisioning.
Provider and platform secrets remain absent from sandbox containers.

### B. Same-Host Rootless Docker Daemon

Create a dedicated `hermes-runner` OS user, install the missing `uidmap` helpers, allocate
`/etc/subuid` and `/etc/subgid` ranges, and run a rootless Docker daemon owned only by that user.
The dedicated runner service connects to that daemon; the primary API/Hermes containers retain no
Docker socket.

This is the recommended fallback when a second host is unavailable. It requires explicit approval
because it modifies host packages, users, subordinate-ID files, and service configuration outside
the project directory.

### C. Root Docker Socket Proxy On The Current Host

A socket proxy can reduce the exposed Docker API surface, but create/exec/container endpoints still
allow substantial control of the rootful host. It does not provide a sufficient multi-tenant
boundary and is not recommended for enabling terminal/file tools.

## Work After Selection

1. Completed: deploy the dedicated runner/control service against the rootless daemon boundary.
2. Completed: require live rootless host and sandbox attestation before control-service admission.
3. Completed: bind the platform's server-generated Hermes session task ID to organization/user/run ownership.
4. Completed: forward approval and cancellation only after platform ownership and permission checks.
5. Completed: force-remove the labeled sandbox on success, denial, stop, timeout, and disconnect;
   retain the label-scoped timer as the crash fallback.
6. Completed: prove cross-scope denial, stale-container cleanup, daemon restart recovery, exact-label
   preservation, real terminal/file workspace isolation, and audit metadata.
7. Completed after explicit release confirmation: enable only `terminal` and `file` in
   `platform_toolsets.api_server`. `code_execution` and all unrelated toolsets remain disabled.
   Live validation runs the backend and tool gates as the supervised UID 10000 gateway identity,
   with runner SSH material mounted read-only at `$HOME/.ssh`. The policy exposes only foreground
   terminal execution and removes the auxiliary `process` tool. Missing task IDs fail closed;
   platform admission defaults to global/organization/user limits of 8/4/2 active runs, and the
   runner unit, forced-command wrapper, and reaper resolve the service UID at runtime.
