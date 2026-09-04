"""Golden-record eval harness (W3·C): runs the pipeline against
evals/golden/<task>.jsonl and scores the metrics defined in evals/README.md.

The metric math lives in evals/metrics.py (pure, unit-tested); this module
only wires records → pipeline functions → scores. Usage:

    uv run python -m evals.harness --task retrieve --k 5 --k 10
    uv run python -m evals.harness --task extract_obligations

Record shapes (see evals/README.md for the JSONL rationale):

- retrieve: input {"tenant_id", "query"}; expected {"chunks":
  [{"document_sha256", "ordinal"}]} — a chunk is keyed by its document's
  sha256 plus its ordinal, which survives re-ingestion (chunk UUIDs do not).
- extract_obligations: input {"document_sha256", "text"}; expected
  {"obligations": [{"clause_ref", "owner"}]} — matched on (clause_ref, owner);
  the sha ties the record to the stored source bytes for citation checking
  once extraction emits Citations.
- diff: input {"document_sha256", "base_text", "amended_text"}; expected
  {"changes": [{"kind", "clause_ref"}]} — matched on (kind, clause_ref).
  Graded mechanically (W4·C): the texts run through the real parse + diff
  pipeline with no LLM in the loop, so the task is cheap and deterministic.
  Impact grading is deferred to W5 — the mapping must exist first.

Citation validity is graded mechanically against the record's input text
(evals.metrics.citation_spans_valid): the pipeline's strict gate rejects
invalid spans after one retry, so a score below 1.0 flags gate bypass or
drift, and a record whose extraction fails entirely scores zero across the
board. Graded description comparison awaits a grader; the mechanical
metrics here match on (clause_ref, owner) only.

Golden records land with the first real documents (W3·D); with an empty
golden/ directory the harness says so and exits 0.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.llm.client import LlmOutputError, OpenAiClient
from app.services.diffing import detect_changes
from app.services.extraction import extract_obligations
from app.services.parsing import parse
from app.services.search import search
from evals.metrics import (
    citation_spans_valid,
    diff_precision_recall,
    extraction_precision_recall,
    recall_at_k,
)

GOLDEN_DIR = Path(__file__).parent / "golden"

DEFAULT_KS = (5, 10)


def load_records(task: str) -> list[dict[str, Any]]:
    path = GOLDEN_DIR / f"{task}.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: malformed golden record: {exc}") from exc
    return records


def chunk_key(document_sha256: str, ordinal: int) -> str:
    """Stable chunk identity across re-ingestions: document sha256 + ordinal.

    The single definition of the format: expected chunks and retrieved hits
    must key identically or recall silently drops to zero.
    """
    return f"{document_sha256}:{ordinal}"


def _aggregate(per_record: dict[str, dict[str, float]], names: list[str]) -> dict[str, float]:
    return {
        name: sum(scores[name] for scores in per_record.values()) / len(per_record)
        for name in names
    }


async def run_retrieve(
    records: list[dict[str, Any]],
    llm: OpenAiClient,
    ks: list[int],
    settings: Settings,
) -> dict[str, Any]:
    per_record: dict[str, dict[str, float]] = {}
    async with get_sessionmaker()() as session:
        for record in records:
            input_data = record["input"]
            expected = {
                chunk_key(chunk["document_sha256"], chunk["ordinal"])
                for chunk in record["expected"]["chunks"]
            }
            hits = await search(
                session,
                llm=llm,
                tenant_id=input_data["tenant_id"],
                query=input_data["query"],
                limit=max(ks),
            )
            retrieved = [chunk_key(hit.document_sha256, hit.ordinal) for hit in hits]
            per_record[record["id"]] = {
                f"recall@{k}": recall_at_k(expected, retrieved, k) for k in ks
            }
    metric_names = [f"recall@{k}" for k in ks]
    return {
        "task": "retrieve",
        "records": len(per_record),
        "metrics": _aggregate(per_record, metric_names),
        "per_record": per_record,
        "embedding_model": settings.openai_embedding_model,
    }


async def run_extraction(
    records: list[dict[str, Any]], llm: OpenAiClient, settings: Settings
) -> dict[str, Any]:
    per_record: dict[str, dict[str, float]] = {}
    for record in records:
        text = record["input"]["text"]
        expected = [(o["clause_ref"], o["owner"]) for o in record["expected"]["obligations"]]
        try:
            extraction = await extract_obligations(llm, document_text=text)
        except LlmOutputError:
            # The strict citation gate exhausted its retry: nothing usable
            # came out of this record, so it scores zero across the board.
            per_record[record["id"]] = {
                "precision": 0.0,
                "recall": 0.0,
                "citation_validity": 0.0,
            }
            continue
        actual = [(o.clause_ref, o.owner) for o in extraction.obligations]
        precision, recall = extraction_precision_recall(expected, actual)
        spans = [
            (item.citation.char_start, item.citation.char_end)
            for item in (*extraction.obligations, *extraction.defined_terms)
        ]
        per_record[record["id"]] = {
            "precision": precision,
            "recall": recall,
            "citation_validity": citation_spans_valid(text, spans),
        }
    return {
        "task": "extract_obligations",
        "records": len(per_record),
        "metrics": _aggregate(per_record, ["precision", "recall", "citation_validity"]),
        "per_record": per_record,
    }


async def run_diff(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The diff task is pure: parse both texts, align + diff, grade on
    (kind, clause_ref). No database session, no LLM — deterministic and free."""
    per_record: dict[str, dict[str, float]] = {}
    for record in records:
        base_text = parse("text/plain", record["input"]["base_text"].encode()).text
        amended_text = parse("text/plain", record["input"]["amended_text"].encode()).text
        actual = [(c.kind.value, c.clause_ref) for c in detect_changes(base_text, amended_text)]
        expected = [
            (change["kind"], change["clause_ref"]) for change in record["expected"]["changes"]
        ]
        precision, recall = diff_precision_recall(expected, actual)
        per_record[record["id"]] = {"precision": precision, "recall": recall}
    return {
        "task": "diff",
        "records": len(per_record),
        "metrics": _aggregate(per_record, ["precision", "recall"]),
        "per_record": per_record,
    }


