#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DEPLOY_ROOT"

env_value() {
  sed -n "s/^${1}=//p" .env | tail -n 1 | tr -d '\r'
}

compose() {
  docker compose --profile rag --env-file .env \
    -f compose.yaml -f compose.hermes.yaml -f compose.single-host.yaml "$@"
}

sh ./scripts/preflight-single-host.sh
cron_key=$(env_value HERMES_CRON_INTERNAL_KEY)
env HERMES_CRON_INTERNAL_KEY="$cron_key" python3 ./scripts/render-single-host-config.py \
  --source ./hermes/config.yaml \
  --output ./.runtime/single-host/hermes-agent-config.yaml

sh ./scripts/prepare-hermes-source.sh
compose up -d db hermes --build --wait --wait-timeout 300
compose build api
COMPOSE_OVERRIDE_FILE=compose.single-host.yaml sh ./scripts/refresh-hermes-sandbox-attestation.sh
compose up -d --build --wait --wait-timeout 300
sh ./scripts/verify-single-host-deployment.sh
install -m 0600 .env ./.runtime/single-host/last-known-good.env

app_port=$(env_value APP_PORT)
printf 'single-host-deployment=passed url=http://%s:%s next="sh scripts/rebind-feishu.sh user"\n' \
  "$(hostname -I | awk '{print $1}')" "${app_port:-8080}"
