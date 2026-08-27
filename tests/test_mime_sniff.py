"""Unit tests for pure magic-byte sniffing logic (no DB, no HTTP)."""

import io
import zipfile

from app.services.documents import sniff_mime

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _zip_bytes(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name in names:
            bundle.writestr(name, "x")
    return buffer.getvalue()


def test_pdf_prefix_detected() -> None:
    assert sniff_mime(b"%PDF-1.7 trailing bytes") == "application/pdf"


def test_docx_package_detected() -> None:
    content = _zip_bytes("[Content_Types].xml", "word/document.xml")
    assert sniff_mime(content) == DOCX_MIME


def test_generic_zip_is_unknown() -> None:
    content = _zip_bytes("[Content_Types].xml", "readme.txt")
    assert sniff_mime(content) is None


def test_word_parts_without_content_types_is_unknown() -> None:
    content = _zip_bytes("word/document.xml")
    assert sniff_mime(content) is None


def test_truncated_zip_is_unknown() -> None:
    assert sniff_mime(b"PK\x03\x04broken") is None


def test_utf8_text_detected() -> None:
    assert sniff_mime("café agreement".encode()) == "text/plain"


def test_nul_byte_is_not_text() -> None:
    assert sniff_mime(b"binary\x00junk") is None


def test_invalid_utf8_is_unknown() -> None:
    assert sniff_mime(b"\xff\xfe\xff") is None


def test_empty_content_is_unknown() -> None:
    assert sniff_mime(b"") is None
