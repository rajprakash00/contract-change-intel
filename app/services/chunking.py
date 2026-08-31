"""Chunker (ADR-005): clause-primary, paragraph fallback, fixed-size last resort.

Pure logic, unit-tested per PLAN's engineering policy. Chunks always satisfy
`text == parsed.text[char_start:char_end]` — citation offsets are the
contract downstream. The cap is a constant sized to the text-embedding-3-small
budget (8191 tokens), not a settings knob (one caller, per code taste).

Strategy: one chunk per clause (a heading plus its body). A clause beyond the
cap splits at paragraph seams with overlap so no context is lost; a single
paragraph beyond the cap falls back to whitespace cuts. Text with no headings
gets fixed windows with overlap.
"""

import re
from dataclasses import dataclass

from app.services.parsing import BlockKind, ParsedBlock, ParsedDocument

MAX_CHUNK_CHARS = 8000  # ~2k tokens, well inside the embedding model's budget
_OVERLAP_CHARS = 200


@dataclass(frozen=True)
class Chunk:
    text: str
    char_start: int
    char_end: int


def chunk_document(doc: ParsedDocument) -> list[Chunk]:
    if not doc.text or not doc.blocks:
        return []
    if any(block.kind is BlockKind.heading for block in doc.blocks):
        return _chunk_by_clause(doc)
    return _make_chunks(doc.text, _split_range(doc.text, 0, len(doc.text), bounds=[]))


def _chunk_by_clause(doc: ParsedDocument) -> list[Chunk]:
    chunks: list[Chunk] = []
    for clause_start, clause_end in _clause_spans(doc.blocks):
        bounds = [
            block.end
            for block in doc.blocks
            if clause_start <= block.start and block.end <= clause_end
        ]
        chunks.extend(
            _make_chunks(doc.text, _split_range(doc.text, clause_start, clause_end, bounds))
        )
    return chunks


def _clause_spans(blocks: list[ParsedBlock]) -> list[tuple[int, int]]:
    """Clause = one heading plus every paragraph up to the next heading.

    Paragraphs before the first heading form a preamble clause.
    """
    spans: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    for block in blocks:
        if block.kind is BlockKind.heading and start is not None:
            spans.append((start, end))
            start = None
        if start is None:
            start = block.start
        end = block.end
    if start is not None:
        spans.append((start, end))
    return spans


def _split_range(text: str, start: int, end: int, bounds: list[int]) -> list[tuple[int, int]]:
    """Split [start, end) into windows of at most MAX_CHUNK_CHARS.

    Windows prefer stopping at `bounds` (paragraph/block ends) — but only a
    stop at least half a window away, so a short block never strands a sliver
    window. With no qualifying boundary inside the budget, cut at the last
    whitespace (a single paragraph beyond the cap cannot be split at
    paragraphs; words are the floor). Each seam re-includes up to
    _OVERLAP_CHARS so no context is lost at the boundary.
    """
    windows: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        if end - pos <= MAX_CHUNK_CHARS:
            windows.append((pos, end))
            break
        budget = pos + MAX_CHUNK_CHARS
        stops = [
            bound
            for bound in bounds
            if pos < bound <= budget and bound - pos >= MAX_CHUNK_CHARS // 2
        ]
        stop = max(stops) if stops else _snap_backward(text, budget, pos)
        windows.append((pos, stop))
        nxt = _snap_forward(text, max(stop - _OVERLAP_CHARS, pos + 1))
        pos = max(min(nxt, stop), pos + 1)
    return windows


def _snap_backward(text: str, limit: int, floor: int) -> int:
    cut = max(text.rfind(" ", floor, limit), text.rfind("\n", floor, limit))
    return cut if cut > floor else limit


def _snap_forward(text: str, pos: int) -> int:
    match = re.search(r"\S", text[pos:])
    return pos + match.start() if match else len(text)


def _make_chunks(text: str, windows: list[tuple[int, int]]) -> list[Chunk]:
    return [Chunk(text=text[start:end], char_start=start, char_end=end) for start, end in windows]
