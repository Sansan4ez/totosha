KB Hybrid Search Design
=======================

Purpose
-------

This document describes the repository knowledge-base pipeline for the Google ADK text agent. It is the current source of truth for Markdown chunking, PostgreSQL schema expectations, seeding, and hybrid retrieval behavior.

System Flow
-----------

1. `knowledge_base/*.md` is parsed by `src/seed_kb.py`.
2. Files are chunked on Markdown `###` headings.
3. `src/db.py` generates embeddings and writes chunks into PostgreSQL.
4. Runtime tool `search_knowledge_base` in `src/adk_text_agent/tools.py` calls `src/db.py`.
5. The ADK agent consumes structured KB results during `/run` and `/run_sse`.

Retrieval Model
---------------

The repository uses hybrid retrieval with reciprocal-rank fusion over three PostgreSQL-backed strategies:

- full-text search over `tsvector`
- semantic search over `pgvector`
- fuzzy search over `pg_trgm`

The design goal is recall across exact matches, semantic similarity, and typo-tolerant matching without introducing a separate vector store.

Data Model
----------

Primary table: `knowledge_chunks`

- `source_file` — source Markdown file path
- `heading` — chunk heading
- `content` — chunk body
- `fts` — generated `tsvector`
- `embedding` — vector embedding
- `file_hash` — incremental reindex key

Behavior Rules
--------------

- Chunk boundaries are defined by Markdown `###`.
- Text before the first `###` is ignored for chunk generation.
- Empty chunks are skipped.
- Seed can run full reset, incremental update, or file-targeted update through `src/seed_kb.py`.
- Slow DB validation uses the dedicated test database described in `docs/architecture/adr/ADR-002-database-naming-and-test-db.md`.

Operational Entry Points
------------------------

- Quick local seed flow → `README.md`
- DB/test lifecycle → `docs/operations/index.md`
- Runtime contract consuming the KB tool → `specs/index.md`
