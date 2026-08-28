#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BACKUP_ROOT="$DEPLOY_ROOT/backups"
cd "$DEPLOY_ROOT"

fail() {
  echo "feishu-rebind=failed check=$1" >&2
  exit 1
}

env_value() {
  sed -n "s/^${1}=//p" .env | tail -n 1 | tr -d '\r'
}

require_env() {
  value=$(env_value "$1")
  case "$value" in
    ''|change-this*|replace-with*|development-only*|your-*) fail "$1" ;;
  esac
}

verify_app_credentials() {
  label=$1
  app_id=$2
  app_secret=$3
  domain=$(env_value FEISHU_DOMAIN)
  [ -n "$domain" ] || domain=feishu
  if ! FEISHU_VERIFY_DOMAIN="$domain" FEISHU_VERIFY_APP_ID="$app_id" \
    FEISHU_VERIFY_APP_SECRET="$app_secret" python3 - <<'PY'
import json
import os
from urllib.request import Request, urlopen

domain = os.environ["FEISHU_VERIFY_DOMAIN"]
hosts = {"feishu": "open.feishu.cn", "lark": "open.larksuite.com"}
host = hosts.get(domain)
if host is None:
    raise SystemExit(1)
body = json.dumps(
    {
        "app_id": os.environ["FEISHU_VERIFY_APP_ID"],
        "app_secret": os.environ["FEISHU_VERIFY_APP_SECRET"],
    }
).encode("utf-8")
request = Request(
    f"https://{host}/open-apis/auth/v3/tenant_access_token/internal",
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
try:
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception:
    raise SystemExit(1) from None
if payload.get("code") != 0 or not payload.get("tenant_access_token"):
    raise SystemExit(1)
PY
  then
    echo "feishu-rebind=failed check=$label-credentials" >&2
    return 1
  fi
}

compose() {
  docker compose --profile rag --env-file .env \
    -f compose.yaml -f compose.hermes.yaml -f compose.single-host.yaml "$@"
}

backup_user_auth() {
  archive=$1
  mkdir -p "$BACKUP_ROOT"
  compose run --rm --no-deps --user 0:0 \
    -v "$BACKUP_ROOT:/backup" --entrypoint /bin/sh hermes -ec \
    "umask 077; tar -C /opt/data/.lark-cli -czf /backup/$(basename "$archive") ."
  test -s "$archive" || fail user-backup
  chmod 0600 "$archive" 2>/dev/null || true
}

restore_user_auth() {
  archive=$(realpath "$1" 2>/dev/null) || fail restore-archive
  backup_root=$(realpath "$BACKUP_ROOT")
  case "$archive" in
    "$backup_root"/*) ;;
    *) fail restore-path ;;
  esac
  test -s "$archive" || fail restore-archive
  compose stop hermes hermes-cron-bridge
  compose run --rm --no-deps --user 0:0 \
    -v "$BACKUP_ROOT:/backup:ro" --entrypoint /bin/sh hermes -ec \
    "find /opt/data/.lark-cli -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -C /opt/data/.lark-cli -xzf /backup/$(basename "$archive") && chown -R 10000:10000 /opt/data/.lark-cli"
  compose up -d hermes hermes-cron-bridge api --wait --wait-timeout 180
}

mode=${1:-}
case "$mode" in
  bot)
    for key in FEISHU_APP_ID FEISHU_APP_SECRET PLATFORM_FEISHU_APP_ID PLATFORM_FEISHU_APP_SECRET; do
      require_env "$key"
    done
    mkdir -p "$BACKUP_ROOT"
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    rollback_env="$BACKUP_ROOT/env-before-feishu-$timestamp"
    test -s .runtime/single-host/last-known-good.env || fail last-known-good-missing
    install -m 0600 .runtime/single-host/last-known-good.env "$rollback_env"
    if ! verify_app_credentials bot "$(env_value FEISHU_APP_ID)" "$(env_value FEISHU_APP_SECRET)" \
      || ! verify_app_credentials platform "$(env_value PLATFORM_FEISHU_APP_ID)" \
        "$(env_value PLATFORM_FEISHU_APP_SECRET)"; then
      install -m 0600 "$rollback_env" .env
      fail bot-credential-rollback
    fi
    if compose up -d --no-deps --force-recreate hermes api delivery-worker \
      --wait --wait-timeout 180 && sh ./scripts/verify-single-host-deployment.sh; then
      install -m 0600 .env .runtime/single-host/last-known-good.env
    else
      install -m 0600 "$rollback_env" .env
      compose up -d --no-deps --force-recreate hermes api delivery-worker \
        --wait --wait-timeout 180 || true
      fail bot-rollback
    fi
    printf 'feishu-rebind=passed mode=bot env_backup=%s\n' \
      "$rollback_env"
    ;;
  user)
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    archive="$BACKUP_ROOT/lark-cli-before-$timestamp.tar.gz"
    compose stop hermes hermes-cron-bridge
    backup_user_auth "$archive"
    compose run --rm --no-deps --user 10000:10000 --entrypoint lark-cli \
      hermes auth logout --json >/dev/null 2>&1 || true
    if ! compose run --rm --no-deps --user 10000:10000 --entrypoint lark-cli \
      hermes auth login --domain "${LARK_AUTH_DOMAINS:-all}"; then
      restore_user_auth "$archive"
      fail user-login
    fi
    if ! compose up -d hermes hermes-cron-bridge api --wait --wait-timeout 180 \
      || ! VERIFY_LARK_AUTH=true sh ./scripts/verify-single-host-deployment.sh; then
      restore_user_auth "$archive"
      fail user-rollback
    fi
    printf 'feishu-rebind=passed mode=user backup=%s\n' "$archive"
    ;;
  restore-user)
    [ "$#" -eq 2 ] || fail restore-usage
    restore_user_auth "$2"
    VERIFY_LARK_AUTH=true sh ./scripts/verify-single-host-deployment.sh
    printf 'feishu-rebind=passed mode=restore-user archive=%s\n' "$2"
    ;;
  *)
    echo "Usage: $0 bot | user | restore-user <backup.tar.gz>" >&2
    exit 2
    ;;
esac
