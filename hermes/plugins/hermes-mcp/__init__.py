"""Hermes Plugin — unified knowledge retrieval injection.

Three trigger paths, ONE injection mechanism (pre_llm_call hook):

   /search <query>   → sets pending request → pre_llm_call injects context
   search_knowledge   → AI tool call sets pending request → pre_llm_call injects
   (middleware mode)  → three-source-retrieval plugin handles this independently

All paths inject retrieval results into the LLM request context BEFORE
the LLM sees it — same as the middleware's on_llm_request pattern.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRIEVAL_SERVICE_URL = "http://localhost:8001"

# Thread-safe pending retrieval request.
# Set by /search command or search_knowledge tool.
# Cleared by pre_llm_call hook after injection.
_lock = threading.Lock()
_pending_request: dict[str, Any] | None = None


def _call_retrieval(
    question: str,
    session_id: str = "",
    source: str = "all",
    top_k: int = 3,
) -> dict[str, Any]:
    """Synchronous call to three-source retrieval service."""
    exp_enabled = source in ("all", "experience")
    db_enabled = source in ("all", "database")
    kw_enabled = source in ("all", "knowledge")
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
            resp = client.post(
                f"{RETRIEVAL_SERVICE_URL}/serial-retrieve",
                json={
                    "question": question,
                    "session_id": session_id,
                    "mode": "serial",
                    "options": {
                        "experience": {"enabled": exp_enabled, "top_k": top_k, "similarity_threshold": 0.3},
                        "database": {"enabled": db_enabled, "top_k": top_k, "similarity_threshold": 0.3},
                        "knowledge": {"enabled": kw_enabled, "top_k": top_k, "similarity_threshold": 0.3},
                    },
                },
            )
            resp.raise_for_status()
            return {"success": True, **resp.json()}
    except Exception as exc:
        logger.warning("Plugin retrieval failed: %s", exc)
        return {
            "success": False,
            "experience": {"is_empty": True, "results": []},
            "database": {"is_empty": True, "results": []},
            "knowledge": {"is_empty": True, "results": []},
            "meta": {"error": str(exc)},
        }


def _format_context(result: dict) -> str:
    """Format retrieval results as LLM context block.

    Same format as three-source-retrieval middleware's _build_context_block,
    so the LLM sees identical output regardless of which path triggered retrieval.
    """
    parts = ["\n\n## Three-Source Retrieval Results (auto-injected)\n"]

    e = result.get("experience", {})
    if not e.get("is_empty", True):
        parts.append(f"\n### Experience Library ({len(e.get('results', []))} matches)\n")
        for i, r in enumerate(e.get("results", [])[:3], 1):
            sol = r.get("solution", "")
            parts.append(f"\n[Source E-{i}] score={r.get('score', 0):.2f} | {r.get('source_name', '')}")
            parts.append(f"```\n{sol}\n```\n")
    else:
        parts.append("\n### Experience Library: No relevant results\n")

    d = result.get("database", {})
    if not d.get("is_empty", True):
        parts.append(f"\n### Business Database ({len(d.get('results', []))} records)\n")
        for i, r in enumerate(d.get("results", [])[:3], 1):
            sol = r.get("solution", "")
            parts.append(f"\n[Source D-{i}] score={r.get('score', 0):.2f} | {r.get('source_name', '')}")
            parts.append(f"```\n{sol}\n```\n")
    else:
        parts.append("\n### Business Database: No relevant data\n")

    k = result.get("knowledge", {})
    if not k.get("is_empty", True):
        parts.append(f"\n### Knowledge Base ({len(k.get('results', []))} chunks)\n")
        for i, r in enumerate(k.get("results", [])[:3], 1):
            chunk = r.get("chunk", "")
            parts.append(f"\n[Source K-{i}] score={r.get('score', 0):.2f} | {r.get('source_name', '')}")
            parts.append(f"```\n{chunk}\n```\n")
    else:
        parts.append("\n### Knowledge Base: No relevant documents\n")

    name_map = {"Experience Library": "experience", "Business Database": "database", "Knowledge Base": "knowledge"}
    empties = [name for name, key in name_map.items() if result.get(key, {}).get("is_empty", True)]
    if empties:
        parts.append(f"\nSources with no results: {', '.join(empties)}. Do not fabricate information from these sources.\n")

    # Citation rules: tell LLM to quote original text
    parts.append("\n## CRITICAL RULES (MUST FOLLOW)\n\n")
    parts.append("1. ONLY use the retrieval results above to answer. They are your sole reference.\n")
    parts.append("2. For every point you make, cite the source label (e.g. [Source K-1]) AND include the relevant original text as a blockquote or code block.\n")
    parts.append("3. Structure your answer as: brief summary → then each finding with its source citation and quoted original text.\n")
    parts.append("4. DO NOT use read_file, search_files, or any file tool — the documents are NOT on local disk.\n")
    parts.append("5. DO NOT use web_search or any web tool — do NOT search the internet.\n")
    parts.append("6. If retrieval results are empty or irrelevant, say \"知识库中未找到相关信息\" and STOP. Do not fabricate, guess, or use your own knowledge.\n")

    return "".join(parts)


# ==================================================================
# Central injection point — mirrors middleware's on_llm_request
# ==================================================================

def on_pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    """pre_llm_call hook: inject retrieval context before LLM sees the request.

    Called by Hermes before EVERY LLM call. Only does work when a
    pending retrieval request was set by /search or search_knowledge.

    Returns {"context": "..."} → Hermes injects this into the user message.
    """
    global _pending_request

    with _lock:
        req = _pending_request
        _pending_request = None

    if req is None:
        return None

    logger.info("pre_llm_call: injecting retrieval for: %.80s...", req.get("question", ""))
    result = _call_retrieval(
        question=req["question"],
        session_id=req.get("session_id", ""),
        source=req.get("source", "all"),
        top_k=req.get("top_k", 3),
    )

    if not result.get("success"):
        error = result.get("meta", {}).get("error", "Unknown error")
        logger.warning("pre_llm_call retrieval failed: %s", error)
        return {"context": f"\n\n[Knowledge retrieval failed: {error}]"}

    context = _format_context(result)
    logger.info("pre_llm_call: injected %d chars of context", len(context))
    return {"context": context}


# ==================================================================
# /search slash command — user forces retrieval
# ==================================================================

def _parse_search_args(raw_args: str) -> dict[str, Any] | None:
    """Parse /search arguments, return None if invalid (caller shows usage)."""
    import shlex

    try:
        args_list = shlex.split(raw_args.strip())
    except ValueError:
        args_list = raw_args.strip().split()

    if not args_list:
        return None

    source = "all"
    top_k = 3
    query_parts = []
    i = 0
    while i < len(args_list):
        if args_list[i] == "--source" and i + 1 < len(args_list):
            source = args_list[i + 1]
            i += 2
        elif args_list[i] == "--top" and i + 1 < len(args_list):
            try:
                top_k = max(1, min(10, int(args_list[i + 1])))
            except ValueError:
                pass
            i += 2
        else:
            query_parts.append(args_list[i])
            i += 1

    question = " ".join(query_parts)
    if not question:
        return None

    return {"question": question, "source": source, "top_k": top_k}


def handle_search_command(raw_args: str) -> str:
    """Handle /search <query> command.

    Sets a pending retrieval request. The actual retrieval happens
    in on_pre_llm_call on the NEXT LLM call, injecting results as context.
    """
    global _pending_request

    parsed = _parse_search_args(raw_args)
    if parsed is None:
        return "Usage: /search <query> [--source all|experience|database|knowledge] [--top 1-10]"

    with _lock:
        _pending_request = parsed

    logger.info("/search queued: %.80s... (source=%s, top_k=%d)",
                parsed["question"], parsed["source"], parsed["top_k"])
    return (
        f"Knowledge search queued: \"{parsed['question']}\"\n"
        f"Results will be injected into the next LLM request context.\n"
        f"Now ask your question — the LLM will see the retrieval results automatically."
    )


# ==================================================================
# Tool handlers — AI calls these, they set pending request
# ==================================================================

def handle_search_knowledge(args: dict) -> str:
    """AI-triggered knowledge search via tool call.

    Sets pending request → on_pre_llm_call injects results on next LLM call.
    This mirrors the middleware flow instead of the tool-return-value round-trip.
    """
    global _pending_request

    question = args.get("question", "")
    if not question:
        return "No question provided."

    with _lock:
        _pending_request = {
            "question": question,
            "session_id": args.get("session_id", ""),
            "source": args.get("source", "all"),
            "top_k": args.get("top_k", 3),
        }

    return (
        f"Knowledge search queued: \"{question}\"\n"
        f"Results will be available in the conversation context immediately."
    )


def handle_json_parse(args: dict) -> str:
    """Parse JSON string."""
    import json

    text = args.get("text", "")
    try:
        data = json.loads(text)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON: {exc}"


def handle_base64(args: dict) -> str:
    """Encode/decode Base64."""
    import base64

    text = args.get("text", "")
    action = args.get("action", "encode")

    try:
        if action == "encode":
            return base64.b64encode(text.encode()).decode()
        else:
            try:
                return base64.b64decode(text).decode("utf-8")
            except UnicodeDecodeError:
                raw = base64.b64decode(text)
                return f"[Binary data — {len(raw)} bytes]\n{raw.hex()}"
    except Exception as exc:
        return f"Base64 error: {exc}"


def handle_now(args: dict) -> str:
    """Get current time."""
    from datetime import UTC, datetime

    tz_name = args.get("timezone", "UTC")
    now_utc = datetime.now(UTC)

    try:
        if tz_name.upper() == "UTC":
            now_tz = now_utc
        else:
            from zoneinfo import ZoneInfo
            now_tz = now_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        return f"Unknown timezone: '{tz_name}'. Use 'UTC', 'local', or IANA timezone like 'Asia/Shanghai'."

    return now_tz.strftime("%Y-%m-%d %H:%M:%S %Z")


# ==================================================================
# Plugin Registration
# ==================================================================

def register(ctx) -> None:
    """Register tools, commands, and the pre_llm_call injection hook."""
    logger.info("Registering hermes-mcp plugin (unified retrieval injection)")

    # === Core: pre_llm_call hook (the injection point) ===
    ctx.register_hook("pre_llm_call", on_pre_llm_call)

    # === Slash command: /search ===
    ctx.register_command(
        name="search",
        handler=handle_search_command,
        description="Trigger knowledge search: /search <query> [--source all|experience|database|knowledge] [--top 3]",
        args_hint="<query>",
    )

    # === AI-triggered tool: search_knowledge ===
    ctx.register_tool(
        name="search_knowledge",
        toolset="hermes_mcp",
        schema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question or search query"},
                "source": {
                    "type": "string",
                    "enum": ["all", "experience", "database", "knowledge"],
                    "description": "Which knowledge source to search",
                },
                "top_k": {"type": "integer", "description": "Number of results per source (1-10)", "default": 3},
                "session_id": {"type": "string", "description": "Session ID for context tracking"},
            },
            "required": ["question"],
        },
        handler=handle_search_knowledge,
        description="Search three-source knowledge base. Results are injected as context into the conversation.",
    )

    # === Utility tools ===
    ctx.register_tool(
        name="json_parse",
        toolset="hermes_mcp",
        schema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "JSON string to parse and format"}},
            "required": ["text"],
        },
        handler=handle_json_parse,
        description="Parse and pretty-print JSON content",
    )

    ctx.register_tool(
        name="base64",
        toolset="hermes_mcp",
        schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to encode or Base64 to decode"},
                "action": {"type": "string", "enum": ["encode", "decode"], "description": "Encode or decode"},
            },
            "required": ["text", "action"],
        },
        handler=handle_base64,
        description="Encode or decode Base64 text",
    )

    ctx.register_tool(
        name="now",
        toolset="hermes_mcp",
        schema={
            "type": "object",
            "properties": {"timezone": {"type": "string", "description": "Timezone (UTC, Asia/Shanghai, etc.)"}},
        },
        handler=handle_now,
        description="Get current date and time",
    )

    logger.info("hermes-mcp registered: 3 tools + 1 command + pre_llm_call hook")
