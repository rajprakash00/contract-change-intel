"""Unit tests for parsers: stored bytes -> canonical text + structure + page map.

Parsers are pure functions on bytes (no DB, no IO beyond in-memory buffers),
so they are unit-tested per PLAN's engineering policy. Synthetic PDF/DOCX
fixtures are built in-memory; no binary fixtures on disk.
"""

import io

import pytest
from docx import Document

from app.services.parsing import (
    BlockKind,
    ParsedDocument,
    UnsupportedParseError,
    parse,
    parse_pdf,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def build_docx(blocks: list[tuple[str, str]]) -> bytes:
    document = Document()
    for style, text in blocks:
        document.add_paragraph(text, style=style)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def minimal_pdf(*pages: list[str]) -> bytes:
    """Assemble a tiny valid PDF (one text column, Helvetica) for pdfplumber."""
    font_obj = 3
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objs: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, lines in enumerate(pages):
        stream = "BT /F1 12 Tf 14 TL 72 720 Td\n"
        for line in lines:
            escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            stream += f"({escaped}) Tj T*\n"
        stream += "ET"
        encoded = stream.encode()
        objs[4 + 2 * i] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {5 + 2 * i} 0 R /Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
        ).encode()
        objs[5 + 2 * i] = f"<< /Length {len(encoded)} >>\nstream\n{stream}\nendstream".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    size = max(objs) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for num in sorted(objs):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


def assert_slice_fidelity(doc: ParsedDocument) -> None:
    for block in doc.blocks:
        assert doc.text[block.start : block.end] == block.text, (
            "block offsets must index into the canonical text"
        )


class TestDocxParsing:
    async def test_heading_styles_mark_clause_structure(self) -> None:
        content = build_docx(
            [
                ("Heading 1", "1. Scope"),
                ("Normal", "The supplier shall deliver goods."),
                ("Heading 2", "1.1 Delivery"),
                ("Normal", "Within thirty days."),
            ]
        )

        doc = parse(DOCX_MIME, content)

        assert [(b.kind, b.text) for b in doc.blocks] == [
            (BlockKind.heading, "1. Scope"),
            (BlockKind.paragraph, "The supplier shall deliver goods."),
            (BlockKind.heading, "1.1 Delivery"),
            (BlockKind.paragraph, "Within thirty days."),
        ]
        assert doc.page_map == [], "DOCX has no page concept"
        assert_slice_fidelity(doc)

    async def test_empty_paragraphs_are_dropped(self) -> None:
        content = build_docx([("Heading 1", "1. Scope"), ("Normal", ""), ("Normal", "Body.")])

        doc = parse(DOCX_MIME, content)

        assert [b.text for b in doc.blocks] == ["1. Scope", "Body."]


class TestPdfParsing:
    async def test_lines_become_blocks_and_pages_map_to_char_spans(self) -> None:
        content = minimal_pdf(["1. Scope", "The supplier shall deliver goods."])

        doc = parse("application/pdf", content)

        assert "1. Scope" in doc.text
        assert "The supplier shall deliver goods." in doc.text
        assert_slice_fidelity(doc)
        assert doc.page_map == [{"page": 1, "start": 0, "end": len(doc.text)}]

    async def test_clause_number_lines_are_detected_as_headings(self) -> None:
        content = minimal_pdf(["1. Scope", "Body text.", "Article 4 - Term", "Twelve months."])

        doc = parse_pdf(content)

        kinds = [b.kind for b in doc.blocks]
        assert BlockKind.heading in kinds
        headings = [b.text for b in doc.blocks if b.kind is BlockKind.heading]
        assert any("Scope" in h for h in headings)
        assert any("Term" in h for h in headings)

    async def test_each_page_gets_a_contiguous_char_span(self) -> None:
        content = minimal_pdf(["1. Scope", "Body."], ["2. Term", "Twelve months."])

        doc = parse("application/pdf", content)

        assert [entry["page"] for entry in doc.page_map] == [1, 2]
        assert doc.page_map[0]["start"] == 0
        assert doc.page_map[1]["start"] > doc.page_map[0]["start"]
        assert doc.page_map[-1]["end"] == len(doc.text)

    async def test_body_prose_starting_with_a_bare_number_is_not_a_heading(self) -> None:
        content = minimal_pdf(["1. Scope", "30 days after delivery the warranty period begins."])

        doc = parse("application/pdf", content)

        body = next(b for b in doc.blocks if b.text.startswith("30 days"))
        assert body.kind is BlockKind.paragraph, (
            "a bare integer followed by prose is body text, not a clause boundary"
        )

    async def test_textless_pdf_parses_to_an_empty_document(self) -> None:
        content = minimal_pdf(["   "])

        doc = parse("application/pdf", content)

        assert doc.text == ""
        assert doc.blocks == []
        assert doc.page_map == []


class TestPlainTextParsing:
    async def test_blank_lines_split_paragraphs_with_no_headings(self) -> None:
        doc = parse("text/plain", b"First paragraph.\n\nSecond paragraph.")

        assert [(b.kind, b.text) for b in doc.blocks] == [
            (BlockKind.paragraph, "First paragraph."),
            (BlockKind.paragraph, "Second paragraph."),
        ]
        assert doc.page_map == []
        assert_slice_fidelity(doc)


class TestParseDispatch:
    async def test_unsupported_mime_type_raises(self) -> None:
        with pytest.raises(UnsupportedParseError):
            parse("application/json", b"{}")
