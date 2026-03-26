from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from common import compact_preview, json_hash, normalize_ws, sha256_file


H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)
H3_SPLIT_RE = re.compile(r"^### (.+)$", re.MULTILINE)


class ManifestValidationError(ValueError):
    pass


def load_manifest(manifest_path: Path) -> list[str]:
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("files", [])
    else:
        raise ManifestValidationError(f"Unsupported manifest format: {type(payload).__name__}")

    results: list[str] = []
    for item in items:
        path = item.get("path") if isinstance(item, dict) else item
        value = normalize_ws(path)
        if not value:
            raise ManifestValidationError("Manifest contains an empty file entry")
        if not value.endswith(".md"):
            raise ManifestValidationError(f"Manifest entry must point to a .md file: {value}")
        results.append(value)

    if not results:
        raise ManifestValidationError("Manifest does not contain any promoted markdown files")
    if len(set(results)) != len(results):
        raise ManifestValidationError("Manifest contains duplicate markdown paths")
    return results


def parse_markdown_document(source_path: Path, source_file: str) -> tuple[str, list[dict[str, object]]]:
    text = source_path.read_text(encoding="utf-8")
    h1_matches = H1_RE.findall(text)
    if len(h1_matches) != 1:
        raise ManifestValidationError(f"{source_file}: expected exactly one H1 heading")

    document_title = normalize_ws(h1_matches[0])
    parts = H3_SPLIT_RE.split(text)
    chunks: list[dict[str, object]] = []
    for index in range(1, len(parts), 2):
        heading = normalize_ws(parts[index])
        content = normalize_ws(parts[index + 1] if index + 1 < len(parts) else "")
        if not content:
            continue
        chunks.append(
            {
                "chunk_index": len(chunks),
                "heading": heading,
                "content": content,
                "preview": compact_preview(content),
            }
        )

    if not chunks:
        raise ManifestValidationError(f"{source_file}: no non-empty ### chunks found")
    return document_title, chunks


async def _existing_hashes(conn) -> dict[str, str]:
    rows = await conn.fetch(
        """
        SELECT source_file, max(source_hash) AS source_hash
        FROM corp.knowledge_chunks
        GROUP BY source_file
        """
    )
    return {row["source_file"]: row["source_hash"] for row in rows}


async def seed_knowledge_chunks(
    conn,
    wiki_dir: Path,
    manifest_path: Path,
    *,
    incremental: bool = False,
    reset: bool = False,
    embeddings_enabled: bool = True,
) -> dict[str, int]:
    manifest_files = load_manifest(manifest_path)
    existing_hashes = await _existing_hashes(conn) if incremental and not reset else {}

    async with conn.transaction():
        if reset:
            await conn.execute("TRUNCATE TABLE corp.knowledge_chunks")
        else:
            await conn.execute(
                "DELETE FROM corp.knowledge_chunks WHERE NOT (source_file = ANY($1::text[]))",
                manifest_files,
            )

        processed_files = 0
        skipped_files = 0
        inserted_chunks = 0

        for source_file in manifest_files:
            source_path = wiki_dir / source_file
            if not source_path.exists():
                raise ManifestValidationError(f"Promoted wiki file not found: {source_file}")

            source_hash = sha256_file(source_path)
            if incremental and existing_hashes.get(source_file) == source_hash:
                skipped_files += 1
                continue

            document_title, chunks = parse_markdown_document(source_path, source_file)
            await conn.execute("DELETE FROM corp.knowledge_chunks WHERE source_file = $1", source_file)

            embedding_inputs = [
                f"{document_title}\n\n{chunk['heading']}\n\n{chunk['content']}"
                for chunk in chunks
            ]
            if embeddings_enabled:
                from embeddings import get_embeddings
            embeddings = await get_embeddings(embedding_inputs) if embeddings_enabled else [None] * len(chunks)

            await conn.executemany(
                """
                INSERT INTO corp.knowledge_chunks (
                    source_file, document_title, chunk_index, heading, content,
                    preview, metadata, source_hash, embedding
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                [
                    (
                        source_file,
                        document_title,
                        int(chunk["chunk_index"]),
                        chunk["heading"],
                        chunk["content"],
                        chunk["preview"],
                        json.dumps(
                            {
                                "source_file": source_file,
                                "document_title": document_title,
                                "source_hash": source_hash,
                            },
                            ensure_ascii=False,
                        ),
                        source_hash,
                        embedding,
                    )
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ],
            )
            inserted_chunks += len(chunks)
            processed_files += 1

    return {
        "processed_files": processed_files,
        "skipped_files": skipped_files,
        "inserted_chunks": inserted_chunks,
        "manifest_files": len(manifest_files),
    }
