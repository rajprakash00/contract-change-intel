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

Citation validity needs a Citations producer (extraction emits none yet, W4);
the mechanical span check is ready in evals.metrics.citation_span_valid.
Graded description comparison likewise awaits a grader; the mechanical
metrics here match on (clause_ref, owner) only.

Golden records land with the first real documents (W3·D); with an empty
golden/ directory the harness says so and exits 0.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.llm.client import OpenAiClient
from app.services.extraction import extract_obligations
from app.services.search import search
from evals.metrics import extraction_precision_recall, recall_at_k

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
    records: list[dict[str, Any]], llm: OpenAiClient, ks: list[int]
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
    }


async def run_extraction(records: list[dict[str, Any]], llm: OpenAiClient) -> dict[str, Any]:
    per_record: dict[str, dict[str, float]] = {}
    for record in records:
        expected = [(o["clause_ref"], o["owner"]) for o in record["expected"]["obligations"]]
        extraction = await extract_obligations(llm, document_text=record["input"]["text"])
        actual = [(o.clause_ref, o.owner) for o in extraction.obligations]
        precision, recall = extraction_precision_recall(expected, actual)
        per_record[record["id"]] = {"precision": precision, "recall": recall}
    return {
        "task": "extract_obligations",
        "records": len(per_record),
        "metrics": _aggregate(per_record, ["precision", "recall"]),
        "per_record": per_record,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run golden-record evals.")
    parser.add_argument("--task", required=True, choices=("retrieve", "extract_obligations"))
    parser.add_argument(
        "--k", type=int, action="append", default=[], help="recall@k (retrieve only)"
    )
    args = parser.parse_args()

    records = load_records(args.task)
    if not records:
        print(f"no golden records for task {args.task!r} in {GOLDEN_DIR}")
        return 0

    settings = get_settings()
    llm = OpenAiClient(settings)  # raises LlmNotConfiguredError without a key
    init_engine(settings.database_url)
    try:
        if args.task == "retrieve":
            report = await run_retrieve(records, llm, ks=args.k or list(DEFAULT_KS))
        else:
            report = await run_extraction(records, llm)
    finally:
        await llm.aclose()
        await dispose_engine()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
