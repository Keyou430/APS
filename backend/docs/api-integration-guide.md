# Hermes Platform API Integration Guide

The live OpenAPI contract is available at `/docs` and `/openapi.json`. The checked-in
`docs/openapi.json` is a frontend handoff snapshot, not a generated SDK.

## 1. Quick Start

Start PostgreSQL, apply migrations, seed the local administrator, and run FastAPI:

```powershell
docker compose up -d postgres
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\uvicorn.exe main:app --reload --port 8000
```

Health and documentation:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/openapi.json
```

## 2. Authentication

Login returns an access token and a single-use rotating refresh token:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH_TOKEN\"}"
```

Swagger UI's OAuth2 Authorize dialog uses the form-compatible `/api/auth/token` endpoint; the
frontend should continue using the JSON `/api/auth/login` endpoint.

Feishu and DingTalk endpoints are discovery stubs only:

```bash
curl http://localhost:8000/api/auth/oauth/feishu
curl http://localhost:8000/api/auth/oauth/dingtalk
```

All examples below require `Authorization: Bearer $TOKEN`. User and profile administration
also requires the `admin` role.

```bash
curl http://localhost:8000/api/users?page=1\&page_size=20 \
  -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/users \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"change-me-123","email":"alice@example.com","role":"user"}'
curl -X PUT http://localhost:8000/api/users/2/roles \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"role":"manager"}'
curl -X DELETE http://localhost:8000/api/users/2 -H "Authorization: Bearer $TOKEN"

curl -X POST http://localhost:8000/api/hermes/profiles \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"user_id":2}'
curl http://localhost:8000/api/hermes/profiles/2/health \
  -H "Authorization: Bearer $TOKEN"
```

### External guest invitations

Guest endpoints remain fail-closed unless `FEATURE_EXTERNAL_GUESTS=true`. The default `test`
delivery adapter returns a one-time token for isolated acceptance only. A real trial must select
`GUEST_INVITATION_DELIVERY_ADAPTER=smtp` and configure the public browser base URL, SMTP host,
port, username, authorization code, recipient allowlist, and optional from address through runtime
environment values. Addresses outside the normalized allowlist fail before a token or invitation
record is created.

The SMTP adapter sends `/invitations/accept#token=...`; the fragment keeps the token out of HTTP
paths, query strings, referrers, and normal access logs. SMTP responses omit the plaintext token.
If delivery fails, the new token is revoked and the API returns a generic `503` without provider
details. Production invitation links must use HTTPS.

## 3. Chat API: Plan B

Create a session, then send only the new message. Do not send a history array. The configured
provider owns history under `hermes_session_id` through the stateful response/run contract. Local
development uses equivalent compatibility events; the private deployment uses the pinned Hermes
HTTP adapter.

```bash
curl -X POST http://localhost:8000/api/chat/sessions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Project planning"}'
curl http://localhost:8000/api/chat/sessions -H "Authorization: Bearer $TOKEN"
curl -N -X POST http://localhost:8000/api/chat/sessions/1/messages \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"Summarize the project risks"}'
curl http://localhost:8000/api/chat/sessions/1/messages \
  -H "Authorization: Bearer $TOKEN"
curl -X DELETE http://localhost:8000/api/chat/sessions/1 \
  -H "Authorization: Bearer $TOKEN"
```

SSE frames use named events and JSON data:

```text
event: run.created
data: {"run_id":"...","session_id":"..."}

event: response.output_text.delta
data: {"delta":"Mock "}

event: response.completed
data: {"run_id":"..."}
```

## 4. Knowledge Base

The approved path stores metadata and originals, then asynchronously parses supported documents,
creates 1024-dimensional embeddings, and indexes versioned chunks in PostgreSQL 16 with pgvector.
Retrieval is always filtered by the authenticated organization and user scope before vector or
full-text search. Resource CRUD, ingestion status, and authorized hybrid retrieval are implemented.
The API uses a private authenticated query-embedding proxy on `rag-worker`; only that worker receives
the provider credential. When the proxy is unavailable, retrieval reports `degraded_full_text` and
does not expose provider error details.

```bash
curl -X POST http://localhost:8000/api/knowledge \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"link","title":"Hermes Docs","url":"https://hermes-agent.nousresearch.com/docs"}'
curl http://localhost:8000/api/knowledge?type=link -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/knowledge/1 -H "Authorization: Bearer $TOKEN"
curl -X PUT http://localhost:8000/api/knowledge/1 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Updated Hermes Docs"}'
curl -X POST http://localhost:8000/api/knowledge/upload \
  -H "Authorization: Bearer $TOKEN" -F "title=Runbook" -F "file=@runbook.pdf"
curl -X POST http://localhost:8000/api/knowledge/search \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Hermes","limit":10}'
```

Ingestion and authorized retrieval:

```bash
curl -X POST http://localhost:8000/api/knowledge/1/ingest \
  -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/knowledge/1/ingestion \
  -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/knowledge/retrieve \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Hermes","source_ids":[1],"limit":8}'
```

Internal sharing and resource lifecycle:

```bash
curl -X PUT http://localhost:8000/api/knowledge/1/access \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"visibility":"organization_members"}'
curl -X POST http://localhost:8000/api/knowledge/1/grants \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"membership_id":2}'
curl http://localhost:8000/api/knowledge/1/content -H "Authorization: Bearer $TOKEN"
curl -OJ http://localhost:8000/api/knowledge/1/download -H "Authorization: Bearer $TOKEN"
curl -X DELETE http://localhost:8000/api/knowledge/1 -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/knowledge/1/restore -H "Authorization: Bearer $TOKEN"
curl -X DELETE http://localhost:8000/api/knowledge/1/purge -H "Authorization: Bearer $TOKEN"
```

