"""Unit tests for the eval metric math (evals/README.md metric definitions).

Pure logic: recall@k for retrieval, the mechanical half of citation validity,
and extraction accuracy matched on (clause_ref, owner).
"""

import pytest

from evals.metrics import (
    citation_span_valid,
    citation_spans_valid,
    extraction_precision_recall,
    recall_at_k,
)


class TestRecallAtK:
    def test_fraction_of_expected_chunks_present_in_top_k(self) -> None:
        score = recall_at_k(expected={"c1", "c2", "c3"}, retrieved=["c1", "x", "c4"], k=3)

        assert score == pytest.approx(1 / 3)

    def test_chunks_below_rank_k_do_not_count(self) -> None:
        score = recall_at_k(expected={"c1"}, retrieved=["x", "c1"], k=1)

        assert score == 0.0

    def test_perfect_retrieval_scores_one(self) -> None:
        score = recall_at_k(expected={"a", "b"}, retrieved=["b", "a", "c"], k=10)

        assert score == 1.0

    def test_nothing_retrieved_scores_zero(self) -> None:
        assert recall_at_k(expected={"a"}, retrieved=[], k=5) == 0.0

    def test_record_without_expected_chunks_is_malformed_and_raises(self) -> None:
        with pytest.raises(ValueError, match="no expected chunks"):
            recall_at_k(expected=set(), retrieved=["a"], k=5)

    def test_duplicate_retrieved_hits_do_not_inflate_the_score(self) -> None:
        score = recall_at_k(expected={"a"}, retrieved=["a", "a", "a"], k=3)

        assert score == 1.0


class TestCitationSpanValid:
    def test_span_that_matches_the_cited_slice_of_text_is_valid(self) -> None:
        text = "Section 8.2: Supplier shall remedy defects within thirty days."
        start = text.index("Supplier shall")
        end = start + len("Supplier shall remedy defects")

        assert citation_span_valid(text, start, end, "Supplier shall remedy defects") is True

    def test_span_pointing_at_different_text_is_invalid(self) -> None:
        text = "alpha beta gamma"

        assert citation_span_valid(text, 0, 5, "beta") is False

    def test_span_outside_the_parsed_text_is_invalid(self) -> None:
        text = "short"

        assert citation_span_valid(text, 0, 99, "short") is False

    def test_span_with_negative_offsets_is_invalid(self) -> None:
        assert citation_span_valid("abc", -1, 2, "ab") is False

    def test_empty_span_is_invalid(self) -> None:
        assert citation_span_valid("abc", 1, 1, "") is False


class TestCitationSpansValid:
    def test_fraction_of_spans_sitting_inside_the_text(self) -> None:
        text = "alpha beta"
        spans = [(0, 5), (6, 10), (0, 100)]

        assert citation_spans_valid(text, spans) == pytest.approx(2 / 3)

    def test_no_citations_is_perfectly_valid_not_a_divide_by_zero(self) -> None:
        assert citation_spans_valid("text", []) == 1.0

    def test_empty_or_inverted_spans_count_as_invalid(self) -> None:
        assert citation_spans_valid("abc", [(1, 1), (2, 1)]) == 0.0


class TestExtractionPrecisionRecall:
    def test_matched_on_clause_ref_and_owner_not_description(self) -> None:
        expected = [("8.2", "Supplier")]
        actual = [("8.2", "Supplier")]

        precision, recall = extraction_precision_recall(expected, actual)

        assert precision == 1.0
        assert recall == 1.0

    def test_same_clause_ref_with_different_owner_does_not_match(self) -> None:
        precision, recall = extraction_precision_recall([("8.2", "Supplier")], [("8.2", "Buyer")])

        assert precision == 0.0
        assert recall == 0.0

    def test_extra_extractions_lower_precision(self) -> None:
        precision, _ = extraction_precision_recall(
            [("8.2", "Supplier")], [("8.2", "Supplier"), ("9.1", "Buyer")]
        )

        assert precision == pytest.approx(1 / 2)

    def test_missed_golden_obligations_lower_recall(self) -> None:
        _, recall = extraction_precision_recall(
            [("8.2", "Supplier"), ("9.1", "Buyer")], [("8.2", "Supplier")]
        )

        assert recall == pytest.approx(1 / 2)

    def test_nothing_extracted_gives_zero_precision_not_a_crash(self) -> None:
        precision, recall = extraction_precision_recall([("8.2", "Supplier")], [])

        assert precision == 0.0
        assert recall == 0.0

    def test_owner_matches_case_insensitively(self) -> None:
        """Locks the case-insensitivity rationale documented in metrics.py."""
        precision, recall = extraction_precision_recall(
            [("2.1", "Licensor")], [("2.1", "LICENSOR")]
        )

        assert precision == 1.0
        assert recall == 1.0

    def test_duplicate_matches_are_counted_once(self) -> None:
        precision, recall = extraction_precision_recall(
            [("8.2", "Supplier")], [("8.2", "Supplier"), ("8.2", "Supplier")]
        )

        assert precision == pytest.approx(1 / 2)
        assert recall == 1.0
