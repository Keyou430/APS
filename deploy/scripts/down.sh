#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DEPLOY_ROOT"
docker compose --env-file .env -f compose.yaml down

