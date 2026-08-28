#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DEPLOY_ROOT"

fail() {
  echo "single-host-deployment-gate=failed check=$1" >&2
  exit 1
}

env_value() {
  sed -n "s/^${1}=//p" .env | tail -n 1 | tr -d '\r'
}

compose() {
  docker compose --profile rag --env-file .env \
    -f compose.yaml -f compose.hermes.yaml -f compose.single-host.yaml "$@"
}

merged=$(mktemp)
trap 'rm -f "$merged"' EXIT
compose config > "$merged"
for forbidden in 192.168.3.107 development-only; do
  if grep -q "$forbidden" "$merged"; then
    fail merged-config-forbidden-value
  fi
done
runtime_config=.runtime/single-host/hermes-agent-config.yaml
test -s "$runtime_config" || fail runtime-config-missing
grep -q 'PLATFORM_API_URL: http://api:8000' "$runtime_config" \
  || fail runtime-platform-api-url
if grep -q 'http://127.0.0.1:8000' "$runtime_config"; then
  fail runtime-platform-api-loopback
fi

running=$(compose ps --status running --services)
for service in db api web rag-worker hermes hermes-knowledge hermes-cron-bridge \
  pipeline-worker pipeline-approval-worker delivery-worker; do
  echo "$running" | grep -qx "$service" || fail "service-$service"
done

app_port=$(env_value APP_PORT)
curl --fail --silent --show-error "http://127.0.0.1:${app_port:-8080}/ready" >/dev/null \
  || fail web-ready
curl --fail --silent --show-error "http://127.0.0.1:${app_port:-8080}/health" >/dev/null \
  || fail api-health
compose exec -T api alembic current | grep -q '(head)' || fail migration-head

for endpoint in 'db 5432' 'hermes 8642' 'hermes-knowledge 8643' \
  'rag-worker 8091' 'hermes-cron-bridge 8765'; do
  # Each constant intentionally expands into exactly one service and one port.
  # shellcheck disable=SC2086
  set -- $endpoint
  if compose port "$1" "$2" 2>/dev/null | grep -q .; then
    fail "host-port-$1"
  fi
done

if [ "$(id -u)" -eq 0 ]; then
  sh ./scripts/verify-single-host-runner.sh
else
  sudo sh ./scripts/verify-single-host-runner.sh
fi

if [ "${VERIFY_LARK_AUTH:-false}" = true ]; then
  compose exec -T -u 10000:10000 hermes lark-cli auth status --json --verify \
    >/dev/null || fail lark-auth-status
  compose exec -T -u 10000:10000 hermes \
    lark-cli im +chat-list --as user --format json >/dev/null || fail lark-chat-read
fi

printf 'single-host-deployment-gate=passed lark_required=%s\n' "${VERIFY_LARK_AUTH:-false}"
