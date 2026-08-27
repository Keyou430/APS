# Hermes Platform Compose Deployment

This folder starts the current `web-platform/` and `backend/` sibling repositories as one local or
private-network stack:

```text
Browser :8080 -> Nginx + React
                    | /api, /docs, /health, /ready
                    v
                 FastAPI :8000 -> PostgreSQL 16 + pgvector
```

The default stack keeps the local Hermes, Mem0, and platform-owned knowledge boundaries. The optional
Hermes override builds the pinned upstream commit as a private Compose service and switches only
the backend Hermes boundary to the HTTP adapter. The Hermes service has no host port mapping.
RAG embedding is disabled by default, so local and CI queries use the authorized full-text
fallback. Set `RAG_EMBEDDING_ENABLED=true` only after provider credentials are present; the
startup scripts then enable the private `rag` Compose profile.

## Start on Windows

The first run creates `deploy/.env` and exits so placeholder credentials are not started by
accident:

```powershell
cd deploy
.\scripts\up.ps1
notepad .env
.\scripts\up.ps1
```

Open `http://127.0.0.1:8080`. Swagger is available through the same Nginx entry point at
`http://127.0.0.1:8080/docs`.

### Local Hermes AI workbench

The local workbench starts two loopback-only Hermes gateways together with FastAPI and Vite:

```powershell
cd D:\Replica1.0\deploy
.\scripts\start-local-ai.ps1
.\scripts\status-local-ai.ps1
.\scripts\stop-local-ai.ps1
```

Open `http://127.0.0.1:5173` for the application. FastAPI is available at
`http://127.0.0.1:8000`; Agent Hermes listens on `http://127.0.0.1:8642`, and the isolated
Knowledge Hermes profile listens on `http://127.0.0.1:8643`. All four services bind only to
`127.0.0.1`.

`deploy/.env` is the only model-secret source. The launcher reads only `DEEPSEEK_API_KEY`, optional
`DEEPSEEK_BASE_URL`, and `HERMES_API_SERVER_KEY`, then injects them only into the child processes
that require them. The Agent gateway exposes only the controlled `hermes-lark-cli` MCP server,
which reuses the operator-managed local lark-cli user authorization for approved Feishu business
domains. It does not expose raw OpenAPI, account configuration, arbitrary Shell, or direct
`--yes`; lark-cli high-risk writes require an argv-bound one-time user confirmation. The Knowledge
gateway uses `no_mcp` and has no Feishu or other tool access.

Startup fails before launching anything if ports `5173`, `8000`, `8642`, or `8643` are already in
use. A later health-check failure rolls back only processes created by that startup attempt. PID
files and per-service logs are kept under `deploy/.runtime/local-ai`; failed-start logs are retained
for diagnosis.

To include the pinned Hermes container, run `.\scripts\up.ps1 -WithHermes`. The script generates
`HERMES_API_SERVER_KEY` in the ignored `deploy/.env` file. On Linux or macOS use
`./scripts/up.sh --with-hermes`; `openssl` is required for key generation.

## Start on Linux or macOS

```bash
cd deploy
./scripts/up.sh
# edit .env after the first run
./scripts/up.sh
```

Direct Compose commands work as well:

```bash
cp .env.example .env
# edit .env before starting
docker compose --env-file .env -f compose.yaml up -d --build --wait
```

The real Hermes service is started with the additional `-f compose.hermes.yaml` override. The
override pins the build context to commit `9de9c25f620ff7f1ce0fd5457d596052d5159596` from tag
`v2026.7.7.2`, enables the authenticated API server on the Compose network, and checks its private
`/health` endpoint. Its read-only Hermes config exposes only `terminal` and `file` through the
dedicated rootless runner; `code_execution` and every unrelated toolset remain disabled.

See [`docs/hermes-private-integration-runbook.md`](../docs/hermes-private-integration-runbook.md)
for provider readiness, the capability probe, the real exercise gate, profile-isolation checks,
and failure handling. A healthy Hermes container is not sufficient evidence of inference-provider
or tenant-isolation readiness.

## Operations

```powershell
.\scripts\logs.ps1
.\scripts\logs.ps1 api
.\scripts\backup-db.ps1
.\scripts\down.ps1
```

On Linux hosts (including the formal server) use the shell equivalents:

```bash
sh scripts/backup-db.sh
sh scripts/restore-db.sh backups/agent-platform-<timestamp>.dump
```

To remove the database and uploaded data intentionally, run `docker compose down --volumes`
manually after taking a backup. The provided down scripts preserve all named volumes.