`DELETE /api/knowledge/{id}` archives the entry and immediately removes it from authorized reads.
Permanent purge is a separate owner-only command and only accepts archived entries. Shared detail
responses never include the compatibility `content` field; preview and download re-check current
authorization on every request, and download responses are private, no-store, and `nosniff`.

Knowledge operations and audit endpoints expose metadata only:

```bash
curl http://localhost:8000/api/knowledge/operations/overview -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/knowledge/operations/jobs?status=failed -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/knowledge/operations/jobs/1/retry -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/audit-events?limit=50 -H "Authorization: Bearer $TOKEN"
```

Retrieval events store a versioned HMAC query identifier, mode, outcome, count, and latency. They do
not store the query, answer, chunk text, object path, provider response, or a bare query hash.

## 5. Skills

Skills store complete `SKILL.md` text. Generation and Hermes Skills Hub calls are deterministic
mock responses during Phase 1.

```bash
curl http://localhost:8000/api/skills?category=general -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/skills/hub -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/skills \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Monthly Report","category":"general","content":"# Monthly Report"}'
curl -X POST http://localhost:8000/api/skills/generate \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"description":"Help me write monthly sales reports"}'
curl -X PUT http://localhost:8000/api/skills/1 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"category":"role-specific"}'
curl -X DELETE http://localhost:8000/api/skills/1 -H "Authorization: Bearer $TOKEN"
```

## 6. Memory: platform PostgreSQL ledger

The platform reads and writes memory through the PostgreSQL/pgvector ledger. Scope is derived
from the current organization context and active membership, and memory content is never accepted
from request metadata as an authorization signal. Hermes remains the conversation/runtime boundary.

```bash
curl -X POST http://localhost:8000/api/memory \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"User prefers dark mode","type":"preference"}'
curl http://localhost:8000/api/memory?query=dark -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/memory/MEMORY_ID -H "Authorization: Bearer $TOKEN"
curl -X PUT http://localhost:8000/api/memory/MEMORY_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"User prefers light mode","expected_revision":1}'
curl -X DELETE 'http://localhost:8000/api/memory/MEMORY_ID?expected_revision=2' \
  -H "Authorization: Bearer $TOKEN"
```

## 7. Reminders and Errors

Reminder recurrence and notification channels are metadata only. No cron scheduler or external
Feishu/DingTalk delivery runs in the MVP.

```bash
curl -X POST http://localhost:8000/api/reminders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Submit report","due_date":"2026-07-31T18:00:00Z","type":"recurring","recurrence":"monthly","notification_channel":"in-app"}'
curl http://localhost:8000/api/reminders?status=active -H "Authorization: Bearer $TOKEN"
curl http://localhost:8000/api/reminders/upcoming -H "Authorization: Bearer $TOKEN"
curl -X PUT http://localhost:8000/api/reminders/1 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Submit final report"}'
curl -X POST http://localhost:8000/api/reminders/1/complete \
  -H "Authorization: Bearer $TOKEN"
curl -X DELETE http://localhost:8000/api/reminders/1 -H "Authorization: Bearer $TOKEN"
```

Errors use one envelope across authentication, authorization, lookup, and validation failures:

```json
{"error":{"code":"http_404","message":"Resource not found"}}
```

Validation responses add a `details` array. Common statuses are `401` invalid/expired token,
`403` insufficient role, `404` unknown or cross-user resource, `409` uniqueness conflict, and
`422` invalid request. Rate limiting is not enabled in Phase 1; add it at the ingress in Phase 4.

## 8. Architecture Notes and TypeScript

The current Hermes gateway uses a shared HERMES_HOME; platform session keys partition conversation
state but are not an authorization boundary. Chat uses Plan B stateful sessions, memory uses private
the platform memory ledger, and knowledge retrieval uses the platform-owned Docling/pgvector pipeline. Knowledge sessions
are routed to a separate tool-less Hermes gateway, and Hermes receives only the authorized context
assembled by the API.

```typescript
type Tokens = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
};

const login = await fetch("http://localhost:8000/api/auth/login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "admin", password: "admin123" }),
});
const tokens: Tokens = await login.json();

const session = await fetch("http://localhost:8000/api/chat/sessions", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${tokens.access_token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ title: "New session" }),
});
```

Troubleshooting:

1. `401` after refresh: refresh tokens are rotating and can only be exchanged once.
2. `403` on `/api/users`: the token must belong to an active administrator.
3. PostgreSQL connection refused: start `postgres` and verify `DATABASE_URL` in `.env`.
4. Empty chat after restart: the local compatibility provider is in memory; the private Hermes
   container keeps its own session data under the mounted Hermes data volume.
5. Memory items disappear after restart: verify that the API is pointed at the intended PostgreSQL
   database and that Alembic head `20260811_0013` has been applied; SQLite remains development-only.

## 9. Private Hermes Probe

The base Compose stack uses the compatibility provider. The private Hermes HTTP adapter is enabled
only by `HERMES_USE_HTTP=true` and a server-owned `HERMES_API_KEY`; the Hermes Compose override
provides those values inside the private network. Do not expose the Hermes API port to the host or
browser.

Run the capability-only probe before exercising inference:

```bash
python scripts/probe_hermes.py
```

After an inference provider is configured inside the Hermes runtime, run:

```bash
python scripts/probe_hermes.py --exercise
```

The exercise covers response creation, `previous_response_id` continuation, run SSE, stop and
approval capability detection, and session history. A successful `/health` or capabilities probe
does not prove that an inference provider is configured. See
[`docs/hermes-private-integration-runbook.md`](../../docs/hermes-private-integration-runbook.md)
for the release gate and profile-isolation requirements.
