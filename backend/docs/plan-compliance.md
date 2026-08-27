# Plan Compliance Matrix

| Backend task | Implementation | Verification |
| --- | --- | --- |
| B1 Scaffold and Docker | FastAPI, Dockerfile, pgvector Compose, env, CI placeholder | Import, health test; Docker unavailable locally |
| B2 Schema and migration | Platform tables including refresh tokens and the Phase D memory ledger | Alembic roundtrip, migration invariants, ORM tests |
| B3 Auth and RBAC | JWT access/rotating refresh, OAuth stubs, role dependency | Auth and 401/403 tests |
| B4 Users | Paginated CRUD, filtering, sorting, soft delete, role assignment | User/RBAC integration test |
| B5 Profiles | Per-user metadata and manager; no CLI execution | Profile lifecycle integration test |
| B6 Chat | Plan B sessions and mock SSE | Stream and message integration test |
| B7 Memory | PostgreSQL/pgvector memory ledger with owner-scoped CRUD, CAS revisions, and audit metadata | Persistence, authorization, migration, and CRUD integration tests |
| B8 Knowledge | CRUD, upload, filtering, mock FastGPT search | Upload/search integration test |
| B9 Skills | CRUD, categories, hub and generation mocks | Skills integration test |
| B10 Reminders | CRUD, status, completion, upcoming query | Reminder integration test |
| B11 OpenAPI | Tags, schemas, descriptions, exported JSON | OpenAPI contract test |
| B12 Guide | Curl, TypeScript, SSE, errors, troubleshooting | Reviewed against generated paths |
| B13 Analysis | Six required sections and four-phase roadmap | Keyword/completeness checks |

Guardrails retained: no real Hermes CLI, external memory provider, real RAG/embedding, real AI generation,
notification scheduler, Feishu/DingTalk OAuth, LDAP, ReDoc, K8s, or generated SDK.

