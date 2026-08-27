# Hermes Private Integration Runbook

This runbook covers the opt-in Hermes Agent deployment used by the platform. The pinned
baseline is `NousResearch/hermes-agent` tag `v2026.7.7.2`, peeled commit
`9de9c25f620ff7f1ce0fd5457d596052d5159596`, and the expected upstream version is `0.18.2`.

## Boundary

- Hermes runs as a separate Compose service on the private `platform` network.
- The platform API remains the source of truth for JWTs, organization membership, permissions,
  resource ownership, message routing, audit metadata, and tenant boundaries.
- The platform adapter supplies a server-owned profile/session scope and correlation metadata.
  Clients must not provide a Hermes URL, profile path, or tenant scope.
- `platform_toolsets.api_server` enables only `terminal` and `file` after the dedicated runner,
  lifecycle, cross-scope, restart-recovery, and cleanup gates passed. `code_execution` and every
  unrelated toolset remain disabled.
- Knowledge files use the platform ingestion path. Do not send non-image documents to Hermes.

## Start

The default stack keeps the compatibility provider and does not start Hermes:

```bash
cd deploy
./scripts/up.sh
```

The opt-in stack generates `HERMES_API_SERVER_KEY` in the ignored `deploy/.env` file, builds the
pinned tag, and starts Hermes without a host port mapping:

```bash
cd deploy
./scripts/up.sh --with-hermes
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml ps
```

On Windows, use `./scripts/up.ps1 -WithHermes` in PowerShell. The API receives the same server
key as `HERMES_API_KEY` through the Compose override; the key must not be committed, copied into
documentation, or printed in logs.

For the Xiaomi MiMo deployment, set `XIAOMI_API_KEY` and
`XIAOMI_BASE_URL=https://api.xiaomimimo.com/v1` in the ignored `deploy/.env` file. The Compose
override passes them only to the Hermes container; the platform API does not receive the provider
credential. The private profile selects `mimo-v2.5`; deprecated v2 model names are not used.

## Sandbox Gate

The repository includes a Docker sandbox blueprint in `deploy/compose.sandbox.yaml` and a live
verifier in `deploy/scripts/verify-sandbox.sh`. The verifier starts two short-lived containers in
an independent Compose project, checks their Docker runtime policy, proves that their workspaces
cannot see one another, and removes both containers on exit:

```bash
cd deploy
sh scripts/verify-sandbox.sh
```

The pinned Hermes Docker backend has a separate controlled verifier. Run it inside the private
Hermes container so it uses the forced-command SSH transport to the dedicated rootless runner. It
instantiates the upstream `DockerEnvironment`, verifies the actual child container, force-removes
it, and emits a non-secret JSON attestation:

```bash
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml \
  exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-docker-backend.sh
```

The platform admission validator consumes only that JSON object:

```bash
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml \
  exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-docker-backend.sh \
  | sed -n '/^{/p' \
  | docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml \
      exec -T api python scripts/validate_sandbox_attestation.py
```

The deterministic real-tool gate calls the pinned terminal and file implementations directly,
without relying on model tool selection. It verifies two distinct task containers and workspaces:

```bash
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml \
  exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-tool-runner.sh
```

The standalone blueprint uses non-root UID/GID `65532`; the pinned Hermes runner uses the explicit
UID/GID `10000`. Both require a read-only root filesystem, no network, `cap_drop: ALL`, no added
capabilities, `no-new-privileges`, bounded PID/CPU/memory limits, no Docker socket, and a bounded
in-memory workspace.

The standalone blueprint proves only the policy. The deployed integration reuses the pinned Docker
backend behind the dedicated rootless runner and binds it to platform-owned run lifecycle and
cleanup. The primary API and Hermes services receive no Docker socket. After explicit release
confirmation, the minimum API toolset is exactly `terminal` and `file`.

The pinned `/v1/runs` lifecycle does not force-remove its Docker environment when a run completes,
fails, or is stopped; it relies on inactivity/orphan reaping. The platform therefore wraps the
lifecycle with exact-label mTLS cleanup, with the runner timer as the crash fallback. The
host/daemon choice and its security tradeoffs are recorded in
`docs/hermes-tool-runner-deployment-decision.md`.

### Dedicated Runner Checkpoint: 2026-07-27

