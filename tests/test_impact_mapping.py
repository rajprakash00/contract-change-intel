"""Unit tests for impact-mapping candidate selection (pure logic, per PLAN's
engineering policy): which of the base version's extracted Obligations are
shown to the LLM for one Change, given the document-scoped search hits.
"""

from uuid import uuid4

from app.services.extraction import Citation, Obligation
from app.services.impact import select_candidates
from app.services.search import SearchHit


def obligation(clause_ref: str, char_start: int, char_end: int) -> Obligation:
    return Obligation(
        clause_ref=clause_ref,
        description=f"{clause_ref} obligation",
        owner=None,
        citation=Citation(char_start=char_start, char_end=char_end),
        confidence=0.9,
    )


def chunk(char_start: int, char_end: int) -> SearchHit:
    return SearchHit(
        document_id=uuid4(),
        document_sha256="0" * 64,
        filename="base.docx",
        chunk_id=uuid4(),
        ordinal=0,
        text="chunk text",
        char_start=char_start,
        char_end=char_end,
        score=1.0,
    )


class TestSelectCandidates:
    def test_obligation_overlapping_a_retrieved_chunk_is_selected(self) -> None:
        obligations = [obligation("2.1", 10, 40)]
        hits = [chunk(30, 60)]

        assert select_candidates(obligations, hits, limit=5) == obligations

    def test_obligations_are_ordered_by_chunk_rank_then_obligation_order(self) -> None:
        # Chunk rank dominates: the obligation cited inside the second-ranked
        # chunk comes after both obligations inside the first-ranked one.
        second_first = obligation("5.1", 100, 120)
        second_second = obligation("5.2", 125, 140)
        top = obligation("2.1", 10, 40)
        hits = [chunk(100, 150), chunk(0, 50)]
        obligations = [top, second_first, second_second]

        assert select_candidates(obligations, hits, limit=5) == [second_first, second_second, top]

    def test_obligation_cited_outside_every_candidate_chunk_is_not_selected(self) -> None:
        cited = obligation("2.1", 10, 40)
        elsewhere = obligation("9.1", 500, 520)

        assert select_candidates([cited, elsewhere], [chunk(30, 60)], limit=5) == [cited]

    def test_adjacent_spans_do_not_overlap(self) -> None:
        # End-exclusive spans: an obligation ending exactly where a chunk
        # starts shares no character and must not be selected on that basis.
        before = obligation("2.1", 0, 30)

        assert select_candidates([before], [chunk(30, 60)], limit=5) == []

    def test_an_obligation_overlapping_two_chunks_is_selected_once(self) -> None:
        spanning = obligation("2.1", 10, 80)

        assert select_candidates([spanning], [chunk(0, 40), chunk(40, 90)], limit=5) == [spanning]

    def test_limit_caps_the_candidate_list(self) -> None:
        in_first = obligation("2.1", 10, 20)
        in_second = obligation("3.1", 110, 120)

        assert select_candidates(
            [in_first, in_second], [chunk(0, 40), chunk(100, 140)], limit=1
        ) == [in_first]

    def test_no_search_hits_yields_no_candidates(self) -> None:
        obligations = [obligation("2.1", 10, 40)]

        assert select_candidates(obligations, [], limit=5) == []
