# Hermes Stable Platformization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the official Hermes Agent baseline, integrate it behind the existing platform authentication boundary, and prepare organization permissions and message routing for controlled second-stage development.

**Architecture:** Keep Hermes Agent as a separately deployed service at the official `v0.18.2` tag (`v2026.7.7.2`), and replace the in-process mock client with a small platform-owned adapter. The platform remains the source of truth for users, organizations, roles, permissions, resource ownership, routing rules, audit records, and frontend contracts. Hermes receives only an authorized, profile-scoped request through its authenticated API server. Do not merge the full upstream repository into this monorepo unless a later requirement proves that a source fork is necessary.

**Tech Stack:** Existing FastAPI, SQLAlchemy/Alembic, PostgreSQL, JWT, React, Zustand, Docker Compose, Hermes Agent API server, SSE.

---

## Baseline Findings

- The current repository contains explicit Phase 1 mocks in `backend/app/services/hermes_client.py`, `hermes_manager.py`, `mem0_client.py`, and the knowledge/skills boundaries. There is no Hermes Agent dependency, submodule, or branch in this repository.
- Current authorization is role-name based in `backend/app/auth/dependencies.py`; the existing `Role.permissions` JSON field is seeded but not enforced by endpoint policy.
- Current user resources are already filtered by `user_id`; `ChatSession` stores a platform session projection and an internal `hermes_session_id`.
- Official Hermes Agent `v0.18.2` exposes `/v1/responses`, session continuity, streaming runs and SSE events, stop/approval controls, session REST APIs, skills/toolset discovery, capabilities discovery, health/readiness, and Bearer auth.
- Hermes API file upload is not supported for non-image documents. Platform knowledge uploads must remain a separate ingestion/context path.
- Hermes profiles separate configuration, memory, skills, and sessions, but profiles are not a filesystem sandbox or a sufficient tenant security boundary. Tool execution needs container or equivalent isolation.

## Execution Boundary For This Continuation

The tracked `test` baseline remains `65f652b`, and the checkout intentionally carries untracked
`.superpowers/` plus this plan. The former user edit at
`web-platform/src/stores/chatStore.ts` was scanned for consumers, found unused, and removed only
after the user authorized that cleanup. Preserve `.superpowers/` and unrelated paths; do not stage
them as part of Hermes work.

The reviewed ownership branches were created from the `test` baseline and merged into
`codex/hermes-platform-integration` in the declared order. The integration checkpoint now
includes the Xiaomi provider configuration and private validation evidence; do not merge it into
`test` in this continuation. Keep the five Hermes branches separate on the remote for review and
handoff.

Do not create an extra worktree for this continuation: the explicit checkout and dirty-file
boundary above are part of the task context. The phase branch may carry those paths locally, but
Hermes commits must stage only their explicit implementation and test files.

## Branch Responsibilities

The following branches are the reviewed ownership boundaries:

- `codex/hermes-stable-v0.18.2`: version pin, local/container startup, capability probe, health probe, API adapter, SSE/reconnect behavior, and profile reconciliation. No organization policy changes.
- `codex/platform-organization-authz`: organization membership, roles and granular permissions, policy dependencies, resource scoping, audit events, and backend tests.
- `codex/message-routing`: channel identities, routing rules, delivery outbox, retries/idempotency, Hermes session correlation, and Feishu/DingTalk adapter contracts.
- `codex/module-prune`: only remove or disable mock/legacy modules after the integration branch proves their consumers have migrated. This branch must not delete compatibility keys or API field names without an explicit migration.
- `codex/hermes-platform-integration`: integration branch that merges the three feature branches in the order above, runs the full backend contract suite, and becomes the next release candidate. Keep `test` as the demo baseline until this branch passes.

## Implementation Steps

### 1. Freeze and probe the Hermes baseline

