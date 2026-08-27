from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {"pdf", "docx", "xlsx", "pptx", "txt", "md", "html", "csv"}
)


class UnsupportedDocumentFormat(ValueError):
    pass


class DocumentParseFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceBlock:
    ordinal: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    source_blocks: list[SourceBlock]


@dataclass(frozen=True)
class DocumentChunk:
    ordinal: int
    text: str


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def chunk_text(
    text: str,
    *,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> list[DocumentChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between zero and max_chars")

    normalized = _normalize_text(text)
    if not normalized:
        return []

    chunks: list[DocumentChunk] = []
    start = 0
    while start < len(normalized):
        hard_end = min(start + max_chars, len(normalized))
        end = hard_end
        if hard_end < len(normalized):
            search_floor = start + max_chars // 2
            boundaries = [
                normalized.rfind(marker, search_floor, hard_end)
                for marker in ("\n\n", "\n", "。", "；", ";", ".")
            ]
            boundary = max(boundaries)
            if boundary >= search_floor:
                end = boundary + (2 if normalized.startswith("\n\n", boundary) else 1)

        piece = normalized[start:end].strip()
        if piece:
            chunks.append(DocumentChunk(ordinal=len(chunks), text=piece))
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap_chars)

    return chunks


class DoclingDocumentParser:
    def __init__(self, converter: Any | None = None) -> None:
        self._converter = converter

    def _converter_instance(self) -> Any:
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter
            except ImportError as exc:
                raise DocumentParseFailed("parse_failed") from exc
            self._converter = DocumentConverter()
        return self._converter

    def parse(self, path: Path) -> ParsedDocument:
        extension = path.suffix.lower().lstrip(".")
        if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
            raise UnsupportedDocumentFormat("unsupported_format")
        if not path.is_file():
            raise DocumentParseFailed("parse_failed")

        try:
            result = self._converter_instance().convert(path)
            markdown = _normalize_text(result.document.export_to_markdown())
        except DocumentParseFailed:
            raise
        except Exception as exc:
            raise DocumentParseFailed("parse_failed") from exc
        if not markdown:
            raise DocumentParseFailed("parse_failed")

        blocks = [
            SourceBlock(ordinal=index, text=block.strip())
            for index, block in enumerate(re.split(r"\n{2,}", markdown))
            if block.strip()
        ]
        return ParsedDocument(markdown=markdown, source_blocks=blocks)
