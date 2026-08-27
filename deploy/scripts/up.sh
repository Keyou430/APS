#!/usr/bin/env sh
set -eu

WITH_HERMES=0
for arg in "$@"; do
  case "$arg" in
    --with-hermes) WITH_HERMES=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DEPLOY_ROOT"

initialize_service_key() {
  name=$1
  values=$(sed -n "s/^${name}=//p" .env)
  value=$(printf '%s\n' "$values" | tail -n 1)
  count=$(grep -c "^${name}=" .env || true)
  needs_update=0
  if [ -z "$value" ]; then
    needs_update=1
    command -v openssl >/dev/null 2>&1 || {
      echo "openssl is required to generate ${name}." >&2
      exit 1
    }
    value=$(openssl rand -hex 32)
  fi
  if [ "$count" -ne 1 ]; then
    needs_update=1
  fi
  if [ "$needs_update" -eq 1 ]; then
    temporary=$(mktemp "./.env.XXXXXX")
    awk -v key="$name" -v replacement="${name}=${value}" '
      index($0, key "=") == 1 { if (!seen++) print replacement; next }
      { print }
      END { if (!seen) print replacement }
    ' .env > "$temporary"
    mv "$temporary" .env
  fi
}

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created deploy/.env. Replace the placeholder passwords and JWT secret, then run again." >&2
  exit 1
fi

if grep -Eq '^(POSTGRES_PASSWORD|JWT_SECRET_KEY|ADMIN_PASSWORD)=change-this' .env; then
  echo "Replace all change-this secrets in deploy/.env before starting." >&2
  exit 1
fi

rag_enabled=$(sed -n 's/^RAG_EMBEDDING_ENABLED=//p' .env | tail -n 1)
app_env=$(sed -n 's/^APP_ENV=//p' .env | tail -n 1)
case "${app_env:-container}" in
  production|prod|staging)
    [ "$rag_enabled" = "true" ] || {
      echo "RAG_EMBEDDING_ENABLED=true is required in staging/production." >&2
      exit 1
    }
    ;;
esac

compose_profile=""
app_services="api web"
if [ "$rag_enabled" = "true" ]; then
  for name in RAG_EMBEDDING_API_URL RAG_EMBEDDING_API_KEY RAG_QUERY_EMBEDDING_TOKEN RAG_QUERY_AUDIT_HMAC_KEY; do
    value=$(sed -n "s/^${name}=//p" .env | tail -n 1)
    case "$value" in
      ""|change-this*|replace-with*|development-only-change-me|admin123)
        echo "Set a non-placeholder ${name} before enabling RAG embedding." >&2
        exit 1
        ;;
    esac
  done
  compose_profile="--profile rag"
  app_services="rag-worker api web"
fi

initialize_service_key RAG_QUERY_EMBEDDING_TOKEN

COMPOSE_FILES="-f compose.yaml"
if [ "$WITH_HERMES" -eq 1 ]; then
  initialize_service_key HERMES_API_SERVER_KEY
  COMPOSE_FILES="$COMPOSE_FILES -f compose.hermes.yaml"
fi

if [ "$WITH_HERMES" -eq 1 ]; then
  sh ./scripts/prepare-hermes-source.sh
  docker compose --env-file .env $compose_profile $COMPOSE_FILES up -d db hermes --build --wait --wait-timeout 180
  ./scripts/refresh-hermes-sandbox-attestation.sh
  docker compose --env-file .env $compose_profile $COMPOSE_FILES up -d $app_services --build --wait --wait-timeout 180
else
  docker compose --env-file .env $compose_profile $COMPOSE_FILES up -d --build --wait --wait-timeout 180
fi
docker compose --env-file .env $COMPOSE_FILES ps

APP_PORT=$(sed -n 's/^APP_PORT=//p' .env)
echo "Hermes Platform: http://localhost:${APP_PORT:-8080}"
echo "Swagger UI:     http://localhost:${APP_PORT:-8080}/docs"
