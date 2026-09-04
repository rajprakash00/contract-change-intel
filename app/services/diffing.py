"""Clause-level alignment + pure diff for Change Reports (W4·C).

Sections are derived from each version's parsed text rather than from its
chunks: the chunker falls back to fixed-size windows for heading-less
documents (ADR-005), which would collapse plain-text agreements into one
whole-document chunk and degenerate alignment. Paragraph structure is the
common denominator of every parser, and chunk spans are offsets into the
same parsed text — the paragraph route loses nothing.

Alignment matches sections across versions by clause key with number
normalization: "8.02" and "8.2" are the same clause (leading zeros strip),
while tuple keys keep "8.2" and "8.2.1" distinct (child-clause guard).
Within a matched pair the texts are compared as-is; a difference is one
`modified` Change. Sections without a counterpart are `removed` / `added`.
Every Change carries char spans into both versions' parsed text.

Pure logic, unit-tested per PLAN's engineering policy; graded mechanically
by the `diff` golden task in the eval harness.
"""

import enum
import re
from collections import defaultdict
from dataclasses import dataclass

_MAX_HEADING_CHARS = 60

# Clause-number detection on a paragraph's first line. Alternatives: an
# Article/Section/Clause prefix ("Section 8.02"), a dotted number ("2.1",
# "8.2.1"), a bare number with dot/paren ("1.", "1)"), and a bare number
# followed by an uppercase word ("3 OBLIGATIONS OF PLAN_B" — CUAD style).
# The case-insensitive flag is scoped off for the uppercase lookahead so
# body prose ("30 days after delivery …") never reads as a boundary.
_CLAUSE_NUMBER_PATTERN = re.compile(
    r"^(?:"
    r"(?:(?:article|section|clause)\s+(?P<prefixed>\d+(?:\.\d+)*)[.)]?"
    r"|(?P<dotted>\d+(?:\.\d+)+)[.)]?"
    r"|(?P<numbered>\d+)[.)]"
    r")\s+\S"
    r"|(?P<heading>\d+)\s+(?-i:[A-Z])"
    r")",
    re.IGNORECASE,
)


class ChangeKind(enum.Enum):
    added = "added"
    removed = "removed"
    modified = "modified"


@dataclass(frozen=True)
class Span:
    """Char offsets into one version's parsed text (end exclusive)."""

    char_start: int
    char_end: int


@dataclass(frozen=True)
class Change:
    """One detected difference between two document versions.

    Exactly one span is None: `base_span` for an added clause,
    `amended_span` for a removed one. `clause_ref` is None only for the
    unnumbered preamble.
    """

    kind: ChangeKind
    clause_ref: str | None
    base_span: Span | None
    amended_span: Span | None


SectionKey = tuple[int, ...] | str


@dataclass(frozen=True)
class _Section:
    key: SectionKey | None
    clause_ref: str | None
    char_start: int
    char_end: int


def detect_changes(base_text: str, amended_text: str) -> list[Change]:
    """Align the two versions' clauses and diff each matched pair.

    Changes come out deterministic: modified/removed in base order, then
    added in amendment order.
    """
    base_sections = _sections(base_text)
    amended_sections = _sections(amended_text)
    amended_by_key: dict[SectionKey | None, list[int]] = defaultdict(list)
    for index, section in enumerate(amended_sections):
        amended_by_key[section.key].append(index)

    changes: list[Change] = []
    consumed: set[int] = set()
    for base_section in base_sections:
        match = next(
            (i for i in amended_by_key.get(base_section.key, []) if i not in consumed), None
        )
        if match is None:
            changes.append(
                Change(
                    ChangeKind.removed,
                    base_section.clause_ref,
                    Span(base_section.char_start, base_section.char_end),
                    None,
                )
            )
            continue
        consumed.add(match)
        amended_section = amended_sections[match]
        if _slice(base_text, base_section) != _slice(amended_text, amended_section):
            changes.append(
                Change(
                    ChangeKind.modified,
                    base_section.clause_ref,
                    Span(base_section.char_start, base_section.char_end),
                    Span(amended_section.char_start, amended_section.char_end),
                )
            )
    for index, amended_section in enumerate(amended_sections):
        if index in consumed:
            continue
        changes.append(
            Change(
                ChangeKind.added,
                amended_section.clause_ref,
                None,
                Span(amended_section.char_start, amended_section.char_end),
            )
        )
    return changes


def _sections(text: str) -> list[_Section]:
    """Group paragraphs into clause sections: a paragraph whose first line
    carries a clause number starts a section; everything else extends the
    section before it (clause bodies flow over paragraphs). Paragraphs ahead
    of the first numbered clause form the unnumbered preamble."""
    sections: list[_Section] = []
    for start, end, paragraph in _paragraphs(text):
        key = _clause_key(paragraph.split("\n", 1)[0])
        if key is None and sections:
            previous = sections[-1]
            sections[-1] = _Section(previous.key, previous.clause_ref, previous.char_start, end)
            continue
        sections.append(_Section(key, _clause_ref(key), start, end))
    return sections


def _paragraphs(text: str) -> list[tuple[int, int, str]]:
    """Split canonical parsed text ("\n\n" between blocks, per parsing.py)
    into (start, end, paragraph) spans into the original string."""
    paragraphs: list[tuple[int, int, str]] = []
    pos = 0
    while pos < len(text):
        separator = text.find("\n\n", pos)
        end = len(text) if separator == -1 else separator
        if text[pos:end].strip():
            paragraphs.append((pos, end, text[pos:end]))
        pos = end + 2
    return paragraphs


def _clause_key(line: str) -> SectionKey | None:
    """Normalized alignment key for a paragraph's first line.

    Numbered clauses key on their number as a tuple of ints ("8.02" and
    "8.2" both (8, 2); "8.2.1" stays (8, 2, 1)). A short ALL-CAPS line is an
    unnumbered heading, keyed by its casefolded text. Everything else is
    body prose and belongs to the section before it.
    """
    match = _CLAUSE_NUMBER_PATTERN.match(line)
    if match is not None:
        raw = match.group("prefixed") or match.group("dotted") or match.group("numbered")
        if raw is None:
            raw = match.group("heading")
        return tuple(int(part) for part in raw.split("."))
    stripped = line.strip()
    if (
        0 < len(stripped) <= _MAX_HEADING_CHARS
        and stripped.isupper()
        and any(char.isalpha() for char in stripped)
    ):
        return " ".join(stripped.casefold().split())
    return None


def _clause_ref(key: SectionKey | None) -> str | None:
    """Human-facing clause reference: dotted numbers for clauses, the
    normalized heading text for unnumbered headings, None for the preamble."""
    if key is None:
        return None
    if isinstance(key, tuple):
        return ".".join(str(part) for part in key)
    return key


def _slice(text: str, section: _Section) -> str:
    return text[section.char_start : section.char_end]
