"""Pure metric math for the eval harness (definitions in evals/README.md).

Kept free of I/O and LLM calls so the numbers themselves are unit-testable;
evals/harness.py wires these onto golden records and the live pipeline.
"""

from collections.abc import Sequence


def recall_at_k(expected: set[str], retrieved: Sequence[str], k: int) -> float:
    """Fraction of golden-relevant chunks present in the top-k results.

    Raises ValueError on a record with no expected chunks: that is a malformed
    golden record, and silently scoring it 1.0 or 0.0 would hide the problem.
    """
    if not expected:
        raise ValueError("golden record has no expected chunks")
    top_k = set(retrieved[:k])
    return len(expected & top_k) / len(expected)


def citation_span_valid(text: str, char_start: int, char_end: int, cited: str) -> bool:
    """Mechanical half of citation validity: the span must sit inside the
    document's parsed text and its slice must equal the cited text.

    Whether the surrounding clause *supports* the statement is judged against
    the golden record's expected clause — human-graded, not mechanizable here.
    """
    if char_start < 0 or char_end <= char_start or char_end > len(text):
        return False
    return text[char_start:char_end] == cited


def citation_spans_valid(text: str, spans: Sequence[tuple[int, int]]) -> float:
    """Mechanical citation validity for a structured extraction: the fraction
    of emitted spans that sit inside the text (0 <= start < end <= len).

    The extraction service drops uncited items on its final gate attempt, so
    completed extractions only carry grounded spans and a score below 1.0
    means a gate bypass or harness/pipeline drift — the regression this
    tripwire exists for.
    """
    if not spans:
        return 1.0
    valid = sum(1 for char_start, char_end in spans if 0 <= char_start < char_end <= len(text))
    return valid / len(spans)


def _matched_precision_recall(expected: set, actual: Sequence) -> tuple[float, float]:
    """Shared set-matching core: precision over `actual`'s length (duplicates
    stay in the denominator — double-emitting is a real failure), recall over
    the expected set."""
    matched = len(expected & set(actual))
    precision = matched / len(actual) if actual else 0.0
    recall = matched / len(expected) if expected else 0.0
    return precision, recall


def extraction_precision_recall(
    expected: Sequence[tuple[str, str | None]],
    actual: Sequence[tuple[str, str | None]],
) -> tuple[float, float]:
    """Extraction accuracy matched on (clause_ref, owner); descriptions are
    free text and graded separately, per the metric definition in README.md.

    Owner matching is case-insensitive: contracts shout party names
    ("LICENSOR shall deliver") and a correct extraction must not lose the
    match to capitalisation alone.
    """

    def key(pair: tuple[str, str | None]) -> tuple[str, str | None]:
        clause_ref, owner = pair
        return (clause_ref, owner.casefold() if owner is not None else None)

    expected_set = {key(pair) for pair in expected}
    return _matched_precision_recall(expected_set, [key(pair) for pair in actual])


def diff_precision_recall(
    expected: Sequence[tuple[str, str | None]],
    actual: Sequence[tuple[str, str | None]],
) -> tuple[float, float]:
    """Change-detection accuracy matched on (kind, clause_ref) — mechanical
    grading for the `diff` golden task; description/severity quality awaits
    a grader.

    Identical versions (both sides empty) score 1.0, not zero: "no change"
    is a graded outcome, and a golden no-change record must reward an empty
    diff instead of dividing by zero.
    """
    if not expected and not actual:
        return 1.0, 1.0
    return _matched_precision_recall(set(expected), list(actual))


def impact_precision_recall(
    expected: Sequence[tuple[str, str | None]],
    actual: Sequence[tuple[str, str | None]],
) -> tuple[float, float]:
    """Impact-mapping accuracy for one Change, matched on (clause_ref, owner)
    — mechanical grading for the `impact_map` golden task; confidence
    calibration awaits a grader.

    Owner matching is case-insensitive, same as extraction: a correct mapping
    must not lose the match to party-name capitalisation alone. A change that
    affects no listed obligation and maps to nothing scores 1.0, not zero:
    "affects nothing" is a graded outcome (an added payment clause against an
    obligation list with no payment obligation, say).
    """
    if not expected and not actual:
        return 1.0, 1.0

    def key(pair: tuple[str, str | None]) -> tuple[str, str | None]:
        clause_ref, owner = pair
        return (clause_ref, owner.casefold() if owner is not None else None)

    expected_set = {key(pair) for pair in expected}
    return _matched_precision_recall(expected_set, [key(pair) for pair in actual])