The selected runner is a separate Ubuntu 24.04 KVM VM at private address `192.168.3.107`. It runs
rootless Docker under a locked, non-sudo `hermes-runner` user; rootful Docker/containerd services
and `/var/run/docker.sock` are masked/absent. The runner's primary control boundary is mTLS and
only supports `DELETE /v1/tasks/{task_id}` for a strictly validated, exact `hermes-task-id` label.
It has no generic Docker API or shell endpoint. An unauthenticated TLS client was rejected; an
authenticated cleanup smoke test removed exactly one labeled hardened container and a repeated
request returned `removed=0`.

The pinned `DockerEnvironment` ran on the rootless daemon with UID 10000, read-only rootfs, no
network, no forwarded sensitive environment, CPU/memory/PID limits, a writable UID-scoped tmpfs,
and forced cleanup. The outer Docker access path uses a forced-command SSH key limited to
`docker system dial-stdio`; the primary API and Hermes containers still have no Docker socket.
The main platform deployment now has the runtime-only mTLS/SSH material. Its strict startup shim
removes upstream automatic credential/skills/cache mounts and all capability additions, preserves
each server-owned session task ID instead of collapsing gateway sessions into `default`, and uses
`/workspace` for UID 10000. After explicit release confirmation,
`platform_toolsets.api_server` exposes only `terminal` and `file` through this boundary.

## Provider Readiness

Hermes health and capability endpoints can succeed before an inference provider is configured.
The real exercise is therefore a separate release gate. Configure the provider inside the Hermes
runtime according to the upstream deployment contract, then verify only variable names and
present/empty status when inspecting a server. Never print provider credential values.

The private server initially had only `HERMES_API_SERVER_KEY`; its first exercise correctly
stopped with HTTP 500 because no inference provider was configured. The current deployment has
Xiaomi MiMo configured through the ignored runtime `.env`, and the v2.5 exercise is recorded
below. Hermes' `X-Hermes-Session-Key` is a conversation-continuity key, not a tenant isolation
boundary; organization and session ownership must remain enforced by the platform API.

## Probe

Run the capability probe from the backend environment. It requires `HERMES_API_KEY` and fails
closed when the authenticated capability contract is missing:

```bash
cd backend
python scripts/probe_hermes.py
```

After provider readiness is confirmed, run the full exercise:

```bash
python scripts/probe_hermes.py --exercise
```

The exercise must prove all of the following against the private pinned service:

1. An authenticated `/v1/responses` response returns an id.
2. A second response accepts `previous_response_id` and returns a continuation.
3. A `/v1/runs` request produces a consumable SSE stream.
4. Stop and approval capability detection matches the advertised contract.
5. Session history can be read for the probe session.
6. Two user or organization scopes cannot read or continue one another's profile/session.

The first five checks prove the API contract. The last check is the tenant-isolation gate and must
not be replaced by a Hermes profile-name comparison. Profile directories are not a sandbox.

## Failure Handling

- `HERMES_API_KEY is required`: the API and Hermes server key are not aligned in the private
  Compose override.
- HTTP `401`: verify the server key wiring without displaying either secret.
- HTTP `500` with no inference provider: health is available, but the real exercise is blocked;
  do not mark the release gate complete.
- Connection or SSE failure: keep Hermes private, inspect container health/log metadata, and
  rerun the capability probe before changing the adapter.
- Non-image knowledge upload: keep it in the platform knowledge ingestion path; Hermes file
  upload is not the document ingestion boundary.

## Release Evidence

Record the tag, peeled commit, image digest if available, probe command, timestamp, and pass/fail
result. Do not record API keys, provider credentials, prompts, document contents, or raw Hermes
profile paths. Keep `test` as the demo baseline until profile reconciliation and the sandbox gate
are complete.

### Historical Checkpoint: 2026-07-24

This was an earlier private-runtime check before the current v2.5 redeploy. Do not use it as
evidence for the current provider configuration or for Hermes-level tenant isolation.

- Image: `hermes-agent:v2026.7.7.2`, digest
  `sha256:006c49113932971f825f2cfbccf8af3baecb048563412a2597bb2147f0ee87d2`.
- Compose services `db`, `hermes`, `api`, and `web` reported healthy; Hermes exposed no host port.
- `python scripts/probe_hermes.py --exercise` passed response creation, continuation, SSE,
  capability detection, and history read.
- Two distinct user/organization scopes each retained their own marker and did not expose the
  other marker; the isolation assertion returned `isolated=true`.
- The platform route also passed: JWT login `200`, ChatSession creation `201`, streamed chat
  `200` with one event, and platform-managed history `200` with one message.

### Validation Checkpoint: 2026-07-27

