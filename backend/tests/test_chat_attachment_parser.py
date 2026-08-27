from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from httpx import AsyncClient

from app.services.chat_attachment_parser import parse_chat_attachment
from app.services.document_parser import ParsedDocument


class RecordingParser:
    def __init__(self) -> None:
        self.seen_path: Path | None = None

    def parse(self, path: Path) -> ParsedDocument:
        self.seen_path = path
        assert path.read_bytes() == b"transient attachment"
        return ParsedDocument(markdown="attachment content", source_blocks=[])


def test_chat_attachment_is_parsed_without_persisting_the_temporary_file() -> None:
    parser = RecordingParser()

    content = parse_chat_attachment(
        b"transient attachment",
        "../brief.pdf",
        parser=parser,
    )

    assert content == "attachment content"
    assert parser.seen_path is not None
    assert parser.seen_path.name == "source.pdf"
    assert not parser.seen_path.exists()


def test_plain_text_attachment_bypasses_the_document_converter() -> None:
    content = parse_chat_attachment(
        "临时附件内容".encode(),
        "..\\brief.txt",
        parser=RecordingParser(),
    )

    assert content == "临时附件内容"


def _text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(output)


def test_pdf_attachment_extracts_text_without_docling() -> None:
    content = parse_chat_attachment(
        _text_pdf("Production manager experience"),
        "resume.pdf",
    )

    assert "Production manager experience" in content


@pytest.mark.asyncio
async def test_chat_attachment_endpoint_returns_extracted_pdf_text(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/chat/attachments",
        headers=admin_headers,
        files={
            "file": (
                "resume.pdf",
                _text_pdf("Candidate Zhou Min has five years HR experience"),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "resume.pdf"
    assert "five years HR experience" in response.json()["content"]


def test_docx_attachment_extracts_document_text_without_docling() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>生产主管简历</w:t></w:r></w:p><w:p><w:r><w:t>五年现场管理经验</w:t></w:r></w:p></w:body>
            </w:document>""",
        )

    content = parse_chat_attachment(output.getvalue(), "resume.docx")

    assert "生产主管简历" in content
    assert "五年现场管理经验" in content
