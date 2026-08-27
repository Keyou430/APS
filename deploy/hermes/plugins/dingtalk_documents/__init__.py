from __future__ import annotations

import os

from .client import DingTalkApiError, DingTalkDocumentClient


SEARCH_SCHEMA = {
    "name": "dingtalk_search_documents",
    "description": (
        "Search the linked DingTalk account's documents by title keyword. "
        "Use this when the user explicitly asks to find, list, or access DingTalk documents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Document title keyword."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 8},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

CHECK_SCHEMA = {
    "name": "dingtalk_check_document_permissions",
    "description": (
        "Run read-only DingTalk API probes and return the exact missing scopes for document "
        "search and document content access. Use this first when the user asks which permissions "
        "must be enabled."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

READ_SCHEMA = {
    "name": "dingtalk_read_document",
    "description": (
        "Read one DingTalk document as Markdown using the document_id returned by "
        "dingtalk_search_documents. This tool is read-only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "description": "DingTalk dentry UUID returned by dingtalk_search_documents.",
            }
        },
        "required": ["document_id"],
        "additionalProperties": False,
    },
}


def _available() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in (
            "DINGTALK_DOC_CLIENT_ID",
            "DINGTALK_DOC_CLIENT_SECRET",
            "DINGTALK_DOC_OPERATOR_ID",
        )
    )


def _client() -> DingTalkDocumentClient:
    allowed_hosts = tuple(
        host.strip()
        for host in os.getenv("DINGTALK_ALLOWED_RESOURCE_HOSTS", "").split(",")
        if host.strip()
    )
    return DingTalkDocumentClient(
        client_id=os.environ["DINGTALK_DOC_CLIENT_ID"],
        client_secret=os.environ["DINGTALK_DOC_CLIENT_SECRET"],
        operator_id=os.environ["DINGTALK_DOC_OPERATOR_ID"],
        allowed_resource_hosts=allowed_hosts,
    )


def _failure(error: Exception) -> str:
    from tools.registry import tool_error, tool_result

    if isinstance(error, DingTalkApiError):
        return tool_result(error.to_result())
    if isinstance(error, ValueError):
        return tool_error(str(error))
    return tool_error(f"DingTalk document tool failed: {type(error).__name__}")


async def _search(args: dict, **_kwargs) -> str:
    from tools.registry import tool_result

    try:
        result = await _client().search_documents(
            str(args.get("query") or ""),
            limit=int(args.get("limit") or 8),
        )
        return tool_result(result)
    except Exception as error:
        return _failure(error)


async def _check_permissions(_args: dict, **_kwargs) -> str:
    from tools.registry import tool_result

    try:
        return tool_result(await _client().check_permissions())
    except Exception as error:
        return _failure(error)


async def _read(args: dict, **_kwargs) -> str:
    from tools.registry import tool_result

    try:
        result = await _client().read_document(str(args.get("document_id") or ""))
        return tool_result(result)
    except Exception as error:
        return _failure(error)


def register(ctx) -> None:
    ctx.register_tool(
        name="dingtalk_check_document_permissions",
        toolset="dingtalk_documents",
        schema=CHECK_SCHEMA,
        handler=_check_permissions,
        check_fn=_available,
        is_async=True,
        emoji="🔐",
    )
    ctx.register_tool(
        name="dingtalk_search_documents",
        toolset="dingtalk_documents",
        schema=SEARCH_SCHEMA,
        handler=_search,
        check_fn=_available,
        is_async=True,
        emoji="🔎",
    )
    ctx.register_tool(
        name="dingtalk_read_document",
        toolset="dingtalk_documents",
        schema=READ_SCHEMA,
        handler=_read,
        check_fn=_available,
        is_async=True,
        emoji="📄",
    )
