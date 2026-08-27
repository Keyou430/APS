"""Knowledge retrieval tools — three-source (Experience/Database/Knowledge) search."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from hermes_mcp.backends.retrieval import RetrievalBackend
from hermes_mcp.config.schema import HermesMCPConfig

logger = logging.getLogger(__name__)


def register_retrieval_tools(
    mcp: FastMCP,
    backend: RetrievalBackend,
    config: HermesMCPConfig,
) -> None:
    """Register knowledge retrieval tools on the MCP server."""

    @mcp.tool(
        name="search_knowledge",
        description="""Search across three knowledge sources (Experience Library, Business Database, Knowledge Base).

This tool queries all three sources in serial and returns the most relevant results.
Use it when you need domain-specific knowledge that may not be in your training data.

Each source returns up to top_k results with similarity scores. Empty sources are
explicitly marked so you know what wasn't found.""",
    )
    async def search_knowledge(
        question: str,
        source: str = "all",
        top_k: int = 3,
        session_id: str = "",
    ) -> str:
        """Search knowledge bases for relevant information.

        Args:
            question: The search query/question
            source: Which source(s) to search: 'all', 'experience', 'database', or 'knowledge'
            top_k: Number of results per source (1-10)
            session_id: Optional session identifier for context tracking
        """
        exp_enabled = config.retrieval.experience_enabled and source in ("all", "experience")
        db_enabled = config.retrieval.database_enabled and source in ("all", "database")
        kw_enabled = config.retrieval.knowledge_enabled and source in ("all", "knowledge")

        top_k = max(1, min(top_k, 10))

        result = await backend.search(
            question=question,
            session_id=session_id,
            experience_enabled=exp_enabled,
            database_enabled=db_enabled,
            knowledge_enabled=kw_enabled,
            top_k=top_k,
        )

        if not result.get("success"):
            error_msg = result.get("meta", {}).get("error", "Unknown error")
            return f"❌ Retrieval failed: {error_msg}\n\nMake sure the retrieval service is running on {config.retrieval.base_url}"

        return _format_results(result, source)

    @mcp.tool(
        name="get_retrieval_status",
        description="Check the health and availability of the three-source retrieval service.",
    )
    async def get_retrieval_status() -> str:
        """Check if the retrieval service is online and reachable."""
        status = await backend.health_check()

        if status.get("available"):
            return (
                f"✅ Retrieval service is online\n"
                f"   URL: {status.get('base_url')}\n"
                f"   Status: HTTP {status.get('status_code')}"
            )
        else:
            return (
                f"❌ Retrieval service is offline\n"
                f"   URL: {status.get('base_url')}\n"
                f"   Error: {status.get('error', 'Unknown')}"
            )


def _format_results(result: dict, source_filter: str) -> str:
    """Format retrieval results as markdown for MCP response."""
    parts = ["## Knowledge Retrieval Results\n"]

    # Experience Library
    if source_filter in ("all", "experience"):
        e = result.get("experience", {})
        parts.append("### 📚 Experience Library")
        if e.get("is_empty", True) or not e.get("results"):
            parts.append("_No relevant experience records found._\n")
        else:
            for i, r in enumerate(e["results"][:10], 1):
                score = r.get("score", 0)
                source_name = r.get("source_name", "Unknown")
                solution = r.get("solution", "")
                parts.append(f"**E-{i}** | score={score:.3f} | {source_name}")
                parts.append(f"```\n{solution[:2000]}\n```\n")

    # Business Database
    if source_filter in ("all", "database"):
        d = result.get("database", {})
        parts.append("### 🗄️ Business Database")
        if d.get("is_empty", True) or not d.get("results"):
            parts.append("_No relevant business records found._\n")
        else:
            for i, r in enumerate(d["results"][:10], 1):
                score = r.get("score", 0)
                source_name = r.get("source_name", "Unknown")
                solution = r.get("solution", "")
                parts.append(f"**D-{i}** | score={score:.3f} | {source_name}")
                parts.append(f"```\n{solution[:2000]}\n```\n")

    # Knowledge Base
    if source_filter in ("all", "knowledge"):
        k = result.get("knowledge", {})
        parts.append("### 📖 Knowledge Base")
        if k.get("is_empty", True) or not k.get("results"):
            parts.append("_No relevant documents found._\n")
        else:
            for i, r in enumerate(k["results"][:10], 1):
                score = r.get("score", 0)
                source_name = r.get("source_name", "Unknown")
                chunk = r.get("chunk", "")
                parts.append(f"**K-{i}** | score={score:.3f} | {source_name}")
                parts.append(f"```\n{chunk[:2000]}\n```\n")

    # Summary
    name_map = {
        "Experience Library": "experience",
        "Business Database": "database",
        "Knowledge Base": "knowledge",
    }
    empties = [
        name for name, key in name_map.items()
        if result.get(key, {}).get("is_empty", True)
    ]
    if empties:
        parts.append(f"⚠️ Sources with no results: {', '.join(empties)}")
        parts.append("Do not fabricate information from these sources.\n")

    parts.append("\n---")
    parts.append("**Instructions:** For every point in your answer, cite the source label (e.g. [Source K-1]) and include the relevant original text as a quote. Structure: brief summary → each finding with source citation + quoted original text.")

    return "\n".join(parts)
