from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers import knowledge as knowledge_router


class ChunkedUpload:
    def __init__(self, *, filename: str, content_type: str, chunks: list[bytes]) -> None:
        self.filename = filename
        self.content_type = content_type
        self._chunks = iter(chunks)

    async def read(self, _size: int) -> bytes:
        return next(self._chunks, b"")


@pytest.mark.asyncio
async def test_knowledge_upload_reads_text_in_bounded_chunks() -> None:
    file = ChunkedUpload(
        filename="notes.txt",
        content_type="text/plain",
        chunks=["第一行".encode(), "第二行".encode()],
    )

    assert await knowledge_router._read_knowledge_upload(file) == "第一行第二行".encode()


@pytest.mark.asyncio
async def test_knowledge_upload_rejects_multibyte_payload_over_50_mib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge_router, "_MAX_KNOWLEDGE_UPLOAD_BYTES", 10)
    file = ChunkedUpload(
        filename="notes.txt",
        content_type="text/plain",
        chunks=["中文内容".encode()],
    )

    with pytest.raises(HTTPException) as error:
        await knowledge_router._read_knowledge_upload(file)

    assert error.value.status_code == 413
    assert error.value.detail == "payload_too_large"


@pytest.mark.asyncio
async def test_knowledge_upload_rejects_extension_and_magic_mismatch() -> None:
    file = ChunkedUpload(
        filename="../secret.exe",
        content_type="application/octet-stream",
        chunks=[b"not a document"],
    )

    with pytest.raises(HTTPException) as error:
        await knowledge_router._read_knowledge_upload(file)

    assert error.value.status_code == 422
    assert error.value.detail == "content_type_not_allowed"