Set `APP_BIND=0.0.0.0` in `.env` only when other machines must access the stack. In that case,
also place the deployment behind the organization's TLS reverse proxy before using real data.
Use URL-safe characters for `POSTGRES_PASSWORD` because it is embedded in the SQLAlchemy database
URL. Hermes remains private even when the platform browser entry point is exposed; do not add a
host `ports` mapping for the Hermes service. Terminal/file tools are permitted only through the
dedicated rootless runner and platform lifecycle controls.

### Backup and restore

`backup-db.sh` / `backup-db.ps1` write a compressed custom-format archive
(`pg_dump -Fc`) plus a `.sha256` manifest into `deploy/backups/`. Before any
restore, verify integrity and preview the archive (`sha256sum -c` /
`pg_restore -l`); `restore-db.sh` enforces both, stops the API and
rag-worker, drops and recreates the database, restores, and restarts the
stack. Never run a restore against the production database without a fresh
backup of its current state.

## Formal Deployment

The formal (production) host runs the base stack plus the Hermes formal
override and its pinned gateway configuration:

```bash
cd deploy
docker compose --env-file .env \
  -f compose.yaml -f compose.formal-hermes.yaml up -d --build
```

Key points:

- `deploy/hermes-formal/` holds the formal gateway configs
  (`config.yaml` for the agent gateway with the `web` toolset,
  `config.knowledge.yaml` for the knowledge gateway with no web tools,
  `SOUL.md` for channel/claims discipline). These files are version
  controlled; credentials stay in the ignored `.env`.
- The web entry defaults to `127.0.0.1:8092` (`FORMAL_APP_BIND` /
  `FORMAL_APP_PORT`). Expose it only behind the organization's TLS reverse
  proxy.
- The API and rag-worker images run as non-root UID 10001. On hosts whose
  `backend_uploads`/`hermes_profiles` volumes were created by an older
  root-built image, run the one-time ownership fix before upgrading:
  `docker compose --env-file .env -f compose.yaml -f compose.formal-hermes.yaml exec -u root api chown -R app:app /data`
  (and the same for `rag-worker`).

### Feishu delivery authority (single channel)

Decision notifications have exactly one outbound authority: the platform
`delivery-worker` consuming `delivery_outbox` through the official Feishu
OpenAPI (`PLATFORM_FEISHU_APP_ID` / `PLATFORM_FEISHU_APP_SECRET` in
`deploy/.env`). The Hermes gateway's own `FEISHU_*` variables and its
`platform_toolsets.feishu: [web]` entry only enable the Hermes-native inbound
bot session and its tool traffic — they are **not** a platform send
capability and must never be described as one. Set the non-secret
`PLATFORM_FEISHU_DELIVERY_CONFIGURED=true` only while both platform credentials
are provisioned for the worker; it lets the API report worker readiness without
receiving either secret. With the credentials absent, keep the flag false so
`GET /api/delivery/status` reports `feishu_not_configured` and outbox rows retry
honestly instead of faking success.

### Feishu context reader

Private Feishu Docx, Wiki documents, Base tables, and group-chat history in AI
chat are read by the API only when `PLATFORM_FEISHU_READ_CONFIGURED=true` and
the same `PLATFORM_FEISHU_APP_ID` / `PLATFORM_FEISHU_APP_SECRET` credentials are
present in the ignored `deploy/.env`. The Feishu application must have the
approved Docx/Wiki read and group-chat history read scopes plus
`bitable:app:readonly`. Its bot/application identity must be a member of each
target group, have access to each target document, and be granted access to each
target Base application.

The API requires comma-separated grants in
`PLATFORM_FEISHU_READ_ALLOWED_ORGANIZATION_IDS`,
`PLATFORM_FEISHU_READ_ALLOWED_DOCUMENT_TOKENS`,
`PLATFORM_FEISHU_READ_ALLOWED_BASE_TABLES`, and
`PLATFORM_FEISHU_READ_ALLOWED_CHAT_IDS`. Base entries use the exact
`organization_id:app_token:table_id` format, for example
`PLATFORM_FEISHU_READ_ALLOWED_BASE_TABLES=1:app_example:tbl_example,1:app_example:tbl_second`.
Every organization and target resource must be listed explicitly; an empty or
malformed value denies access. Do not put credentials or allowlists in Hermes
configuration or prompts.

After changing `deploy/.env`, rebuild and recreate the API service so it restarts
with the new environment:

```bash
docker compose --env-file .env \
  -f compose.yaml -f compose.formal-hermes.yaml \
  up -d --build api
```

For live acceptance, sign in under an allowed organization and ask AI chat to
summarize an authorized Feishu Base URL containing the configured `app_token`
and `table_id`; verify that the response uses records from that table. Then use
an unlisted Base table and verify that access is denied without a public-fetch
fallback. Remove any temporary test grant from `deploy/.env` and rerun the same
Compose command after acceptance.

## Isolated Acceptance Stack

`compose.acceptance.yaml` runs a release candidate beside the live
deployment without sharing its project name, ports, or volumes:

```bash
cd deploy
cp .env .env.acceptance        # then change secrets/ports inside
docker compose --env-file .env.acceptance \
  -f compose.yaml -f compose.formal-hermes.yaml -f compose.acceptance.yaml \
  up -d --build
```

Defaults: project `hermes-platform-acceptance`, web on `127.0.0.1:18080`,
database on `127.0.0.1:15432`, dedicated `acceptance_*` volumes. To test
against realistic data, restore a production backup into the acceptance
database first (`COMPOSE_PROJECT_NAME=hermes-platform-acceptance
sh scripts/restore-db.sh <archive>`). Never point the acceptance stack at
the production volumes, and never reuse production secrets in
`.env.acceptance`.

## External Guest Email Trial

External guests are disabled by default. An approved SMTP trial requires runtime-only values in
the ignored `.env` file or a separate Compose `--env-file`:

```text
FEATURE_EXTERNAL_GUESTS=true
GUEST_INVITATION_DELIVERY_ADAPTER=smtp
GUEST_INVITATION_PUBLIC_BASE_URL=https://platform.example.com
GUEST_INVITATION_RECIPIENT_ALLOWLIST=approved-recipient@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=provider-authorization-code
SMTP_FROM_EMAIL=sender@example.com
```

Never commit the SMTP authorization code. Build the Web with the same feature flag so the member
page exposes the invitation command. The API sends tokens only in the email fragment and omits
them from the SMTP-mode response. A failed send revokes the issued token. Restore the guest flag
to `false` and recreate API/Web after a bounded trial unless the external service has separately
been approved for ongoing use.

## Sandbox Validation

`compose.sandbox.yaml` is an isolated validation profile and is not part of the application stack.
Run its live gate on the Linux Docker host with:

```bash
cd deploy
sh scripts/verify-sandbox.sh
```

The verifier uses a separate `hermes-sandbox-verify` Compose project, launches two non-root,
read-only, networkless containers with independent tmpfs workspaces and strict resource limits,
checks negative cross-workspace access, and cleans up on exit. Passing this gate validates the
container policy only. It does not enable Hermes tools. The deployed integration adds the
platform-owned run lifecycle and reuses the pinned Hermes Docker backend through the dedicated
rootless runner; the primary `api` and `hermes` services still have no Docker socket mount.

To validate the pinned Hermes backend itself without enabling API toolsets, run:

```bash
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml \
  exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-docker-backend.sh
```

The real terminal/file implementation gate is safe to run independently of model tool selection:

```bash
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml \
  exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-tool-runner.sh
```

These verifiers use the forced SSH transport to the dedicated rootless runner, validate the child
policy and per-task workspace isolation, and force-remove their children. The dormant policy is
recorded in `hermes/tool-runner-config.yaml`; the enabled API set is exactly `terminal` and `file`.
Run both verifiers as UID/GID 10000 so the check uses the same `$HOME=/opt/data`, SSH material,
and runner access as the supervised gateway process.

Run admission is serialized across API workers with a PostgreSQL advisory lock. The default
limits are eight active sandboxes globally, four per organization, and two per user; override the
corresponding `SANDBOX_MAX_ACTIVE_RUNS_*` variables only after sizing the dedicated runner.

## Service Lifecycle

1. PostgreSQL starts and passes `pg_isready`.
2. FastAPI runs `alembic upgrade head` and the idempotent seed script.
3. Nginx starts after the API health check succeeds.
4. Compose `--wait` returns only after the public `/ready` route succeeds. `/health` remains a
   liveness-only endpoint.

Rebuild after frontend or backend changes:

```powershell
docker compose --env-file .env -f compose.yaml up -d --build --wait
```

If the API container is recreated and the web healthcheck temporarily reports `502`, restart the
web container so Nginx resolves the current Compose `api` address:

```bash
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml restart web
```
