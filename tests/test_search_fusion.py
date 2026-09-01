"""Unit tests for reciprocal rank fusion (ADR-006): pure rank math, no I/O.

The fusion is the heart of hybrid search: two engines' rankings must merge so
that agreement between the engines beats a top rank in either one alone.
"""

import pytest

from app.services.search import RRF_K, rrf_fuse


class TestRrfFusion:
    def test_item_ranked_by_both_engines_outranks_top_of_either_single_engine(self) -> None:
        fused = rrf_fuse([["a", "b"], ["b", "c"]], k=RRF_K)

        assert fused[0][0] == "b", "agreement between engines must win over a single top rank"

    def test_score_is_the_sum_of_one_over_k_plus_rank_across_rankings(self) -> None:
        fused = rrf_fuse([["a"], ["a", "b"]], k=10)

        scores = dict(fused)
        assert scores["a"] == pytest.approx(1 / 11 + 1 / 11)
        assert scores["b"] == pytest.approx(1 / 12)
        assert scores["a"] > scores["b"]

    def test_result_is_sorted_by_fused_score_descending(self) -> None:
        fused = rrf_fuse([["a", "b", "c"], ["c"]], k=60)

        scores = [score for _, score in fused]
        assert scores == sorted(scores, reverse=True)

    def test_tied_items_keep_first_appearance_order(self) -> None:
        # "x" and "y" appear in exactly one list each at the same rank; the tie
        # must break deterministically (first seen wins) so eval runs are stable.
        fused = rrf_fuse([["x"], ["y"]], k=60)

        assert [item for item, _ in fused] == ["x", "y"]

    def test_no_rankings_yields_no_hits(self) -> None:
        assert rrf_fuse([], k=RRF_K) == []

    def test_all_empty_rankings_yield_no_hits(self) -> None:
        assert rrf_fuse([[], []], k=RRF_K) == []

    def test_single_engine_ranking_preserves_its_order(self) -> None:
        fused = rrf_fuse([["a", "b", "c"]], k=RRF_K)

        assert [item for item, _ in fused] == ["a", "b", "c"]
