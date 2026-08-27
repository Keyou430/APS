#!/usr/bin/env bash
# Production database backup: custom-format dump + SHA256 manifest.
# Usage: ./scripts/backup-db.sh  (run from deploy/ or anywhere in the repo)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_ROOT="$DEPLOY_ROOT/backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-hermes-platform}"

mkdir -p "$BACKUP_ROOT"

if [ ! -f "$DEPLOY_ROOT/.env" ]; then
    echo "deploy/.env not found; refusing to guess database credentials." >&2
    exit 1
fi

# shellcheck disable=SC1091
set -a; . "$DEPLOY_ROOT/.env"; set +a
DB_NAME="${POSTGRES_DB:-agent_platform}"
DB_USER="${POSTGRES_USER:-postgres}"

DESTINATION="$BACKUP_ROOT/agent-platform-${TIMESTAMP}.dump"

docker compose --project-name "$PROJECT_NAME" --env-file "$DEPLOY_ROOT/.env" \
    -f "$DEPLOY_ROOT/$COMPOSE_FILE" \
    exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DESTINATION"

if [ ! -s "$DESTINATION" ]; then
    rm -f "$DESTINATION"
    echo "pg_dump produced an empty archive; backup aborted." >&2
    exit 1
fi

SHA256="$(sha256sum "$DESTINATION" | awk '{print $1}')"
SIZE="$(stat -c%s "$DESTINATION")"
printf '%s  %s  %s bytes  db=%s\n' "$SHA256" "$(basename "$DESTINATION")" "$SIZE" "$DB_NAME" \
    > "$DESTINATION.sha256"

echo "Backup complete:"
echo "  archive : $DESTINATION ($SIZE bytes)"
echo "  sha256  : $SHA256"
echo "  verify  : pg_restore -l $DESTINATION"
