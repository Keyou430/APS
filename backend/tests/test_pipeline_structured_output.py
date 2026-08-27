import pytest

from app.services.pipeline_executor import _parse_structured_output


def test_parses_json_code_fence_without_treating_prose_as_output() -> None:
    payload = _parse_structured_output(
        '结果如下：\n```json\n{"title":"T","markdown":"M","summary":"S","sources":[]}\n```'
    )

    assert payload == {"title": "T", "markdown": "M", "summary": "S", "sources": []}


def test_rejects_prose_or_partial_json() -> None:
    with pytest.raises(ValueError, match="structured_output_invalid"):
        _parse_structured_output("这里有一个链接 https://example.com，但没有结构化结果")
