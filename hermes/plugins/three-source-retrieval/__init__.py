"""Hermes plugin: three-source serial retrieval middleware.
Auto-injects E->D->K retrieval results into every LLM call's system prompt.

IMPORTANT: Must use synchronous httpx. Hermes middleware callbacks are
called synchronously (no await).
"""
from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

RETRIEVAL_SERVICE_URL = "http://localhost:8001"

_INTERNAL_CALL_PATTERNS = [
    "summarize the conversation",
    "compression summary",
    "kanban task",
    "iteration limit reached",
]


def _is_internal_call(messages: List[Dict]) -> bool:
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            for pattern in _INTERNAL_CALL_PATTERNS:
                if pattern in content.lower():
                    return True
    return False


def _get_last_user_message(messages: List[Dict]) -> Optional[str]:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                texts = [p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text"]
                return " ".join(texts) if texts else None
    return None


def _build_context_block(result: Dict) -> str:
    """Build markdown context block from retrieval results."""
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

    return "".join(parts)


def _call_retrieval_service(question: str, session_id: str) -> Dict:
    """Synchronous call to three-source retrieval service."""
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
            resp = client.post(
                f"{RETRIEVAL_SERVICE_URL}/serial-retrieve",
                json={
                    "question": question,
                    "session_id": session_id,
                    "mode": "serial",
                    "options": {
                        "experience": {"enabled": True, "top_k": 3, "similarity_threshold": 0.3},
                        "database": {"enabled": True, "top_k": 3, "similarity_threshold": 0.3},
                        "knowledge": {"enabled": True, "top_k": 3, "similarity_threshold": 0.3},
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("Three-source retrieval failed: %s", e)
        return {
            "experience": {"is_empty": True}, "database": {"is_empty": True},
            "knowledge": {"is_empty": True}, "meta": {"error": str(e)},
        }


# ====== LLM Request Middleware (SYNCHRONOUS) ======

def on_llm_request(**kwargs: Any) -> Dict[str, Any]:
    """Middleware: intercept LLM request, inject three-source retrieval results."""
    logger.info("MIDDLEWARE FIRED! kwargs keys: %s", list(kwargs.keys()))
    request = kwargs.get("request", {})
    messages = request.get("messages", [])

    if _is_internal_call(messages):
        return {"request": request}

    question = _get_last_user_message(messages)
    if not question:
        return {"request": request}

    platform = kwargs.get("platform", "")
    if platform in ("kanban_worker",):
        return {"request": request}

    session_id = kwargs.get("session_id", "")
    logger.info("Three-source retrieval for: %.80s...", question)
    start = time.monotonic()
    result = _call_retrieval_service(question, session_id)
    elapsed = time.monotonic() - start
    logger.info("Retrieval done in %.1fs", elapsed)

    context_block = _build_context_block(result)

    new_messages = list(messages)
    for i, msg in enumerate(new_messages):
        if msg.get("role") == "system":
            orig = msg.get("content", "")
            if isinstance(orig, str):
                new_messages[i] = {**msg, "content": orig + context_block}
            break
    else:
        new_messages.insert(0, {
            "role": "system",
            "content": f"You have access to retrieval results:{context_block}\n\n## CRITICAL RULES (MUST FOLLOW)\n\n1. ONLY use the retrieval results above to answer. They are your sole reference.\n2. In your answer, cite the source label (e.g. [Source K-1]) for each point. Do NOT repeat the full source text.\n3. DO NOT use read_file, search_files, or any file tool — the documents are NOT on local disk.\n4. DO NOT use web_search or any web tool — do NOT search the internet.\n5. If retrieval results are empty or irrelevant, say \"知识库中未找到相关信息\" and STOP. Do NOT fabricate, guess, or use your own knowledge.",
        })

    return {"request": {**request, "messages": new_messages}}


# ====== Plugin Registration ======

def register(ctx) -> None:
    from hermes_cli.middleware import LLM_REQUEST_MIDDLEWARE
    ctx.register_middleware(LLM_REQUEST_MIDDLEWARE, on_llm_request)
    logger.info("Three-source retrieval middleware registered")
