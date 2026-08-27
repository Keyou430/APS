#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE_DIR="$DEPLOY_ROOT/.runtime/hermes-source"

grep -q 'DINGTALK_CLIENT_ID:' "$DEPLOY_ROOT/compose.hermes.yaml"
grep -q 'DINGTALK_ALLOW_ALL_USERS.*false' "$DEPLOY_ROOT/compose.hermes.yaml"
grep -q 'DINGTALK_CARD_TEMPLATE_ID:' "$DEPLOY_ROOT/compose.hermes.yaml"
grep -q 'DINGTALK_REQUIRE_MENTION.*true' "$DEPLOY_ROOT/compose.hermes.yaml"
grep -q '^_config_version: 33$' "$DEPLOY_ROOT/hermes/config.yaml"
grep -q '^_config_version: 33$' "$DEPLOY_ROOT/hermes/config.knowledge.yaml"
grep -q '  dingtalk:' "$DEPLOY_ROOT/hermes/config.yaml"
test "$(grep -c '    - skills' "$DEPLOY_ROOT/hermes/config.yaml")" -ge 2
grep -q '星纪年AI工作平台' "$DEPLOY_ROOT/hermes/SOUL.md"
grep -q 'name: hr-weekly-report' "$DEPLOY_ROOT/hermes/skills/hr-weekly-report/SKILL.md"
grep -q '钉钉会话中完成文本交付' "$DEPLOY_ROOT/hermes/skills/hr-weekly-report/SKILL.md"

if [ -d "$SOURCE_DIR" ]; then
  grep -q -- '--extra dingtalk' "$SOURCE_DIR/Dockerfile"
  grep -q 'DINGTALK_CARD_TEMPLATE_ID' "$SOURCE_DIR/plugins/platforms/dingtalk/adapter.py"
fi

printf 'dingtalk-demo-config=passed\n'
