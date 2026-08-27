# Hermes Enterprise Agent Platform

Hermes enterprise workspace MVP with a React frontend, FastAPI backend, PostgreSQL/pgvector, and
a single Docker Compose deployment entry point.

## Repository Layout

- `web-platform/`: React, TypeScript, Vite, Arco Design frontend
- `backend/`: FastAPI, SQLAlchemy, Alembic, JWT/RBAC, compatibility mocks, and a pinned private Hermes HTTP boundary
- `deploy/`: full-stack Compose, Nginx reverse proxy, environment template, and operations scripts

## Linux Deployment

Requirements: Git, Docker Engine, and Docker Compose v2.

```bash
git clone https://github.com/OneAsmallFish/agent-platform-system.git
cd agent-platform-system/deploy
cp .env.example .env
```

Edit `.env` and replace all `change-this` values, then start the stack:

```bash
./scripts/up.sh
```

The default entry points are:

- Platform: `http://127.0.0.1:8080`
- Swagger UI: `http://127.0.0.1:8080/docs`
- Health: `http://127.0.0.1:8080/health`

Set `APP_BIND=0.0.0.0` only when the service must be reachable outside the Linux host. For real
data, terminate TLS at a trusted reverse proxy or load balancer.

See [`deploy/README.md`](deploy/README.md) for logs, shutdown, backup, rebuild, and volume handling.

## Development Verification

```bash
cd web-platform && npm ci && npm run build
cd ../backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Phase 1 keeps explicit mock integrations for local Hermes, Mem0, and FastGPT behavior while
preparing a pinned private Hermes container and HTTP adapter. The platform database,
authentication, user/profile metadata, API contract, frontend, and Compose stack are implemented.