- [x] Record the upstream repository URL, tag `v2026.7.7.2`, full commit `9de9c25f620ff7f1ce0fd5457d596052d5159596`, artifact digest status, and the non-secret provider/tool policy in `docs/hermes-agent-v0.18.2.json`.
- [x] Add an opt-in `deploy/compose.hermes.yaml` override pinned to the upstream source tag `v2026.7.7.2`; record and verify its peeled commit in the manifest because the remote BuildKit cannot fetch the non-advertised commit directly. Set `API_SERVER_ENABLED=true`, bind only to the private Compose network, generate `API_SERVER_KEY` into ignored runtime `.env`, and add explicit health checks. Do not expose the agent directly to the host or public network.
- [x] Add `backend/app/services/hermes_capabilities.py` and `backend/scripts/probe_hermes.py`. The capability client must call `/health`, `/health/detailed`, and `/v1/capabilities`, require Bearer auth for the capability call, and fail closed when the required feature/endpoint set is missing.
- [x] Make the probe exercise one `/v1/responses` response, one `previous_response_id` continuation, one `/v1/runs` SSE stream, stop/approval capability detection, and one session-history read. The current Xiaomi MiMo v2.5 runtime exercise passed on 2026-07-27; the local test suite covers the request/response contract as well.
- [x] Do not change the platform chat router to real Hermes until the pinned-tag probe passes. Keep the current mock as the default compatibility provider.

### 2. Replace only the Hermes mock boundary

- [x] Define a provider-neutral interface in `backend/app/services/` for response/run creation, SSE event consumption, session history, cancellation, approval, and health.
- [x] Implement the Hermes HTTP adapter with Bearer auth, timeouts, bounded retries only for pre-response connection failures, SSE event parsing, disconnect events, and correlation IDs. Keep the adapter free of organization permission decisions.
- [x] Keep `ChatSession` as the platform projection and derive a server-owned scope from authenticated `user_id` plus the future organization context. Never accept a client-supplied profile, profile path, or raw Hermes URL.
- [x] Pass the server-owned request context through `backend/app/routers/chat.py`; defer real-provider cutover and durable reconnect/run-state persistence until the private probe and organization boundary are verified. Preserve existing API compatibility and frontend types.
- [x] Add focused backend tests for capability mismatch, cross-user session access, streamed completion, cancellation, retry idempotency, and upstream failure mapping.
- [x] Reconcile platform-owned profile metadata with the private Hermes profile/session lifecycle after the real exercise passes. `HermesProfileManager` now idempotently aligns organization scope and server-owned paths, and platform ChatSession creation repairs a missing profile; keep profile paths server-owned and do not enable tools before an enforceable sandbox exists. The pinned Hermes `X-Hermes-Session-Key` is continuity metadata, not a tenant boundary; platform organization/session ownership remains authoritative.

### 3. Implement organization and permission control

Implementation boundary for this branch: keep token shapes unchanged and derive the current
organization from a server-maintained default organization on the user. Memberships own the
organization-local role; the legacy `Role.permissions` JSON remains for compatibility while
normalized `Permission` and `RolePermission` rows become the authorization source of truth.
Persistent user resources gain a non-null `organization_id` while retaining the existing
`user_id` guard. Audit rows record action/resource metadata only and never prompts, tokens,
document contents, or secrets.

- [x] Add organization, membership, role-permission, and optional resource-scope tables through Alembic; migrate existing users into a default organization without changing login/token shapes unnecessarily.
- [x] Replace endpoint checks that only inspect role names with reusable permission dependencies such as `chat:use`, `chat:route`, `knowledge:read`, `knowledge:write`, `agent:admin`, and `org:admin`.
- [x] Enforce organization ownership on chat sessions, knowledge, skills, memory, reminders, and Hermes profiles. Keep the existing user-level ownership checks as the lower-level guard; routing records remain in the next routing branch.
- [x] Add metadata-only audit events for user membership creation/deactivation, role, and profile changes without logging prompts, tokens, document contents, or secrets.
- [x] Add backend tests proving allow/deny behavior and no cross-organization data or session leakage.

### 4. Implement message routing as a platform-owned workflow

