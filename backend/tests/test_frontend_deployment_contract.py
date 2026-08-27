from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).parents[2]


def test_external_guest_flag_is_forwarded_to_the_frontend_build() -> None:
    compose = yaml.safe_load((REPOSITORY_ROOT / "deploy" / "compose.yaml").read_text())
    web_build_args = compose["services"]["web"]["build"]["args"]
    assert web_build_args["VITE_FEATURE_EXTERNAL_GUESTS"] == "${FEATURE_EXTERNAL_GUESTS:-false}"

    dockerfile = (REPOSITORY_ROOT / "deploy" / "frontend.Dockerfile").read_text()
    assert "ARG VITE_FEATURE_EXTERNAL_GUESTS=false" in dockerfile
    assert "ENV VITE_FEATURE_EXTERNAL_GUESTS=${VITE_FEATURE_EXTERNAL_GUESTS}" in dockerfile


def test_smtp_invitation_settings_are_forwarded_to_the_api_only() -> None:
    compose = yaml.safe_load((REPOSITORY_ROOT / "deploy" / "compose.yaml").read_text())
    api_environment = compose["services"]["api"]["environment"]
    for name in (
        "GUEST_INVITATION_PUBLIC_BASE_URL",
        "GUEST_INVITATION_RECIPIENT_ALLOWLIST",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
        "SMTP_TIMEOUT_SECONDS",
    ):
        assert name in api_environment
        assert name not in compose["services"]["web"].get("environment", {})
