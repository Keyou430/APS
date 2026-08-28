#!/usr/bin/env sh
set -eu

EXPECTED_BRANCH=codex/hermes-platform-full-chain
FULL_CHAIN_BASE_SHA=4c665069236324cfeed1af6479e840cc4458310c
DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$DEPLOY_ROOT/.." && pwd)
ENV_FILE="$DEPLOY_ROOT/.env"

fail() {
  echo "single-host-preflight=failed check=$1" >&2
  exit 1
}

env_value() {
  key=$1
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

require_env() {
  key=$1
  count=$(grep -c "^${key}=" "$ENV_FILE" || true)
  [ "$count" -eq 1 ] || fail "${key}-count"
  value=$(env_value "$key")
  case "$value" in
    ''|change-this*|replace-with*|development-only*|your-*|admin123)
      fail "${key}-placeholder"
      ;;
  esac
}

. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ] || fail ubuntu-24.04-required
[ "$(getconf _NPROCESSORS_ONLN)" -ge 8 ] || fail cpu-minimum
memory_kib=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
[ "$memory_kib" -ge 14680064 ] || fail memory-minimum
available_kib=$(df -Pk "$DEPLOY_ROOT" | awk 'NR == 2 {print $4}')
[ "$available_kib" -ge 15728640 ] || fail disk-minimum

for command in git docker python3 curl openssl ssh sudo; do
  command -v "$command" >/dev/null 2>&1 || fail "command-$command"
done
docker compose version >/dev/null 2>&1 || fail docker-compose
python3 -c 'import yaml' >/dev/null 2>&1 || fail python3-yaml
docker info >/dev/null 2>&1 || fail standard-docker

cd "$PROJECT_ROOT"
[ "$(git branch --show-current)" = "$EXPECTED_BRANCH" ] || fail git-branch
git merge-base --is-ancestor "$FULL_CHAIN_BASE_SHA" HEAD || fail full-chain-base
git diff --quiet --ignore-submodules -- || fail tracked-worktree-dirty
git diff --cached --quiet --ignore-submodules -- || fail index-dirty

[ -f "$ENV_FILE" ] || fail env-file-missing
[ "$(stat -c %a "$ENV_FILE")" = 600 ] || fail env-file-mode
for key in \
  POSTGRES_PASSWORD JWT_SECRET_KEY ADMIN_PASSWORD \
  RAG_EMBEDDING_API_URL RAG_EMBEDDING_API_KEY RAG_QUERY_EMBEDDING_TOKEN \
  RAG_QUERY_AUDIT_HMAC_KEY HERMES_API_SERVER_KEY DEEPSEEK_API_KEY \
  HERMES_CRON_INTERNAL_KEY FEISHU_APP_ID FEISHU_APP_SECRET \
  PLATFORM_FEISHU_APP_ID PLATFORM_FEISHU_APP_SECRET; do
  require_env "$key"
done
[ "$(env_value APP_BIND)" = 0.0.0.0 ] || fail app-bind
[ "$(env_value RAG_EMBEDDING_ENABLED)" = true ] || fail rag-disabled
[ "$(env_value PLATFORM_FEISHU_DELIVERY_CONFIGURED)" = true ] || fail feishu-delivery-disabled
[ "$(env_value PLATFORM_FEISHU_READ_CONFIGURED)" = true ] || fail feishu-read-disabled

if [ "$(id -u)" -eq 0 ]; then
  sh "$DEPLOY_ROOT/scripts/verify-single-host-runner.sh"
else
  sudo sh "$DEPLOY_ROOT/scripts/verify-single-host-runner.sh"
fi

printf 'single-host-preflight=passed branch=%s base=%s disk_kib=%s\n' \
  "$EXPECTED_BRANCH" "$FULL_CHAIN_BASE_SHA" "$available_kib"