- [x] Model channel identity, routing rule, delivery target, run correlation, and outbox state separately from Hermes sessions.
- [x] Resolve an incoming event to organization, member, permission, channel, and Hermes profile before creating a run.
- [x] Use an outbox with idempotency keys, retry/backoff, dead-letter state, and delivery status. Do not send external messages inside the database transaction.
- [x] Define Feishu and DingTalk adapters as contracts first; keep current UI discovery/iframe behavior separate from server-side delivery until credentials and webhook contracts are available.
- [x] Map Hermes tool-approval events to platform notifications and require the platform permission check before forwarding an approval.

### 5. Remove or quarantine unrelated modules

- [x] Build a consumer map before deletion. `docs/hermes-consumer-map.md` records the current consumers; every first-pass candidate still has compatibility consumers and remains in place.
- Deferred: replace candidates behind provider interfaces or feature flags, then remove only code
  with no remaining imports, routes, tests, or compatibility obligations. This is intentionally
  outside the current Hermes sandbox deployment continuation.
- [x] Keep `hermes-*` localStorage keys, API fields, historical type names, and compatibility identifiers until a separate migration is approved. The consumer map and frontend store tests confirm the keys/contracts remain; `chatStore.ts` was removed only after its no-consumer scan and explicit authorization.
- [x] Update deployment documentation, OpenAPI snapshots, and runbooks whenever a mock boundary changes. The private Hermes runbook and deployment/API guides now record the provider gate; OpenAPI regeneration reported no schema diff.

### 6. Verification and release

- [x] Run `backend` focused tests, migration checks, and contract tests for the Hermes adapter, authorization, and routing.
- [x] Run `npm run build`, `npm run lint`, and the focused frontend Vitest suite (`25 passed`); keep `.superpowers/` untracked and preserve compatibility keys/types even though the unused `chatStore.ts` file was removed with explicit authorization.
- [x] Run a small real Hermes integration check in a private environment, including auth, continuation, SSE, stop/approval detection, and platform-enforced profile/session isolation. The current Xiaomi MiMo v2.5 run on 2026-07-27 passed response/continuation, a 74-event SSE stream, stop/approval detection, and history. The platform JWT -> organization permission -> Hermes adapter route passed streamed output and history; a second organization received `404` for both history and send attempts. Direct Hermes API profile headers were not treated as isolation evidence.
- [x] Review `git diff -- backend`, secrets, public bindings, and container permissions on `codex/hermes-platform-integration`; Hermes exposes only the private Compose network and no secret value is committed.

## Merge Order

1. Completed: review and checkpoint `codex/hermes-stable-v0.18.2` at `9910f61`.
2. Completed: merge the stable branch into `codex/hermes-platform-integration`.
3. Completed: merge `codex/platform-organization-authz` into the integration branch.
4. Completed: merge `codex/message-routing` into the integration branch.
5. Completed: merge `codex/module-prune` after the consumer map and verification review.
6. Completed: the isolated Docker policy, dedicated runner, platform lifecycle, and real pinned
   terminal/file implementation gates passed on 2026-07-27. The explicit release confirmation was
   received; keep `test` as the demo baseline while validating the enabled minimum toolset.

## Docker Sandbox Gate

- [x] Define a short-lived container policy with non-root execution, read-only rootfs, no network,
  all capabilities dropped, no-new-privileges, strict PID/CPU/memory/file limits, no Docker socket,
  and independent tmpfs workspaces.
- [x] Add a fail-closed runtime verifier and prove on the private Linux Docker host that rootfs
  writes and network egress fail, workspaces remain writable but mutually invisible, runtime
  inspect values match policy, and probe containers are removed afterward.
- [x] Exercise the pinned Hermes `DockerEnvironment` through a transient UID 10000 runner, fix the
  upstream ephemeral-workspace ownership gap with an explicit tmpfs uid/gid/mode, verify the real
  child container policy and forced cleanup, and pass its JSON attestation through the platform's
  strict admission validator inside the deployed API container.
