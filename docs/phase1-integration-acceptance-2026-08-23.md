# Phase 1 Integration Acceptance - 2026-08-23

This record covers the isolated integration branch `codex/phase1-integration`, based on Phase 1 closure plus the scoped Issue #14 changes.

## Included fixes

- Web search events are aggregated into one final platform status and validated sources are restored/rendered by the React chat route.
- Delivery outbox uniqueness uses a nested savepoint, preserving the outer decision transaction.
- Decision Feishu delivery is owner-route scoped; active targets without an enabled route for the decision owner are not broadcast.
- Issue #14 experience migrations are revision `20260823_0022` after the Phase 1 `0020/0021` chain, with PostgreSQL-valid organization composite uniqueness and creator membership foreign key.
- Experience method counts and lists enforce organization scope; duplicate domain races return 409.
- React knowledge upload requires and submits a selected `collection_id`.

## Local evidence

- Backend: `480 passed, 1 skipped` with the project venv; targeted experience/WebEvidence/outbox tests `19 passed`, decision tests `10 passed`, cross-organization and guest-permission experience tests included.
- Frontend: Node contract tests `32 passed`, Vitest `160 passed`, ESLint passed, production build passed, Playwright `11/11` passed.
- `scripts/export_openapi.py --check` passed; Alembic reports one head: `20260823_0022`.
- In-app browser rendered `/chat` and `/knowledge` with permission-denied states and no console errors.

## Remaining external gates

- PostgreSQL upgrade/downgrade and concurrent uniqueness must run in CI or an authorized PostgreSQL environment; this workstation has no Docker/psql. SQLite upgrade stops earlier at the pre-existing `0018` constraint-alter migration, before reaching this change.
- Real web-provider evidence still needs the formal SSH/provider credential path and a provider contract response.
- Real Feishu send/readback still needs an authorized test tenant, app credentials, and target conversation. Fake transport is not production evidence.
- Formal deployment, TLS reverse proxy, worker health, rollback, and `/docs` exposure require the operations environment.
