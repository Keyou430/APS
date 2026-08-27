from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import SessionLocal
from app.config import get_settings
from app.models import KnowledgeEntry, KnowledgeIngestionJob
from app.services.document_parser import (
    DoclingDocumentParser,
    UnsupportedDocumentFormat,
    chunk_text,
)
from app.services.object_storage import LocalPrivateObjectStorage, UnsafeObjectKey


def test_chunker_preserves_order_and_limits_without_empty_chunks() -> None:
    chunks = chunk_text("第一段。\n\n第二段。", max_chars=8, overlap_chars=2)

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert all(0 < len(chunk.text) <= 8 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks).replace("。第", "。第").startswith("第一段。")


@pytest.mark.asyncio
async def test_local_private_storage_round_trip_and_rejects_traversal(tmp_path: Path) -> None:
    storage = LocalPrivateObjectStorage(tmp_path)

    object_key = await storage.put_bytes("private/notes.txt", b"private text")

    assert object_key == "private/notes.txt"
    assert await storage.open_read(object_key) == b"private text"
    with pytest.raises(UnsafeObjectKey):
        await storage.put_bytes("../escape.txt", b"blocked")


def test_docling_parser_uses_whitelist_and_normalized_markdown(tmp_path: Path) -> None:
    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "# Title\r\n\r\nBody  "

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, _path: Path) -> FakeResult:
            return FakeResult()

    document = tmp_path / "policy.pdf"
    document.write_bytes(b"fixture")
    parser = DoclingDocumentParser(converter=FakeConverter())

    parsed = parser.parse(document)

    assert parsed.markdown == "# Title\n\nBody"
    with pytest.raises(UnsupportedDocumentFormat, match="unsupported_format"):
        parser.parse(tmp_path / "archive.exe")


@pytest.mark.asyncio
async def test_upload_keeps_compatibility_field_without_exposing_object_key(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    collection = await client.post(
        "/api/knowledge/collections", headers=admin_headers, json={"name": "解析测试"}
    )
    assert collection.status_code == 201, collection.text
    response = await client.post(
        "/api/knowledge/upload",
        headers=admin_headers,
        data={"title": "Private notes", "collection_id": str(collection.json()["id"])},
        files={"file": ("notes.txt", b"private text", "text/plain")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert "file_path" in body
    assert body["file_path"] is None
    assert "object_key" not in body
    assert body["ingestion_status"] == "queued"
    async with SessionLocal() as db:
        entry = await db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.id == body["id"]))
        assert entry is not None
        assert entry.file_path is not None
        assert not Path(entry.file_path).is_absolute()
        assert ".." not in Path(entry.file_path).parts
        job = await db.scalar(
            select(KnowledgeIngestionJob).where(
                KnowledgeIngestionJob.knowledge_entry_id == entry.id
            )
        )
        assert job is not None
        assert job.status == "queued"

    deleted = await client.delete(f"/api/knowledge/{body['id']}", headers=admin_headers)
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_delete_accepts_legacy_file_path_only_inside_upload_root(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = settings.upload_dir / "legacy-delete.txt"
    legacy_path.write_bytes(b"legacy")
    async with SessionLocal() as db:
        entry = KnowledgeEntry(
            organization_id=1,
            user_id=1,
            type="file",
            title="Legacy file",
            file_path=str(legacy_path),
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        entry_id = entry.id

    response = await client.delete(f"/api/knowledge/{entry_id}", headers=admin_headers)

    assert response.status_code == 204
    assert legacy_path.exists()
    purged = await client.delete(
        f"/api/knowledge/{entry_id}/purge", headers=admin_headers
    )
    assert purged.status_code == 204
    assert not legacy_path.exists()
