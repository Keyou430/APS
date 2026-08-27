from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import Protocol


class UnsafeObjectKey(ValueError):
    pass


class ObjectStorage(Protocol):
    async def put_bytes(self, object_key: str, content: bytes) -> str: ...

    async def open_read(self, object_key: str) -> bytes: ...

    async def delete(self, object_key: str) -> None: ...


class LocalPrivateObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path_for(self, object_key: str) -> Path:
        normalized = object_key.replace("\\", "/")
        key = PurePosixPath(normalized)
        if (
            not normalized
            or key.is_absolute()
            or any(part in {"", ".", ".."} for part in key.parts)
            or ":" in key.parts[0]
        ):
            raise UnsafeObjectKey("unsafe object key")
        candidate = self.root.joinpath(*key.parts).resolve()
        if not candidate.is_relative_to(self.root):
            raise UnsafeObjectKey("unsafe object key")
        return candidate

    async def put_bytes(self, object_key: str, content: bytes) -> str:
        destination = self._path_for(object_key)
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, content)
        return object_key.replace("\\", "/")

    async def open_read(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path_for(object_key).read_bytes)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._path_for(object_key).unlink, missing_ok=True)
