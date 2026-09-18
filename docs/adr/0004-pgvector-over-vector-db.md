# ADR 0004 — pgvector instead of a dedicated vector database

**Status:** accepted

## Context
Triage retrieval needs top-3 similarity search over runbook chunks. Corpus size: 7 runbooks,
~40 chunks. It will maybe reach hundreds of chunks, never millions.

## Decision
Store 768-dim embeddings in Postgres via pgvector (`runbook_chunks.embedding`,
cosine distance, no ANN index — exact scan).

## Rationale
- The `timescale/timescaledb-ha` image already ships pgvector: zero extra services.
- At this corpus size an exact scan is microseconds; an ANN index and a separate vector DB
  (Qdrant/Pinecone/…) would be pure operational overhead.
- Embeddings, chunks, and the rest of the data share one backup/migration/transaction story.

## Consequences
- Embedding dimension is fixed at 768 in the schema; both embedders (Gemini with
  `outputDimensionality: 768`, and the offline hashing fallback) target it, and chunks record
  which embedder indexed them so queries never mix spaces.
- If the corpus ever grows 1000x, add an HNSW index — still no new service.
