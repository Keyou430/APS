#!/usr/bin/env bash
# Restore a custom-format backup produced by backup-db.sh.
# Safety: prints the archive TOC first and requires explicit confirmation,
# unless RUN_CONFIRMED=1 is exported (for automation with prior approval).
# Usage: ./scripts/restore-db.sh backups/agent-platform-YYYYmmdd-HHMMSS.dump
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-hermes-platform}"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "Usage: $0 <path/to/agent-platform-*.dump>" >&2
    exit 1
fi
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"

if [ -f "$ARCHIVE.sha256" ]; then
    echo "Verifying SHA256 manifest..."
    (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256")
else
    echo "WARNING: no .sha256 manifest found next to the archive." >&2
fi

if [ ! -f "$DEPLOY_ROOT/.env" ]; then
    echo "deploy/.env not found; refusing to guess database credentials." >&2
    exit 1
fi
# shellcheck disable=SC1091
set -a; . "$DEPLOY_ROOT/.env"; set +a
DB_NAME="${POSTGRES_DB:-agent_platform}"
DB_USER="${POSTGRES_USER:-postgres}"

echo
echo "=== Archive contents (pg_restore -l) ==="
docker compose --project-name "$PROJECT_NAME" --env-file "$DEPLOY_ROOT/.env" \
    -f "$DEPLOY_ROOT/$COMPOSE_FILE" \
    exec -T db pg_restore -l "/dev/stdin" < "$ARCHIVE" | head -40
echo "...(truncated)"
echo

if [ "${RUN_CONFIRMED:-0}" != "1" ]; then
    read -r -p "This will DROP and recreate database '$DB_NAME'. Type the database name to confirm: " CONFIRM
    if [ "$CONFIRM" != "$DB_NAME" ]; then
        echo "Confirmation mismatch; aborting." >&2
        exit 1
    fi
fi

echo "Stopping API and rag-worker before restore..."
docker compose --project-name "$PROJECT_NAME" --env-file "$DEPLOY_ROOT/.env" \
    -f "$DEPLOY_ROOT/$COMPOSE_FILE" stop api rag-worker 2>/dev/null || true

echo "Dropping and recreating database '$DB_NAME'..."
docker compose --project-name "$PROJECT_NAME" --env-file "$DEPLOY_ROOT/.env" \
    -f "$DEPLOY_ROOT/$COMPOSE_FILE" \
    exec -T db psql -U "$DB_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" \
    -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" \
    -c "CREATE DATABASE \"$DB_NAME\";"

echo "Restoring archive..."
docker compose --project-name "$PROJECT_NAME" --env-file "$DEPLOY_ROOT/.env" \
    -f "$DEPLOY_ROOT/$COMPOSE_FILE" \
    exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --no-privileges "/dev/stdin" < "$ARCHIVE"

echo "Restarting services..."
docker compose --project-name "$PROJECT_NAME" --env-file "$DEPLOY_ROOT/.env" \
    -f "$DEPLOY_ROOT/$COMPOSE_FILE" up -d

echo "Restore complete. Verify with: curl http://127.0.0.1:${APP_PORT:-8080}/ready"
