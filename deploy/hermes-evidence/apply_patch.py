import json
from pathlib import Path


HERMES_ROOT = Path("/opt/hermes")


def replace_once(path: Path, before: str, after: str) -> None:
    source = path.read_text(encoding="utf-8")
    if source.count(before) != 1:
        raise RuntimeError(f"Hermes evidence patch anchor mismatch: {path}")
    path.write_text(source.replace(before, after), encoding="utf-8")


def patch_exa_provider() -> None:
    path = HERMES_ROOT / "plugins/web/exa/provider.py"
    replace_once(
        path,
        "import logging\nimport os\nfrom typing import Any, Dict, List\n",
        "import logging\nimport os\nfrom datetime import UTC, datetime\nfrom typing import Any, Dict, List\n",
    )
    replace_once(
        path,
        '''                    {
                        "url": result.url or "",
                        "title": result.title or "",
                        "description": " ".join(highlights) if highlights else "",
                        "position": i + 1,
                    }
''',
        '''                    {
                        "provider": "exa",
                        "url": result.url or "",
                        "title": result.title or "",
                        "description": " ".join(highlights) if highlights else "",
                        "position": i + 1,
                        "published_at": str(result.published_date or ""),
                        "searched_at": datetime.now(UTC).isoformat(),
                        "source_id": result.id or "",
                    }
''',
    )
    replace_once(
        path,
        '''    try:
        from tools.lazy_deps import ensure as _lazy_ensure

        _lazy_ensure("search.exa", prompt=False)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — lazy_deps surfaces install hints
        raise ImportError(str(exc))

    from exa_py import Exa  # noqa: WPS433 — deliberately lazy
''',
        '''    try:
        from exa_py import Exa  # noqa: WPS433 — deliberately lazy
    except ImportError:
        try:
            from tools.lazy_deps import ensure as _lazy_ensure

            _lazy_ensure("search.exa", prompt=False)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001 — lazy_deps surfaces install hints
            raise ImportError(str(exc))
        from exa_py import Exa  # noqa: WPS433 — deliberately lazy
''',
    )


def patch_api_gateway() -> None:
    path = HERMES_ROOT / "gateway/platforms/api_server.py"
    source = path.read_text(encoding="utf-8")
    if "def _parse_tool_result(raw_result: object)" not in source:
        marker = "\n\n    def _make_run_event_callback"
        if source.count(marker) != 1:
            raise RuntimeError(f"Hermes evidence patch anchor mismatch: {path}")
        source = source.replace(
            marker,
            '''\n\n    @staticmethod\n    def _parse_tool_result(raw_result: object) -> dict:\n        if isinstance(raw_result, dict):\n            return raw_result\n        if not isinstance(raw_result, str):\n            raw_result = str(raw_result)\n        decoder = json.JSONDecoder()\n        for index, char in enumerate(raw_result):\n            if char != "{":\n                continue\n            try:\n                parsed, _ = decoder.raw_decode(raw_result[index:])\n            except json.JSONDecodeError:\n                continue\n            if isinstance(parsed, dict) and ("data" in parsed or "success" in parsed):\n                return parsed\n        return {}\n\n    def _make_run_event_callback''',
        )
        path.write_text(source, encoding="utf-8")
    replace_once(
        path,
        '''            elif event_type == "tool.completed":
                _push({
                    "event": "tool.completed",
                    "run_id": run_id,
                    "timestamp": ts,
                    "tool": tool_name,
                    "duration": round(kwargs.get("duration", 0), 3),
                    "error": kwargs.get("is_error", False),
                })
''',
        '''            elif event_type == "tool.completed":
                is_error = kwargs.get("is_error", False)
                _push({
                    "event": "tool.completed",
                    "run_id": run_id,
                    "timestamp": ts,
                    "tool": tool_name,
                    "duration": round(kwargs.get("duration", 0), 3),
                    "error": is_error,
                })
                if tool_name in {"web_search", "web_search_tool"} and not is_error:
                    raw_result = kwargs.get("result")
                    parsed_result = self._parse_tool_result(raw_result)
                    data = parsed_result.get("data") if isinstance(parsed_result, dict) else None
                    results = data.get("web") if isinstance(data, dict) else None
                    if isinstance(results, list):
                        valid_results = [item for item in results if isinstance(item, dict)]
                        providers = {
                            item.get("provider") for item in valid_results
                            if isinstance(item.get("provider"), str) and item.get("provider")
                        }
                        _push({
                            "event": "tool.web_search",
                            "run_id": run_id,
                            "timestamp": ts,
                            "provider": next(iter(providers)) if len(providers) == 1 else "hermes-web",
                            "results": valid_results,
                        })
''',
    )


def _parse_tool_result(raw_result: object) -> dict:
    if isinstance(raw_result, dict):
        return raw_result
    if not isinstance(raw_result, str):
        raw_result = str(raw_result)
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw_result):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw_result[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("data" in parsed or "success" in parsed):
            return parsed
    return {}


if __name__ == "__main__":
    patch_exa_provider()
    patch_api_gateway()
