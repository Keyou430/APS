"""Read-only assertions for the isolated RAG migration jobs."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


REQUIRED_TABLES = {
    "knowledge_ingestion_jobs",
    "knowledge_chunks",
    "knowledge_retrieval_events",
}
REQUIRED_INDEXES = {
    "ix_knowledge_chunks_scope",
    "ix_knowledge_chunks_text_fts",
    "ix_knowledge_chunks_embedding_hnsw",
}


async def inspect_schema(dialect: str) -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            missing_tables = sorted(REQUIRED_TABLES - tables)
            if missing_tables:
                raise AssertionError(f"missing migration tables: {missing_tables}")

            chunk_columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("knowledge_chunks")}
            )
            if "embedding" not in chunk_columns:
                raise AssertionError("knowledge_chunks.embedding is missing")

            result: dict[str, Any] = {"tables": sorted(REQUIRED_TABLES)}
            if dialect == "sqlite":
                indexes = await connection.run_sync(
                    lambda sync: {index["name"] for index in inspect(sync).get_indexes("knowledge_chunks")}
                )
                result["indexes"] = sorted(indexes)
                return result

            extension = await connection.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            if extension != 1:
                raise AssertionError("PostgreSQL vector extension is missing")
            indexes = await connection.run_sync(
                lambda sync: {index["name"] for index in inspect(sync).get_indexes("knowledge_chunks")}
            )
            missing_indexes = sorted(REQUIRED_INDEXES - indexes)
            if missing_indexes:
                raise AssertionError(f"missing PostgreSQL RAG indexes: {missing_indexes}")
            result["indexes"] = sorted(indexes)
            return result
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialect", choices=("sqlite", "postgresql"), required=True)
    args = parser.parse_args()
    result = asyncio.run(inspect_schema(args.dialect))
    print(f"Migration schema assertions passed for {args.dialect}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
