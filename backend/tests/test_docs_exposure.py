"""Phase D docs-exposure contract tests.

The formal entry must not expose /docs or /openapi.json publicly; exposure is
controlled by EXPOSE_DOCS (default open for local development, disabled in the
formal compose).
"""

from pathlib import Path

from app.main import docs_urls

ROOT = Path(__file__).resolve().parents[2]


def test_docs_urls_gate_openapi_and_swagger() -> None:
    assert docs_urls(True) == {"docs_url": "/docs", "openapi_url": "/openapi.json"}
    assert docs_urls(False) == {"docs_url": None, "openapi_url": None}


def test_main_app_binds_docs_urls_from_helper() -> None:
    from app.main import app
    from app.config import get_settings

    expected = docs_urls(get_settings().expose_docs)
    assert app.docs_url == expected["docs_url"]
    assert app.openapi_url == expected["openapi_url"]


def test_formal_compose_disables_public_docs_exposure() -> None:
    compose = (ROOT / "deploy" / "compose.formal-hermes.yaml").read_text(
        encoding="utf-8"
    )
    api_block = compose.split("  api:", maxsplit=1)[1].split("  pipeline-worker:", 1)[0]
    assert 'EXPOSE_DOCS: "false"' in api_block
