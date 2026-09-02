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

from evals.harness import load_records
from evals.seed_fixtures import EVAL_TENANT_ID, FIXTURES_DIR

FIXTURE_SHAS_PATH = Path(__file__).resolve().parent.parent / "evals" / "fixture_shas.json"


def _fixture_shas() -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(FIXTURES_DIR.glob("*.pdf"))
    }


@pytest.mark.parametrize("task", ["retrieve", "extract_obligations"])
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


def test_fixture_shas_are_stable_against_committed_hashes() -> None:
    """Re-saving a fixture (even byte-identical intent) would silently orphan
    every golden record keyed by sha256 — fail instead of drifting."""
    manifest_path = FIXTURE_SHAS_PATH
    committed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert committed == _fixture_shas(), (
        "fixtures/cuad changed but evals/fixture_shas.json was not regenerated "
        "(and every sha256-keyed golden record with it)"
    )
