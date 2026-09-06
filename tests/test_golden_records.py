"""Golden records are committed data: lock their shape and their tie to the
CUAD fixture documents (evals/README.md). Pure checks — no database, no
network — so a malformed record or a re-saved fixture fails fast in CI,
not at eval time. Semantics (is the expected chunk the *right* chunk?) stay
with the human reviewer; these tests only lock structure and provenance.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.services.impact import CANDIDATE_LIMIT
from evals.harness import load_records
from evals.seed_fixtures import EVAL_TENANT_ID, FIXTURES_DIR

FIXTURE_SHAS_PATH = Path(__file__).resolve().parent.parent / "evals" / "fixture_shas.json"
BASELINES_DIR = Path(__file__).resolve().parent.parent / "evals" / "baselines"


def _fixture_shas() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(FIXTURES_DIR.glob("*.pdf"))
    }


@pytest.mark.parametrize("task", ["retrieve", "extract_obligations", "diff", "impact_map"])
def test_golden_records_load_and_carry_unique_ids_per_task(task: str) -> None:
    records = load_records(task)
    assert records, f"no golden records committed for {task!r}; golden/ must stay seeded"
    ids = [record["id"] for record in records]
    assert len(ids) == len(set(ids)), f"duplicate ids in {task}.jsonl: {sorted(ids)}"


def test_retrieve_records_target_eval_tenant_and_fixture_documents() -> None:
    shas = set(_fixture_shas().values())
    for record in load_records("retrieve"):
        assert record["input"]["tenant_id"] == str(EVAL_TENANT_ID), record["id"]
        chunks = record["expected"]["chunks"]
        assert chunks, f"{record['id']} expects no chunks — a recall of zero forever"
        for chunk in chunks:
            assert chunk["document_sha256"] in shas, (
                f"{record['id']} references a document that is not a committed fixture: "
                f"{chunk['document_sha256']}"
            )
            assert isinstance(chunk["ordinal"], int) and chunk["ordinal"] >= 0


def test_extract_records_reference_fixture_documents_and_carry_text() -> None:
    shas = set(_fixture_shas().values())
    for record in load_records("extract_obligations"):
        sha = record["input"]["document_sha256"]
        assert sha in shas, f"{record['id']} references a non-fixture document: {sha}"
        assert record["input"]["text"].strip(), record["id"]
        obligations = record["expected"]["obligations"]
        assert obligations, f"{record['id']} expects no obligations"
        for obligation in obligations:
            assert obligation["clause_ref"].strip(), record["id"]
            assert obligation["owner"] is None or obligation["owner"].strip(), record["id"]


_KINDS = {"added", "removed", "modified"}


def test_diff_records_tie_their_texts_to_a_committed_fixture() -> None:
    shas = set(_fixture_shas().values())
    for record in load_records("diff"):
        sha = record["input"]["document_sha256"]
        assert sha in shas, f"{record['id']} references a non-fixture document: {sha}"
        assert record["input"]["base_text"].strip(), record["id"]
        assert record["input"]["amended_text"].strip() or record["id"] == "diff-002", (
            f"{record['id']} amended text is empty (only deliberate no-change "
            "records may carry an empty amendment)"
        )
        for change in record["expected"]["changes"]:
            assert change["kind"] in _KINDS, f"{record['id']} has unknown kind {change['kind']}"
            assert change["clause_ref"] is None or change["clause_ref"].strip(), record["id"]


def test_impact_records_tie_their_texts_to_a_fixture_and_carry_cited_obligations() -> None:
    """Impact records restate the diff task's texts plus the base version's
    obligations: citations must sit inside the parsed base text so the mapping
    call sees grounded candidates, and every expected change carries an
    affected list keyed on (kind, clause_ref)."""
    shas = set(_fixture_shas().values())
    for record in load_records("impact_map"):
        sha = record["input"]["document_sha256"]
        assert sha in shas, f"{record['id']} references a non-fixture document: {sha}"
        assert record["input"]["base_text"].strip(), record["id"]
        assert record["input"]["amended_text"].strip(), record["id"]
        obligations = record["input"]["obligations"]
        assert obligations, f"{record['id']} lists no candidate obligations"
        assert len(obligations) <= CANDIDATE_LIMIT, (
            f"{record['id']} lists more obligations than the harness will show the "
            "mapping call — anything past CANDIDATE_LIMIT is silently unmatchable"
        )
        for obligation in obligations:
            span = obligation["citation"]
            text = record["input"]["base_text"][span["char_start"] : span["char_end"]]
            assert (
                0 <= span["char_start"] < span["char_end"] <= len(record["input"]["base_text"])
            ), f"{record['id']} obligation {obligation['clause_ref']} cites outside the text"
            assert text.strip(), (
                f"{record['id']} obligation {obligation['clause_ref']} cites empty text"
            )
        for change in record["expected"]["changes"]:
            assert change["kind"] in _KINDS, f"{record['id']} has unknown kind {change['kind']}"
            assert change["clause_ref"] is None or change["clause_ref"].strip(), record["id"]
            for impact in change["affected"]:
                assert impact["clause_ref"].strip(), record["id"]
                assert impact["owner"] is None or impact["owner"].strip(), record["id"]


@pytest.mark.parametrize("task", ["retrieve", "extract_obligations", "diff", "impact_map"])
def test_committed_baseline_covers_exactly_the_golden_records(task: str) -> None:
    """Baselines are deliberate snapshots (evals/README.md): adding or removing
    a golden record without refreshing the baseline must fail loudly, or the
    committed numbers silently stop describing the records they claim to."""
    baseline_path = BASELINES_DIR / f"{task}.json"
    assert baseline_path.exists(), f"no committed baseline for {task!r}; run the harness"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert baseline["task"] == task
    golden_ids = {record["id"] for record in load_records(task)}
    assert set(baseline["per_record"]) == golden_ids, (
        f"baseline {task}.json covers {sorted(baseline['per_record'])} but golden has "
        f"{sorted(golden_ids)} — refresh the baseline from a harness run"
    )
    assert baseline["model"].strip() and baseline["generated_at"].strip(), (
        "baseline lacks provenance (model/generated_at); use the harness --out flag"
    )


def test_fixture_shas_are_stable_against_committed_hashes() -> None:
    """Re-saving a fixture (even byte-identical intent) would silently orphan
    every golden record keyed by sha256 — fail instead of drifting."""
    manifest_path = FIXTURE_SHAS_PATH
    committed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert committed == _fixture_shas(), (
        "fixtures/cuad changed but evals/fixture_shas.json was not regenerated "
        "(and every sha256-keyed golden record with it)"
    )
