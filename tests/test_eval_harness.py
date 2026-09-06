"""Harness wiring for the impact_map golden task (unit-level, LLM faked at
the httpx2 seam like the other LLM tests): golden records run through the
real parse → diff → per-Change mapping pipeline and grade mechanically.
"""

import json

import pytest

from evals.harness import run_impact
from tests.fake_openai import fake_llm_client, fake_llm_client_queue

BASE_TEXT = (
    "2.1 LICENSOR shall deliver Content to plan_b within 14 days.\n\n"
    "2.2 LICENSOR shall deliver Content per plan_b's specifications.\n\n"
    "3.1 plan_b shall pay LICENSOR on each delivery."
)
AMENDED_TEXT = (
    "2.1 LICENSOR shall deliver Content to plan_b within 30 days.\n\n"
    "2.2 LICENSOR shall deliver Content per plan_b's specifications.\n\n"
    "3.1 plan_b shall pay LICENSOR on each delivery."
)


def obligations() -> list[dict]:
    base = BASE_TEXT
    spans = [
        ("2.1", "LICENSOR", base.index("LICENSOR shall deliver"), base.index("14 days.") + 8),
        ("2.2", "LICENSOR", base.index("2.2 LICENSOR"), base.index("specifications.") + 14),
        ("3.1", "plan_b", base.index("3.1 plan_b"), base.index("each delivery.") + 14),
    ]
    return [
        {
            "clause_ref": ref,
            "description": f"{ref} obligation",
            "owner": owner,
            "citation": {"char_start": start, "char_end": end},
        }
        for ref, owner, start, end in spans
    ]


def record(changes: list[dict]) -> dict:
    return {
        "id": "impact-test",
        "input": {
            "base_text": BASE_TEXT,
            "amended_text": AMENDED_TEXT,
            "obligations": obligations(),
        },
        "expected": {"changes": changes},
    }


def affected(clause_ref: str, owner: str) -> dict:
    return {"clause_ref": clause_ref, "owner": owner}


async def test_per_change_expected_impacts_grade_against_the_mapping_calls() -> None:
    """The mapping call per detected Change is answered by the fake wire in
    detection order; the record's precision/recall come out of the per-change
    grading against the golden affected lists."""
    record_ = record(
        [
            {
                "kind": "modified",
                "clause_ref": "2.1",
                "affected": [affected("2.1", "LICENSOR")],
            }
        ]
    )
    # Detected order: modified 2.1 only. The mapping names candidate index 0.
    async with fake_llm_client_queue(
        [json.dumps({"impacts": [{"index": 0, "confidence": 0.9}]})]
    ) as (llm, requests):
        report = await run_impact([record_], llm)

    assert len(requests) == 1  # one mapping call per detected Change
    assert report["task"] == "impact_map"
    assert report["records"] == 1
    assert report["metrics"]["precision"] == pytest.approx(1.0)
    assert report["metrics"]["recall"] == pytest.approx(1.0)
    assert report["per_record"]["impact-test"]["precision"] == pytest.approx(1.0)


async def test_record_with_no_changes_scores_perfect_without_touching_the_llm() -> None:
    """A no-change record maps nothing; grading is vacuously perfect and the
    wire stays cold."""
    record_ = {**record([]), "input": {**record([])["input"], "amended_text": BASE_TEXT}}

    async with fake_llm_client_queue([]) as (llm, requests):
        report = await run_impact([record_], llm)

    assert requests == []
    assert report["per_record"]["impact-test"] == {"precision": 1.0, "recall": 1.0}


async def test_change_with_no_expected_impacts_rewards_an_empty_mapping() -> None:
    """A change that affects none of the listed obligations expects an empty
    affected list; an empty mapping call scores 1.0 for that change."""
    record_ = record(
        [
            {
                "kind": "modified",
                "clause_ref": "2.1",
                "affected": [],
            }
        ]
    )

    async with fake_llm_client(json.dumps({"impacts": []})) as (llm, _):
        report = await run_impact([record_], llm)

    assert report["metrics"]["precision"] == pytest.approx(1.0)
    assert report["metrics"]["recall"] == pytest.approx(1.0)


async def test_invalid_candidate_index_in_a_mapping_scores_zero_for_the_record() -> None:
    """A mapping call that cites an unknown candidate index fails the whole
    record across the board, like an extraction that fails its gate."""
    record_ = record(
        [
            {
                "kind": "modified",
                "clause_ref": "2.1",
                "affected": [affected("2.1", "LICENSOR")],
            }
        ]
    )

    async with fake_llm_client(json.dumps({"impacts": [{"index": 9, "confidence": 0.9}]})) as (
        llm,
        _,
    ):
        report = await run_impact([record_], llm)

    assert report["per_record"]["impact-test"] == {"precision": 0.0, "recall": 0.0}
