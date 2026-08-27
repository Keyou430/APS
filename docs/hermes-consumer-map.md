# Hermes and Mock Consumer Map

Snapshot for `codex/module-prune` after the Phase 1, organization-authz, and routing
checkpoints. This map is a deletion gate; a candidate is not removed merely because its
implementation is currently a mock.

| Candidate | Current consumers | Decision |
| --- | --- | --- |
| `backend/app/services/hermes_client.py` | `backend/app/routers/chat.py`, `backend/scripts/probe_hermes.py`, Hermes boundary tests, runtime provider builder | Keep. It is now the provider-neutral mock/HTTP boundary; preserve the default mock and compatibility API. |
| `backend/app/services/hermes_manager.py` | `backend/app/seed.py`, `backend/app/routers/users.py`, `backend/app/routers/hermes.py`, `backend/app/routers/chat.py`, profile tests | Keep. It owns compatibility metadata and server-owned `org:user` scope reconciliation; it does not start a per-user process. |
| `backend/app/services/memory_repository.py` | `backend/app/routers/memory.py`, backend memory tests | Keep as the PostgreSQL/pgvector owner-scoped persistence boundary; external providers may only return validated candidate DTOs. |
| Mock FastGPT search | `backend/app/routers/knowledge.py`, `backend/app/schemas/knowledge.py`, OpenAPI snapshot, frontend knowledge services/types/tests | Keep. The `provider` field and response shape are compatibility contracts. |
| Mock skill generation/Hub | `backend/app/routers/skills.py`, `backend/app/services/skill_generator.py`, schemas, OpenAPI snapshot, frontend skill services/types/tests | Keep. Replace behind a provider interface before pruning. |
| Frontend mock runtime/database/generators | `web-platform/src/mock/**`, platform/knowledge services, page/store/component tests | Keep for the existing demo mode. Do not remove `hermes-*` storage keys or mock API fields. |
| `web-platform/src/stores/chatStore.ts` | No consumers found by `rg`; removed with explicit user authorization and checkpointed in `9910f61`. | Already removed; no compatibility key was removed. |

No candidate in the first-pass list is safe for deletion on this branch. The next removal work
requires a real provider implementation, a migration/compatibility plan, and a second consumer
scan covering routes, tests, OpenAPI snapshots, frontend types, and persisted storage keys.
