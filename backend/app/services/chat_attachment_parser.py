from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.services.document_parser import (
    DoclingDocumentParser,
    DocumentParseFailed,
    ParsedDocument,
    UnsupportedDocumentFormat,
)


class DocumentParser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...


_DIRECT_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".html"}


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def _xml_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    parts: list[str] = []
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        if name in {"t", "v"} and element.text:
            parts.append(element.text)
        elif name in {"p", "row", "tr"} and parts and parts[-1] != "\n":
            parts.append("\n")
    return "\n".join(
        line.strip() for line in "".join(parts).splitlines() if line.strip()
    )


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        return "\n\n".join(
            (page.extract_text() or "").strip() for page in reader.pages
        ).strip()
    except Exception as exc:
        raise DocumentParseFailed("parse_failed") from exc


def _parse_office_archive(data: bytes, suffix: str) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            if suffix == ".docx":
                targets = ["word/document.xml"]
            elif suffix == ".pptx":
                targets = sorted(
                    name
                    for name in names
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                )
            else:
                targets = sorted(
                    name
                    for name in names
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                )
                if "xl/sharedStrings.xml" in names:
                    targets.insert(0, "xl/sharedStrings.xml")
            return "\n\n".join(
                _xml_text(archive.read(name)) for name in targets if name in names
            ).strip()
    except (BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise DocumentParseFailed("parse_failed") from exc


def _parse_supported_document(data: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        return _parse_pdf(data)
    if suffix in {".docx", ".xlsx", ".pptx"}:
        return _parse_office_archive(data, suffix)
    raise UnsupportedDocumentFormat("unsupported_format")


def parse_chat_attachment(
    data: bytes,
    filename: str,
    *,
    parser: DocumentParser | None = None,
    max_characters: int = 12_000,
) -> str:
    safe_name = Path(filename.replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    if suffix in _DIRECT_TEXT_SUFFIXES:
        return _decode_text(data)[:max_characters]
    if parser is None and suffix in {".pdf", ".docx", ".xlsx", ".pptx"}:
        content = _parse_supported_document(data, suffix)
        if not content:
            raise DocumentParseFailed("parse_failed")
        return content[:max_characters]
    with TemporaryDirectory(prefix="chat-attachment-") as temporary_directory:
        source_path = Path(temporary_directory) / f"source{suffix}"
        source_path.write_bytes(data)
        parsed = (parser or DoclingDocumentParser()).parse(source_path)
        return parsed.markdown.strip()[:max_characters]
