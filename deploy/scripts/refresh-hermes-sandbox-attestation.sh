#!/usr/bin/env sh
set -eu

DEPLOY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DEPLOY_ROOT"

attestation_path=${SANDBOX_ATTESTATION_FILE:-$DEPLOY_ROOT/.runtime/sandbox-attestation.json}
mkdir -p "$(dirname "$attestation_path")"
rm -f "$attestation_path"
temporary_attestation=$(mktemp "${attestation_path}.tmp.XXXXXX")
verifier_output=$(mktemp "${attestation_path}.verify.XXXXXX")
trap 'rm -f "$temporary_attestation" "$verifier_output"' EXIT

compose="docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml"
if ! sh -c "$compose exec -T -u 10000:10000 hermes sh -s < scripts/verify-hermes-docker-backend.sh" \
  > "$verifier_output"; then
  echo "sandbox-attestation=failed check=backend-verifier" >&2
  exit 1
fi
sed -n '/^{/p' "$verifier_output" > "$temporary_attestation"
test -s "$temporary_attestation"

: > "$attestation_path"
sh -c "$compose run --rm --no-deps -T api python scripts/validate_sandbox_attestation.py" \
  < "$temporary_attestation" >/dev/null
mv "$temporary_attestation" "$attestation_path"
rm -f "$verifier_output"
trap - EXIT
printf 'sandbox-attestation=passed path=%s\n' "$attestation_path"
