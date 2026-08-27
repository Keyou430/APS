import importlib.util
import os
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "scripts" / "verify-hermes-web-config.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_hermes_web_config", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_primary_web_toolset_is_exposed_and_knowledge_stays_fail_closed():
    config = yaml.safe_load((ROOT / "deploy/hermes/config.yaml").read_text(encoding="utf-8"))
    knowledge = yaml.safe_load(
        (ROOT / "deploy/hermes/config.knowledge.yaml").read_text(encoding="utf-8")
    )
    assert config["platform_toolsets"]["api_server"] == [
        "terminal",
        "file",
        "skills",
        "dingtalk_documents",
        "web",
    ]
    assert knowledge["platform_toolsets"]["api_server"] == ["dingtalk_documents"]
    assert config["terminal"]["docker_network"] is False


def test_formal_primary_web_and_feishu_are_enabled_while_knowledge_is_closed():
    config = yaml.safe_load(
        (ROOT / "deploy/hermes-formal/config.yaml").read_text(encoding="utf-8")
    )
    knowledge = yaml.safe_load(
        (ROOT / "deploy/hermes-formal/config.knowledge.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert config["platform_toolsets"]["api_server"] == ["web"]
    assert config["platform_toolsets"]["feishu"] == ["web"]
    assert knowledge["platform_toolsets"]["api_server"] == []


def test_web_provider_environment_is_injected_only_into_primary_hermes():
    compose = (ROOT / "deploy/compose.hermes.yaml").read_text(encoding="utf-8")
    hermes_block, knowledge_block = compose.split("  hermes-knowledge:", maxsplit=1)
    for key in load_verifier().PROVIDER_KEYS:
        assert f"{key}: ${{{key}:-}}" in hermes_block
        assert key not in knowledge_block


def test_feishu_channel_environment_is_injected_only_into_primary_gateway():
    compose = (ROOT / "deploy/compose.hermes.yaml").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    hermes_block, knowledge_block = compose.split("  hermes-knowledge:", maxsplit=1)
    expected = {
        "FEISHU_APP_ID": "${FEISHU_APP_ID:-}",
        "FEISHU_APP_SECRET": "${FEISHU_APP_SECRET:-}",
        "FEISHU_DOMAIN": "${FEISHU_DOMAIN:-feishu}",
        "FEISHU_CONNECTION_MODE": "${FEISHU_CONNECTION_MODE:-websocket}",
        "FEISHU_ALLOWED_USERS": "${FEISHU_ALLOWED_USERS:-}",
        "FEISHU_ALLOW_ALL_USERS": "${FEISHU_ALLOW_ALL_USERS:-false}",
        "FEISHU_REQUIRE_MENTION": "${FEISHU_REQUIRE_MENTION:-true}",
        "FEISHU_GROUP_POLICY": "${FEISHU_GROUP_POLICY:-allowlist}",
        "FEISHU_HOME_CHANNEL": "${FEISHU_HOME_CHANNEL:-}",
    }
    for key, value in expected.items():
        assert f"{key}: {value}" in hermes_block
        assert key not in knowledge_block
        assert f"{key}=" in env_example


def test_formal_provider_and_feishu_environment_are_primary_only():
    compose = (ROOT / "deploy/compose.formal-hermes.yaml").read_text(encoding="utf-8")
    hermes_block, remainder = compose.split("  hermes-knowledge:", maxsplit=1)
    # Isolate the knowledge gateway block: the remainder also contains later
    # services (pipeline-worker, platform delivery-worker) that legitimately
    # declare their own environment.
    knowledge_block = remainder.split("  api:", maxsplit=1)[0]
    assert "XIAOMI_BASE_URL: ${XIAOMI_BASE_URL:-https://api.xiaomimimo.com/v1}" in hermes_block
    assert "XIAOMI_BASE_URL: ${XIAOMI_BASE_URL:-https://api.xiaomimimo.com/v1}" in knowledge_block
    for key in load_verifier().PROVIDER_KEYS:
        assert f"{key}: ${{{key}:-}}" in hermes_block
        assert key not in knowledge_block
    for key in (
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_CONNECTION_MODE",
        "FEISHU_ALLOWED_USERS",
        "FEISHU_ALLOW_ALL_USERS",
        "FEISHU_REQUIRE_MENTION",
        "FEISHU_GROUP_POLICY",
    ):
        assert f"{key}:" in hermes_block
        assert key not in knowledge_block


def test_platform_delivery_worker_uses_dedicated_feishu_credentials():
    """The platform send authority must not reuse the Hermes bot credentials."""
    compose = (ROOT / "deploy/compose.formal-hermes.yaml").read_text(encoding="utf-8")
    delivery_block = compose.split("  delivery-worker:", maxsplit=1)[1]
    assert "PLATFORM_FEISHU_APP_ID" in delivery_block
    assert "PLATFORM_FEISHU_APP_SECRET" in delivery_block
    assert "RAG_QUERY_AUDIT_HMAC_KEY" in delivery_block
    # Platform worker consumes its own outbox; it never talks to Hermes.
    assert "HERMES_API_URL" not in delivery_block


def test_formal_api_gets_only_the_feishu_reader_credentials_and_access_policy():
    compose = (ROOT / "deploy/compose.formal-hermes.yaml").read_text(encoding="utf-8")
    api_block = compose.split("  api:", maxsplit=1)[1].split(
        "  pipeline-worker:", maxsplit=1
    )[0]
    assert (
        "FEISHU_DELIVERY_CONFIGURED: ${PLATFORM_FEISHU_DELIVERY_CONFIGURED:-false}"
        in api_block
    )
    expected = {
        "FEISHU_READ_CONFIGURED": "${PLATFORM_FEISHU_READ_CONFIGURED:-false}",
        "FEISHU_APP_ID": "${PLATFORM_FEISHU_APP_ID:-}",
        "FEISHU_APP_SECRET": "${PLATFORM_FEISHU_APP_SECRET:-}",
        "FEISHU_READ_ALLOWED_ORGANIZATION_IDS": "${PLATFORM_FEISHU_READ_ALLOWED_ORGANIZATION_IDS:-}",
        "FEISHU_READ_ALLOWED_DOCUMENT_TOKENS": "${PLATFORM_FEISHU_READ_ALLOWED_DOCUMENT_TOKENS:-}",
        "FEISHU_READ_ALLOWED_CHAT_IDS": "${PLATFORM_FEISHU_READ_ALLOWED_CHAT_IDS:-}",
    }
    for key, value in expected.items():
        assert f"{key}: {value}" in api_block


def test_formal_compose_publishes_feishu_base_table_reader_contract():
    compose = (ROOT / "deploy/compose.formal-hermes.yaml").read_text(
        encoding="utf-8"
    )
    env_example = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    readme = (ROOT / "deploy/README.md").read_text(encoding="utf-8")
    api_block = compose.split("  api:", maxsplit=1)[1].split(
        "  pipeline-worker:", maxsplit=1
    )[0]

    assert (
        "FEISHU_READ_ALLOWED_BASE_TABLES: "
        "${PLATFORM_FEISHU_READ_ALLOWED_BASE_TABLES:-}"
    ) in api_block
    assert "PLATFORM_FEISHU_READ_ALLOWED_BASE_TABLES=" in env_example
    for required_instruction in (
        "`organization_id:app_token:table_id`",
        "`bitable:app:readonly`",
        "target Base application",
        "up -d --build",
        "unlisted Base table",
    ):
        assert required_instruction in readme


def test_formal_gateways_use_the_auditable_web_evidence_image():
    compose = (ROOT / "deploy/compose.formal-hermes.yaml").read_text(encoding="utf-8")
    hermes_block, remainder = compose.split("  hermes-knowledge:", maxsplit=1)
    knowledge_block = remainder.split("  api:", maxsplit=1)[0]
    image_reference = (
        "image: ${HERMES_EVIDENCE_IMAGE:-agent-platform-hermes-evidence:v2026.7.7.2}"
    )
    assert image_reference in hermes_block
    assert image_reference in knowledge_block
    assert "dockerfile: hermes-evidence/Dockerfile" in hermes_block

    dockerfile = (ROOT / "deploy/hermes-evidence/Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "ARG HERMES_BASE_IMAGE=hermes-agent:v2026.7.7.2" in dockerfile
    assert "uv pip install --python /opt/hermes/.venv/bin/python3 exa-py" in dockerfile
    assert "python /tmp/apply_web_evidence_patch.py" in dockerfile


def test_hermes_evidence_patch_emits_only_provider_tool_results():
    patch = (ROOT / "deploy/hermes-evidence/apply_patch.py").read_text(
        encoding="utf-8"
    )
    for field in ("provider", "published_at", "searched_at", "source_id"):
        assert f'"{field}"' in patch
    assert '"event": "tool.web_search"' in patch
    assert 'tool_name in {"web_search", "web_search_tool"}' in patch
    assert "kwargs.get(\"result\")" in patch
    assert "_parse_tool_result(raw_result)" in patch
    assert "from exa_py import Exa" in patch
    assert "_lazy_ensure(\"search.exa\"" in patch
    assert "Hermes evidence patch anchor mismatch" in patch


def test_hermes_image_bakes_locked_dingtalk_and_feishu_gateway_extras():
    prepare = (ROOT / "deploy/scripts/prepare-hermes-source.sh").read_text(
        encoding="utf-8"
    )
    assert "--extra dingtalk --extra feishu" in prepare
    assert "grep -q -- '--extra dingtalk --extra feishu'" in prepare


def test_web_tool_definition_contract_and_no_secret_values():
    verifier = load_verifier()
    assert verifier.tool_definitions(["web"]) == {"web_search", "web_extract"}
    assert verifier.tool_definitions(["search"]) == {"web_search"}
    tracked = "\n".join(
        path.read_text(encoding="utf-8")
        for directory in (ROOT / "deploy/hermes", ROOT / "deploy/hermes-formal")
        for path in directory.glob("*.yaml")
    )
    for key in verifier.PROVIDER_KEYS:
        assert f"{key}=" not in tracked


def test_without_provider_credentials_fails_closed_without_revealing_values():
    verifier = load_verifier()
    availability = verifier.provider_availability({})
    assert set(availability.values()) == {"absent"}
    assert all(value not in {"", None} for value in availability.values())


@pytest.mark.skipif(
    not any(os.environ.get(key) for key in load_verifier().PROVIDER_KEYS),
    reason="live Web provider credential is an external approval gate",
)
def test_live_web_provider_smoke_is_explicitly_gated():
    pytest.fail("Run the provider-specific live smoke only after credential approval")
