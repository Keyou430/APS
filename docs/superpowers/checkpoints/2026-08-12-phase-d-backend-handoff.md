# Phase D backend-only handoff

Date: 2026-08-12
Branch: `codex/phase-d-memory`
Base: `origin/main` at `25dbd67bc07138e37d11b4ae41ee9ca94021e181`

## Scope

Task 1-3 backend-only implementation is complete in this isolated worktree. No `web-platform/**`
files, frontend replacement files, PR #7 changes, Issue #6/#8 changes, credentials, runtime data,
uploads, or real customer data are included.

## API handoff

- `GET /api/memory` and `GET /api/memory/{memory_id}` return only current organization + current
  user active records; list uses `cursor`/`limit` keyset pagination and `provider=platform-postgres`.
- `POST /api/memory` creates an active manual record. `PUT` and `DELETE` require
  `expected_revision`; stale writes return `409`.
- `GET /api/memory/candidates` is owner-scoped. `POST /api/memory/{id}/confirm` and
  `/reject` require `expected_revision`; confirm activates and reject physically removes the
  candidate and links.
- `PUT /api/chat/sessions/{id}/memory-mode` is limited to knowledge sessions and requires
  `chat:use` plus `memory:read`; existing sessions default to `off`.
- Successful completed user turns may create a bounded, expiring `memory_capture_sources` snapshot
  only from the server-validated user request. Attachments, links, fixed context, assistant/tool
  output, skills, DingTalk documents, failed/interrupted turns, credentials, and high-risk PII are
  excluded. External extraction is disabled by default and cannot supply scope/status/id fields.
- Memory retrieval applies organization/user/status predicates in SQL before text matching. Only
  knowledge sessions with `memory_mode=auto` and `memory:read` receive the bounded untrusted
  `AUTHORIZED_MEMORY` block; agent sessions and `off` mode fail closed.

## Migration gate

Revision `20260811_0013` has `down_revision=20260810_0012`; no competing `0013` was present.
Against a disposable PostgreSQL 16.14 instance with pgvector 0.8.6:

1. `upgrade head` succeeded.
2. Verified six memory tables, `vector` embedding type, composite scope FKs/CHECKs, active owner
   partial index, partial FTS GIN, partial HNSW, and queue claim index.
3. `downgrade 20260810_0012` succeeded and removed the additive memory schema.
4. `upgrade head` succeeded again with Alembic version `20260811_0013`.

The instance used only `E:\Temp\phase-d-pg16`, database `phase_d_memory_gate`, and port `55432`;
the existing PostgreSQL 18 service was not used.

## Verification

- Task 1 initial RED: `5 failed, 2 passed` on persistence/authorization/migration tests.
- Task 2/3 focused regression: latest targeted suites pass, including capture replay/terminal purge,
  persistent claim/retry/restart recovery, candidate correction/supersede, FTS/vector/RRF,
  context budget, guest denial, and session tombstone/hash behavior.
- Full backend pytest: `317 passed, 60 warnings` after the final regression run.
- Ruff: `All checks passed!`.
- OpenAPI: `scripts/export_openapi.py --check` passed; snapshot contains 93 paths.
- Alembic heads: `20260811_0013 (head)`.
- Synthetic evaluation and `EXPLAIN` evidence: [2026-08-12-phase-d-memory-evaluation.md](2026-08-12-phase-d-memory-evaluation.md).

## Gates remaining

Task 0 Step 7, Task 4 frontend work, and Task 5 integration remain blocked by PR #7 / Issue #6 /
Issue #8. This handoff does not mark those gates complete.
