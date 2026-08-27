from app.services.pipeline_executor import _collect_response_evidence


def test_collects_web_evidence_from_function_call_output() -> None:
    correlation_id = "provider-evidence-correlation"
    body = {
        "output": [
            {
                "type": "function_call",
                "name": "web_search",
                "call_id": "call-1",
                "arguments": '{"query":"latest AI news"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": (
                    '{"success":true,"data":{"web":[{'
                    '"provider":"exa","url":"https://example.com/news",'
                    '"title":"Source","published_at":"2026-08-22T00:00:00Z",'
                    '"searched_at":"2026-08-23T00:00:00Z",'
                    '"source_id":"exa-1"}]}}'
                ),
            },
        ]
    }

    evidence = _collect_response_evidence(body, correlation_id=correlation_id)

    assert len(evidence) == 1
    assert evidence[0].provider == "exa"
    assert evidence[0].correlation_id == correlation_id
    assert evidence[0].source_id == "exa-1"


def test_ignores_unpaired_function_call_output() -> None:
    body = {
        "output": [
            {
                "type": "function_call_output",
                "call_id": "unknown-call",
                "output": '{"data":{"web":[{"url":"https://example.com"}]}}',
            }
        ]
    }

    assert _collect_response_evidence(body, correlation_id="corr") == []


def test_collects_web_evidence_from_hermes_untrusted_result_envelope() -> None:
    body = {
        "output": [
            {"type": "function_call", "name": "web_search", "call_id": "call-2"},
            {
                "type": "function_call_output",
                "call_id": "call-2",
                "output": (
                    '<untrusted_tool_result source="web_search">\n'
                    '{"success":true,"data":{"web":[{'
                    '"provider":"exa","url":"https://example.com/enveloped",'
                    '"title":"Enveloped source","published_at":"2026-08-22T00:00:00Z",'
                    '"searched_at":"2026-08-23T00:00:00Z"}]}}\n'
                    "</untrusted_tool_result>"
                ),
            },
        ]
    }

    evidence = _collect_response_evidence(body, correlation_id="corr-envelope")

    assert len(evidence) == 1
    assert evidence[0].url == "https://example.com/enveloped"
