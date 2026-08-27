# Hermes Enterprise Platform Backend

FastAPI backend for the Hermes enterprise agent platform. The compatibility mock remains the
default provider while a pinned private Hermes HTTP boundary and organization authorization layer
are available behind explicit configuration.

## Architecture

- PostgreSQL 16 with pgvector for platform metadata, chunks, and platform-owned RAG
- JWT access/refresh tokens with persisted, single-use refresh-token records
- Platform-owned Hermes session projections with server-derived organization scope, active memberships, and normalized permissions
- Compatibility mock by default, with the pinned Hermes HTTP adapter available for a private container
- PostgreSQL/pgvector memory ledger with owner-scoped CRUD, revisions, and audit metadata
- Platform-owned Docling ingestion, text-embedding-v4 embeddings, and authorized hybrid retrieval
- A private `rag-worker` owns provider credentials and exposes only an authenticated query-embedding
  proxy to the API; the API never receives the provider key
- External guest invitations remain disabled by default. Approved trials can select the server-only
  SMTP adapter; the API never returns the invitation token when email delivery is enabled.

## Local Setup

```powershell
Copy-Item .env.example .env
docker compose up -d postgres
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe seed.py
.\.venv\Scripts\uvicorn.exe main:app --reload --port 8000
.\.venv\Scripts\python.exe -m app.workers.memory_worker
```

The real Hermes adapter is opt-in. Set `HERMES_USE_HTTP=true` and provide `HERMES_API_KEY` only
when a private Hermes API server is available. To run the pinned container with the full Compose
stack, use `deploy/scripts/up.ps1 -WithHermes` or `deploy/scripts/up.sh --with-hermes` from the
`deploy/` directory.

Open `http://localhost:8000/docs`. The development seed account is `admin` / `admin123`;
change it through environment variables outside local development.

Without Docker, the default settings use a local SQLite database for API development. The
PostgreSQL URL in `.env.example` is the deployment target and the Alembic migration enables
pgvector when running against PostgreSQL.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\export_openapi.py
.\.venv\Scripts\python.exe scripts\probe_hermes.py
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --dataset tests/fixtures/rag/evaluation.jsonl --report .runtime/rag-evaluation.json
.\.venv\Scripts\python.exe scripts\verify_rag_worker_recovery.py --help
```

See [docs/api-integration-guide.md](docs/api-integration-guide.md) for endpoint examples and
[docs/backend-analysis.md](docs/backend-analysis.md) for the runtime, sandbox, and platform RAG roadmap.
