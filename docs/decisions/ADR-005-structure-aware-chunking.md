# ADR-005: Structure-aware chunking with recursive fallback

## Context

W3 ingestion turns a parsed document into chunks — the unit that gets embedded,
indexed in pgvector, retrieved by hybrid search, and cited by extracted
obligations. Contracts are clause-structured: an obligation lives inside a
clause, and a citation that lands mid-clause is nearly useless to a reviewer.
Chunk boundaries are load-bearing downstream — embeddings, the HNSW index, and
citation offsets are all built on them — so switching strategy later means
re-parsing, re-chunking, and re-embedding every stored document.

## Decision

Chunking is structure-aware, with a two-stage fallback:

1. **Primary**: one chunk per clause, taken from the parser's structure (DOCX
   heading styles via python-docx, PDF layout via pdfplumber). Boundaries are
   semantic, not statistical.
2. **Fallback**: a clause exceeding the size cap (sized to the embedding
   model's context budget) is split recursively at paragraph level, with
   overlap, so no context is lost at the seam.
3. **Last resort**: text with no detectable structure (plain text) falls back
   to fixed-size windows.

The chunker is pure logic → unit tests per PLAN's engineering policy. The size
cap is a constant, not a settings knob (one caller, per code taste).

## Consequences

- Chunk sizes vary with clause length — good for meaning, mild imbalance for
  the index.
- Re-chunking means re-ingestion; the re-run path (delete-then-insert after a
  terminal job state) already exists by design.
- Plain-text uploads never get clause-level chunks; acceptable, since real
  agreements arrive as PDF/DOCX.

## Rejected alternative

Generic recursive (LangChain-style) or fixed-size chunking for everything —
simpler and the common default, but it splits obligations mid-clause, degrading
both retrieval precision and citation usefulness. Semantic chunking (embedding
sentences, cutting at distance jumps) rejected as circular — it needs
embeddings before chunking exists — and costly.
