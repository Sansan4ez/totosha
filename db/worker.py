#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import logging
from pathlib import Path

import asyncpg
from opentelemetry import trace
from pgvector.asyncpg import register_vector

from catalog_loader import seed_json_sources
from common import DEFAULT_KB_MANIFEST, DEFAULT_SOURCES_DIR, DEFAULT_WIKI_DIR, get_rw_dsn
from kb_loader import seed_knowledge_chunks
from observability import setup_observability
from search_docs import build_search_docs

setup_observability("corp-db-worker")
logger = logging.getLogger("corp-db-worker")


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    timeout_ms = int(os.getenv("CORP_DB_RW_STATEMENT_TIMEOUT_MS", "60000"))
    await conn.execute(f"SET statement_timeout = {timeout_ms}")


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        get_rw_dsn(),
        min_size=1,
        max_size=4,
        init=_init_connection,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operator-only worker for corp-pg-db")
    parser.add_argument("--sources-dir", type=Path, default=DEFAULT_SOURCES_DIR)
    parser.add_argument("--wiki-dir", type=Path, default=DEFAULT_WIKI_DIR)
    parser.add_argument("--kb-manifest", type=Path, default=DEFAULT_KB_MANIFEST)
    parser.add_argument("--reset", action="store_true", help="Reset mutable target tables before seeding")
    parser.add_argument("--incremental", action="store_true", help="Skip unchanged KB files when possible")
    parser.add_argument("--skip-embeddings", action="store_true", help="Build rows without vector embeddings")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed-json", help="Load canonical JSON sources into normalized tables")
    subparsers.add_parser("seed-kb", help="Load promoted wiki subset into knowledge_chunks")
    subparsers.add_parser("build-search-docs", help="Rebuild corp_search_docs from normalized tables")
    subparsers.add_parser("rebuild", help="Run seed-json, seed-kb and build-search-docs in order")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    pool = await get_pool()
    try:
        tracer = trace.get_tracer("corp-db-worker")
        with tracer.start_as_current_span(f"corp-db-worker.{args.command}") as span:
            span.set_attribute("worker.command", args.command)
            span.set_attribute("worker.skip_embeddings", args.skip_embeddings)
            span.set_attribute("worker.incremental", args.incremental)
            span.set_attribute("worker.reset", args.reset)
            logger.info("Starting worker command=%s", args.command)
            async with pool.acquire() as conn:
                result: dict[str, object]
                embeddings_enabled = not args.skip_embeddings
                if args.command == "seed-json":
                    result = {
                        "command": "seed-json",
                        "counts": await seed_json_sources(conn, args.sources_dir),
                    }
                elif args.command == "seed-kb":
                    result = {
                        "command": "seed-kb",
                        "counts": await seed_knowledge_chunks(
                            conn,
                            args.wiki_dir,
                            args.kb_manifest,
                            incremental=args.incremental,
                            reset=args.reset,
                            embeddings_enabled=embeddings_enabled,
                        ),
                    }
                elif args.command == "build-search-docs":
                    result = {
                        "command": "build-search-docs",
                        "counts": await build_search_docs(conn, embeddings_enabled=embeddings_enabled),
                    }
                else:
                    json_counts = await seed_json_sources(conn, args.sources_dir)
                    kb_counts = await seed_knowledge_chunks(
                        conn,
                        args.wiki_dir,
                        args.kb_manifest,
                        incremental=args.incremental,
                        reset=args.reset,
                        embeddings_enabled=embeddings_enabled,
                    )
                    doc_counts = await build_search_docs(conn, embeddings_enabled=embeddings_enabled)
                    result = {
                        "command": "rebuild",
                        "counts": {
                            "json": json_counts,
                            "knowledge_chunks": kb_counts,
                            "search_docs": doc_counts,
                        },
                    }
                logger.info("Worker command completed command=%s", args.command)
                print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