- [x] Integrate the pinned Hermes Docker terminal backend through the selected dedicated tool-runner and
  constrained Docker daemon/socket-proxy boundary. Do not mount a Docker socket into the primary
  API or Hermes service; use ephemeral per-task containers with network disabled, no environment
  forwarding, no host cwd mount, resource limits, labels, and orphan cleanup.
  **Selected boundary:** Ubuntu 24.04 KVM runner VM `192.168.3.107` with rootless Docker,
  a forced-command SSH Docker transport, mTLS exact-label cleanup control, and a stale-container
  reaper. Runtime-only client material is deployed to the primary platform, with no Docker socket
  mount. The strict shim removes upstream automatic host mounts and capability additions, preserves
  server-owned task IDs instead of the upstream shared `default` container, and keeps the writable
  workspace at a UID-scoped 64 MiB tmpfs. A rootful socket proxy remains disallowed.
- [x] Bind tool approval, cancellation, timeout, audit metadata, and guaranteed container cleanup
  to the platform run lifecycle; add cross-scope, stale-container, and escape regression tests.
  Owner-scoped stop/approval routes, active-run persistence, stop/delete/deny cleanup, SSE
  completion/interruption cleanup, audit writes, exact-label controls, and the stale reaper passed
  unit and live gates. Persistent `always` approvals are rejected by the platform.
- [x] Enable only the minimum required terminal/file toolset after the runner and negative tests
  pass. The enabled set is exactly `terminal` plus `file`; `code_execution` remains disabled and
  every tool call continues through the dedicated runner and platform lifecycle controls. The
  release validation corrected the SSH mount from root's home to the supervised gateway's
  `HOME=/opt/data`, reran both gates as UID 10000, and observed model-driven `terminal`,
  `write_file`, and `read_file` events through platform JWT sessions with an empty runner after
  cleanup. Background terminal execution and its auxiliary `process` tool are removed by policy.
  Hermes skips approval prompts for fully isolated Docker commands with no host mounts; this
  confinement exemption is recorded explicitly and does not authorize any non-isolated tool.
  Missing task IDs now fail closed, run admission is serialized across workers, and the default
  active-run quotas are global 8, organization 4, and user 2. The exact exercise also cleans the
  upstream Responses API's header-only session task and proves the runner is empty afterward.
- [x] Deploy the post-review fail-closed task-ID, serialized/quota admission, probe cleanup, and
  exact runtime/tool/tmpfs verifier. The repaired SSH-MCP passed sustained exec/upload/reconnect
  validation; `hermes/api/web` were rebuilt; local verification passed `75` tests plus Ruff and
  syntax checks; the real backend/tool, MiMo exercise, platform JWT terminal/file, PostgreSQL
  advisory-lock, 2/4/8 quota, and runner cleanup gates all passed on 2026-07-28. Delete, stop,
  and approval now take the same ChatSession row lock as run admission; a live two-transaction
  contention check passed after the final API rebuild.
- [x] Install the staged dynamic runner-UID wrapper and systemd unit candidates into their
  root-owned live paths, then rerun the runner-host, backend/tool, platform JWT, and empty-runner
  gates. On 2026-07-28, the privileged installation completed and the root runner-host verifier
  passed with the live `hermes-runner` UID resolved as `1001`. The deployed UID 10000 backend and
  terminal/file gates passed, including policy, task-workspace isolation, and cleanup. A fresh
  MiMo v2.5 exercise passed response continuation, 96 SSE events, capability detection, and eight
  history messages. A temporary-user platform JWT login then completed ChatSession creation,
  a streamed terminal event, history read, session deletion (`204`), temporary-user cleanup, and
  a root runner-empty check. No runtime credential value was printed or recorded.

## Deferred Decisions

- Do not adopt `v0.19.0` or `main` until an official tagged release exists and the same capability/isolation probe passes.
- Do not expose Hermes API server directly to browsers or the public FRP endpoint; route through the platform API or a private network.
- Do not treat Hermes profiles as tenant isolation by themselves. Choose Docker/Modal/another enforceable sandbox before enabling terminal/file tools for multiple organizations.
- Do not implement document upload by sending files to Hermes API; use the platform knowledge ingestion path and pass authorized excerpts/references.
