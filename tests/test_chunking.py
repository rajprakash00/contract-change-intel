"""Unit tests for the ADR-005 chunker: pure logic, no database.

The invariants that matter downstream (embedding + citation offsets):
every chunk's text is exactly ParsedDocument.text[char_start:char_end],
chunks are ordered, and no chunk exceeds the size cap.
"""

import itertools

from app.services.chunking import MAX_CHUNK_CHARS, chunk_document
from app.services.parsing import BlockKind, ParsedBlock, ParsedDocument


def make_doc(*blocks: tuple[BlockKind, str]) -> ParsedDocument:
    """Assemble blocks into a ParsedDocument the same way the parsers do."""
    parts: list[str] = []
    parsed: list[ParsedBlock] = []
    pos = 0
    for kind, text in blocks:
        if parts:
            parts.append("\n\n")
            pos += 2
        parsed.append(ParsedBlock(kind=kind, text=text, start=pos, end=pos + len(text), page=None))
        parts.append(text)
        pos += len(text)
    return ParsedDocument(text="".join(parts), blocks=parsed, page_map=[])


def paragraph(text: str) -> tuple[BlockKind, str]:
    return (BlockKind.paragraph, text)


def heading(text: str) -> tuple[BlockKind, str]:
    return (BlockKind.heading, text)


def assert_slice_fidelity(doc: ParsedDocument, chunks) -> None:
    for chunk in chunks:
        assert chunk.text == doc.text[chunk.char_start : chunk.char_end], (
            "chunk text must equal the parsed-text slice: citation offsets are "
            "meaningless otherwise"
        )


class TestClausePrimaryChunking:
    async def test_each_clause_becomes_exactly_one_chunk(self) -> None:
        doc = make_doc(
            heading("1. Definitions"),
            paragraph('"Agreement" means the contract attached hereto.'),
            heading("2. Term"),
            paragraph("This Agreement runs for twelve months."),
        )

        chunks = chunk_document(doc)

        assert [c.text for c in chunks] == [
            '1. Definitions\n\n"Agreement" means the contract attached hereto.',
            "2. Term\n\nThis Agreement runs for twelve months.",
        ]
        assert all(c.char_end - c.char_start <= MAX_CHUNK_CHARS for c in chunks)
        assert_slice_fidelity(doc, chunks)

    async def test_short_document_yields_a_single_chunk(self) -> None:
        doc = make_doc(paragraph("Short agreement."))

        chunks = chunk_document(doc)

        assert len(chunks) == 1
        assert chunks[0].text == "Short agreement."
        assert chunks[0].char_start == 0
        assert chunks[0].char_end == len(doc.text)

    async def test_paragraphs_before_the_first_heading_form_a_preamble_chunk(self) -> None:
        doc = make_doc(
            paragraph("Preamble text."),
            heading("1. Scope"),
            paragraph("Scope body."),
        )

        chunks = chunk_document(doc)

        assert [c.text for c in chunks] == ["Preamble text.", "1. Scope\n\nScope body."]
        assert_slice_fidelity(doc, chunks)


class TestOversizedClauseFallback:
    async def test_oversized_clause_splits_at_paragraph_seams_with_overlap(self) -> None:
        para = "The supplier shall deliver goods. " * 80  # ~2.7k chars, under the cap alone
        doc = make_doc(
            heading("7. Delivery"),
            paragraph(para),
            paragraph(para),
            paragraph(para),
        )
        clause_len = 3 * len(para) + len("7. Delivery") + 4
        assert clause_len > MAX_CHUNK_CHARS

        chunks = chunk_document(doc)

        assert len(chunks) > 1
        assert all(c.char_end - c.char_start <= MAX_CHUNK_CHARS for c in chunks), (
            "no chunk may exceed the embedding budget"
        )
        assert_slice_fidelity(doc, chunks)
        # Consecutive chunks share the seam: overlap means no context is lost
        # at the boundary.
        for prev, nxt in itertools.pairwise(chunks):
            assert prev.char_end > nxt.char_start, "seams must overlap"
            assert nxt.char_start > prev.char_start, "windows must make progress"
        # Together the chunks cover the whole clause.
        assert chunks[0].char_start == doc.blocks[0].start
        assert chunks[-1].char_end == doc.blocks[-1].end

    async def test_single_paragraph_beyond_the_cap_is_whitespace_split(self) -> None:
        para = "word " * (MAX_CHUNK_CHARS // 2)  # one paragraph, twice the cap
        doc = make_doc(heading("1. Boilerplate"), paragraph(para.rstrip()))

        chunks = chunk_document(doc)

        assert len(chunks) > 1
        assert all(c.char_end - c.char_start <= MAX_CHUNK_CHARS for c in chunks)
        assert_slice_fidelity(doc, chunks)
        for prev, nxt in itertools.pairwise(chunks):
            assert prev.char_end > nxt.char_start


class TestUnstructuredFallback:
    async def test_text_without_headings_falls_back_to_fixed_windows(self) -> None:
        body = "No clause structure here. " * (MAX_CHUNK_CHARS // 10)
        doc = make_doc(paragraph(body.rstrip()))

        chunks = chunk_document(doc)

        assert len(chunks) > 1
        assert all(c.char_end - c.char_start <= MAX_CHUNK_CHARS for c in chunks)
        assert_slice_fidelity(doc, chunks)
        for prev, nxt in itertools.pairwise(chunks):
            assert prev.char_end > nxt.char_start
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(doc.text)

    async def test_empty_document_yields_no_chunks(self) -> None:
        doc = make_doc()

        assert chunk_document(doc) == []
