"""
Seed the knowledge base from Markdown files.

Usage:
    uv run python src/seed_kb.py                  # full re-index
    uv run python src/seed_kb.py --reset          # truncate and full re-index
    uv run python src/seed_kb.py --incremental    # only changed files
    uv run python src/seed_kb.py --file path.md   # single file
"""

import argparse
import asyncio
import hashlib
import logging
import os
import re
import sys

import asyncpg
from dotenv import load_dotenv
from pgvector.asyncpg import register_vector

from telemetry import configure_observability

logger = logging.getLogger(__name__)

load_dotenv(".env.local")
configure_observability()

from db import EMBEDDING_MODEL, get_embedding  # noqa: E402

KB_DIR = os.getenv("KNOWLEDGE_BASE_DIR", "knowledge_base")


def compute_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_md_chunks(filepath: str) -> list[dict]:
    """Split a Markdown file into chunks by ### headings."""
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    chunks = []
    # Split by ### headings
    pattern = r"^### (.+)$"
    parts = re.split(pattern, text, flags=re.MULTILINE)

    # parts[0] is text before first ###, then alternating heading/content
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            chunks.append({"heading": heading, "content": content})

    if not chunks:
        logger.warning(f"No ### headings found in {filepath}")

    return chunks


async def seed_file(
    conn: asyncpg.Connection,
    filepath: str,
    source_name: str,
    file_hash: str,
):
    """Parse, embed, and insert chunks from a single file."""
    chunks = parse_md_chunks(filepath)
    if not chunks:
        return 0

    logger.info(f"Processing {source_name}: {len(chunks)} chunks")

    # Delete old chunks for this file
    await conn.execute(
        "DELETE FROM knowledge_chunks WHERE source_file = $1",
        source_name,
    )

    inserted = 0
    for chunk in chunks:
        embed_text = f"{chunk['heading']}\n\n{chunk['content']}"
        try:
            embedding = await get_embedding(embed_text)
        except Exception:
            logger.exception(f"Failed to get embedding for chunk: {chunk['heading']}")
            embedding = None

        await conn.execute(
            """
            INSERT INTO knowledge_chunks (source_file, heading, content, embedding, file_hash)
            VALUES ($1, $2, $3, $4, $5)
            """,
            source_name,
            chunk["heading"],
            chunk["content"],
            embedding,
            file_hash,
        )
        inserted += 1
        logger.debug(f"  Inserted: {chunk['heading']}")

    return inserted


async def get_stored_hashes(conn: asyncpg.Connection) -> dict[str, str]:
    """Get file hashes currently stored in the database."""
    rows = await conn.fetch(
        "SELECT DISTINCT source_file, file_hash FROM knowledge_chunks"
    )
    return {row["source_file"]: row["file_hash"] for row in rows}


async def main():
    parser = argparse.ArgumentParser(description="Seed knowledge base from MD files")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only process changed files",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Process a single file",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate knowledge_chunks before seeding",
    )
    args = parser.parse_args()

    dsn = os.getenv(
        "DATABASE_URL",
        "postgresql://adk:adk@localhost:5432/adk_kb",
    )

    conn = await asyncpg.connect(dsn)
    await register_vector(conn)

    try:
        if args.reset:
            await conn.execute("TRUNCATE TABLE knowledge_chunks RESTART IDENTITY")
            logger.info("Reset knowledge_chunks table before seeding")

        if args.file:
            # Single file mode
            filepath = args.file
            if not os.path.isfile(filepath):
                logger.error(f"File not found: {filepath}")
                sys.exit(1)
            source_name = os.path.basename(filepath)
            file_hash = compute_file_hash(filepath)
            count = await seed_file(conn, filepath, source_name, file_hash)
            logger.info(f"Inserted {count} chunks from {source_name}")
        else:
            # Directory mode
            if not os.path.isdir(KB_DIR):
                logger.error(f"Knowledge base directory not found: {KB_DIR}")
                sys.exit(1)

            md_files = sorted(f for f in os.listdir(KB_DIR) if f.endswith(".md"))

            if not md_files:
                logger.warning(f"No .md files found in {KB_DIR}")
                sys.exit(0)

            stored_hashes = await get_stored_hashes(conn) if args.incremental else {}
            total = 0

            for filename in md_files:
                filepath = os.path.join(KB_DIR, filename)
                file_hash = compute_file_hash(filepath)

                if args.incremental and stored_hashes.get(filename) == file_hash:
                    logger.info(f"Skipping unchanged: {filename}")
                    continue

                count = await seed_file(conn, filepath, filename, file_hash)
                total += count

            logger.info(
                f"Seeding complete: {total} chunks from {len(md_files)} files "
                f"(model: {EMBEDDING_MODEL})"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