- The running Hermes container reported provider `xiaomi`, model `mimo-v2.5`, and build SHA
  `9de9c25f620ff7f1ce0fd5457d596052d5159596`; Hermes `0.18.2` health and detailed health were
  healthy. The image remained `hermes-agent:v2026.7.7.2` with the pinned digest
  `sha256:006c49113932971f825f2cfbccf8af3baecb048563412a2597bb2147f0ee87d2`.
- `python scripts/probe_hermes.py --exercise` passed authenticated response creation,
  `previous_response_id` continuation, a 74-event `/v1/runs` SSE stream, stop/approval
  capability detection, and session history with two messages.
- The platform JWT smoke passed: login `200`, ChatSession creation `201`, streamed chat `200`
  with four events including `response.completed`, platform history `200` with two messages,
  and cleanup `204`.
- The platform organization-isolation smoke passed: two temporary users in separate
  organizations each authenticated; the owner completed chat and history, while the other user
  received `404` for both history and send attempts. Temporary users, profiles, sessions, tokens,
  and organizations were removed after the check.
- All four Compose services (`db`, `hermes`, `api`, `web`) were healthy after the API rebuild and
  the planned Nginx `web` restart. Hermes had no host port mapping. No provider credential value
  was printed or recorded.
- The independent Docker sandbox blueprint passed its live gate: non-root/read-only/no-network
  policy, capability and resource limits, no Docker socket, blocked rootfs writes, writable
  per-container tmpfs workspaces, and negative cross-workspace visibility. The verifier cleaned
  up both probe containers. Hermes terminal/file toolsets remained disabled at that checkpoint.
- The pinned Hermes `DockerEnvironment` also passed a transient live probe with UID 10000,
  read-only rootfs, writable UID-scoped tmpfs workspace, no network, no forwarded sensitive
  environment, CPU/memory/PID limits, no Docker socket inside the child sandbox, and forced
  cleanup. The real JSON attestation passed the platform validator inside the rebuilt API
  container. At that checkpoint the dedicated runner service and lifecycle integration were still
  pending; the later bullets record their completion.
- The dedicated runner integration then passed from the formal Hermes container over forced-command
  SSH: no automatic bind mounts, no added capabilities, UID/GID 10000, read-only rootfs, network
  `none`, 256 MiB memory, 0.5 CPU, PID limit 256, and a 64 MiB UID-scoped writable tmpfs.
  The API admitted the resulting attestation and the runner was empty after cleanup.
- The deterministic pinned terminal/file gate passed `id -u`, write/read, two distinct task
  containers, exact server-owned labels, and negative cross-workspace visibility. This gate exposed
  and fixed the upstream gateway `default`-container collapse, `/root` cwd for the non-root user,
  and the host-side safe-root rejection of `/workspace`. The temporary tool-enabled container had
  no host port and was removed after the gate.
- Platform run lifecycle validation passed owner JWT stop, cross-owner `404`, stop audit, completed
  run idempotency, session deletion, SSE completion/interruption cleanup, and exact-label removal.
  A final JWT -> ChatSession -> SSE -> history run returned two history messages and settled its
  active run state before deletion.
- After the final restart, `db`, `hermes`, `api`, and `web` were healthy. The MiMo exercise passed
  response creation, continuation, a 66-event SSE stream, stop/approval capability detection, and
  two-message history. The formal API toolset remained empty at that pre-release checkpoint.
- After explicit release confirmation, the formal API set became exactly `terminal` and `file`.
  The platform shim removes the auxiliary `process` tool and background-only terminal parameters;
  `code_execution` and every unrelated toolset remain absent.
- The first model-driven attempt exposed a runtime-user mismatch: deterministic checks had run as
  root while the supervised gateway runs as UID 10000 with `HOME=/opt/data`. The runtime-only SSH
  directory was moved from `/root/.ssh` to `/opt/data/.ssh`, kept mode 0700 with non-secret files
  readable only by UID 10000, and both verifiers now fail unless run as that gateway identity.
- The UID 10000 backend and real-tool gates then passed again: runner Docker `29.6.2`, UID 10000,
  read-only rootfs, no network, no host mounts or forwarded environment, resource limits, terminal
  and file execution, two task scopes, cross-workspace denial, and complete child cleanup.
- Two platform JWT -> ChatSession -> SSE -> history -> delete smokes exercised the actual MiMo tool
  selection path. One produced `terminal` started/completed events for `id -u`; the other produced
  `write_file` and `read_file` started/completed events. History returned successfully, deletion
  returned `204`, and the dedicated runner was empty afterward.
