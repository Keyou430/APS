#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUNTIME_ROOT="$DEPLOY_ROOT/.runtime"
SOURCE_DIR="$RUNTIME_ROOT/hermes-source"
MCP_SOURCE_DIR="$DEPLOY_ROOT/../hermes/MCP"
SOURCE_SHA=9de9c25f620ff7f1ce0fd5457d596052d5159596
SOURCE_URL="https://codeload.github.com/NousResearch/hermes-agent/tar.gz/$SOURCE_SHA"

mkdir -p "$RUNTIME_ROOT"
temporary_source=$(mktemp -d "$RUNTIME_ROOT/hermes-source.tmp.XXXXXX")
cleanup() { rm -rf -- "$temporary_source"; }
trap cleanup EXIT

curl -fsSL --retry 2 "$SOURCE_URL" \
  | tar -xz --strip-components=1 -C "$temporary_source"
test -f "$temporary_source/Dockerfile"
test -f "$temporary_source/pyproject.toml"
test -f "$MCP_SOURCE_DIR/pyproject.toml"
test -f "$MCP_SOURCE_DIR/src/hermes_mcp/lark_cli_full.py"
cp -R "$MCP_SOURCE_DIR" "$temporary_source/platform-hermes-mcp"

# Runtime package installation is disabled, so bake the locked messaging extras
# into the immutable image instead of downloading them on first message.
sed -i \
  's/--extra all --extra messaging --extra anthropic/--extra all --extra messaging --extra dingtalk --extra feishu --extra anthropic/' \
  "$temporary_source/Dockerfile"
printf '%s\n' \
  'RUN uv pip install --python /opt/hermes/.venv/bin/python3 --no-cache-dir /opt/hermes/platform-hermes-mcp && npm install -g @larksuite/cli@1.0.90 && lark-cli --version && npm cache clean --force' \
  >> "$temporary_source/Dockerfile"

# Keep optional AI Card identifiers in deploy/.env instead of read-only YAML.
sed -i \
  's/extra.get("robot_code") or self._client_id/extra.get("robot_code") or os.getenv("DINGTALK_ROBOT_CODE", "") or self._client_id/' \
  "$temporary_source/plugins/platforms/dingtalk/adapter.py"
sed -i \
  's/extra.get("card_template_id")/extra.get("card_template_id") or os.getenv("DINGTALK_CARD_TEMPLATE_ID")/' \
  "$temporary_source/plugins/platforms/dingtalk/adapter.py"

grep -q -- '--extra dingtalk --extra feishu' "$temporary_source/Dockerfile"
grep -q 'DINGTALK_CARD_TEMPLATE_ID' "$temporary_source/plugins/platforms/dingtalk/adapter.py"
grep -q '/opt/hermes/.venv/bin/python3 --no-cache-dir /opt/hermes/platform-hermes-mcp' "$temporary_source/Dockerfile"
grep -q '@larksuite/cli@1.0.90' "$temporary_source/Dockerfile"

case "$SOURCE_DIR" in
  "$RUNTIME_ROOT/hermes-source") ;;
  *) echo "hermes-source=failed check=unsafe-runtime-path" >&2; exit 1 ;;
esac
rm -rf -- "$SOURCE_DIR"
mv "$temporary_source" "$SOURCE_DIR"
trap - EXIT
printf 'hermes-source=passed sha=%s\n' "$SOURCE_SHA"