def _stamp(report: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Make a stored report self-describing: what ran it and when. Reports
    land in evals/runs/ (gitignored) or evals/baselines/ (committed), where
    a JSON blob without provenance is uninterpretable months later."""
    report["model"] = settings.openai_model
    report["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run golden-record evals.")
    parser.add_argument(
        "--task", required=True, choices=("retrieve", "extract_obligations", "diff")
    )
    parser.add_argument(
        "--k", type=int, action="append", default=[], help="recall@k (retrieve only)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="also write the JSON report to this path (e.g. evals/runs/<date>-<task>.json)",
    )
    args = parser.parse_args()

    records = load_records(args.task)
    if not records:
        print(f"no golden records for task {args.task!r} in {GOLDEN_DIR}")
        return 0

    settings = get_settings()
    # Only tasks that call the model construct a client: diff runs the pure
    # pipeline, so it needs neither an API key nor the database.
    llm = OpenAiClient(settings) if args.task != "diff" else None
    if llm is not None:
        init_engine(settings.database_url)
    try:
        if args.task == "retrieve":
            assert llm is not None
            report = await run_retrieve(
                records, llm, ks=args.k or list(DEFAULT_KS), settings=settings
            )
        elif args.task == "extract_obligations":
            assert llm is not None
            report = await run_extraction(records, llm, settings=settings)
        else:
            report = await run_diff(records)
    finally:
        if llm is not None:
            await llm.aclose()
            await dispose_engine()
    report = _stamp(report, settings)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report, indent=2) + "\n"
        await asyncio.to_thread(out.write_text, payload, "utf-8")
        print(f"report written to {out}")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