- Hermes intentionally skips dangerous-command approval prompts for its isolated Docker backend
  when there are no host mounts. A destructive-command probe therefore completed inside the
  disposable no-network sandbox without an `approval.request`; this is upstream confinement
  semantics, not evidence that the platform approval endpoint resolved a request. The owner-scoped
  approval route remains fail-closed for future tools that are not eligible for this isolation
  exemption, and no such tool is enabled in this release.
- The first release probe hit the prior 30-second synchronous read timeout. The API's private
  Hermes timeout is now explicitly 120 seconds. The exact `python scripts/probe_hermes.py
  --exercise` command then passed health, detailed health, response continuation, 43 SSE events,
  stop/approval capability detection, and six history messages without an environment override.
- The Responses API assigns its own UUID session and returns it only through
  `X-Hermes-Session-Id`. The adapter now retains that non-secret cleanup identifier for the probe,
  and the probe removes both Responses and run tasks in `finally`. A repeated exact exercise
  completed with 47 SSE events and two history messages, followed by `runner-empty=passed`.
- Sandbox admission is serialized with a process lock plus a PostgreSQL transaction advisory lock.
  Row locks preserve one active run per ChatSession and also guard delete, stop, and approval
  lifecycle mutations, while defaults cap active runs at eight globally, four per organization,
  and two per user. A database commit failure stops the newly created upstream run and performs
  exact-label cleanup.
- Strict remote policy now rejects a missing or empty server-owned task ID instead of falling back
  to a shared `default` workspace. Runner unit files, the forced-command wrapper, and the reaper
  resolve the `hermes-runner` UID at runtime; the verifier also asserts the exact `/workspace`
  tmpfs size, UID/GID, `nosuid`, and `nodev` options.
- On 2026-07-28 the repaired SSH-MCP passed 30 sequential execs, 20 sequential uploads, a
  20-file batch, interleaved exec/upload calls, controlled-failure recovery, download hash
  verification, and reconnect validation without a channel-open failure. Platform source sync and
  the `hermes/api/web` rebuild then completed.
- Post-review hardening passed `75` local backend tests, Ruff, shell syntax, JSON, and diff checks.
  The live policy rejected missing task IDs; runtime toolsets were exactly `terminal,file`; the
  effective tool functions were exactly `patch/read_file/search_files/terminal/write_file`; and
  `process`, `code_execution`, and background terminal parameters were absent.
- The hardened backend and tool gates passed again. The tool gate now reads the gateway's actual
  `platform_toolsets.api_server` config and compares the complete `/workspace` tmpfs token set,
  including `rw`, `exec`, `nosuid`, `nodev`, size, UID/GID, and mode. Cross-workspace access was
  blocked and cleanup completed.
- The exact MiMo exercise passed response continuation, 62 SSE events, capability detection, and
  nine history messages, followed by `runner-empty=passed`. Platform JWT smokes produced real
  terminal and file tool events, successful history reads and session deletion, and another empty
  runner check.
- Two real PostgreSQL connections proved transaction advisory-lock serialization. Transactional
  live checks enforced user/organization/global active-run limits at 2/4/8 and rolled back all
  temporary rows.
- After the lifecycle row-lock review fix, the rebuilt API passed a second real PostgreSQL
  `SELECT ... FOR UPDATE` contention check: the second transaction stayed blocked until the first
  released its ChatSession lock. The temporary session was deleted. The UID 10000 terminal/file
  gate and a fresh MiMo exercise then passed again with 45 SSE events and six history messages.
  Runner cleanup was verified inside that tool gate; the maintenance SSH account cannot query the
  `hermes-runner` UID 1001 rootless Docker socket directly, so no separate default-socket result
  is treated as evidence.
- Final Compose state was healthy for `db`, `hermes`, `api`, and `web`; Hermes remained private
  with no host port, and no provider or platform credential value was printed or recorded.
- The staged dynamic-UID forced-command wrapper, reaper, and control/reaper unit files were
  installed through a privileged channel on 2026-07-28. The root runner-host verifier passed with
  the live `hermes-runner` account resolved dynamically as UID `1001`; rootful Docker, sudo group
  membership, and Docker TCP exposure remained absent. Fresh platform verification then passed
  the UID 10000 backend and terminal/file gates, the MiMo v2.5 exercise (96 SSE events and eight
  history messages), and a temporary-user JWT -> ChatSession -> terminal SSE -> history -> delete
  flow. Temporary validation data was removed, and a root runner check confirmed no
  `hermes-task-id` containers remained. No runtime credential value was printed or recorded.
