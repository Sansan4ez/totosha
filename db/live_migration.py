from __future__ import annotations

from pathlib import Path

from catalog_loader import (
    build_category_parent_records,
    build_sphere_curated_category_records,
)
from common import load_json_file, sha256_file


RFC026_SCHEMA_STATEMENTS = (
    """
    CREATE SCHEMA IF NOT EXISTS corp
    """,
    """
    ALTER TABLE IF EXISTS corp.categories
        ADD COLUMN IF NOT EXISTS parent_category_id bigint
    """,
    """
    DO $$
    BEGIN
        IF to_regclass('corp.categories') IS NULL THEN
            RAISE EXCEPTION 'corp.categories is required before applying RFC-026 migration';
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'categories_parent_category_id_fkey'
              AND conrelid = 'corp.categories'::regclass
        ) THEN
            ALTER TABLE corp.categories
                ADD CONSTRAINT categories_parent_category_id_fkey
                FOREIGN KEY (parent_category_id)
                REFERENCES corp.categories(category_id)
                ON DELETE SET NULL;
        END IF;
    END;
    $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS corp.sphere_curated_categories (
        sphere_id bigint NOT NULL REFERENCES corp.spheres(sphere_id) ON DELETE CASCADE,
        category_id bigint NOT NULL REFERENCES corp.categories(category_id) ON DELETE CASCADE,
        position integer NOT NULL,
        source_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (sphere_id, category_id),
        UNIQUE (sphere_id, position),
        CHECK (position > 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_categories_parent_category_id
        ON corp.categories (parent_category_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sphere_curated_categories_category_id
        ON corp.sphere_curated_categories (category_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sphere_curated_categories_sphere_position
        ON corp.sphere_curated_categories (sphere_id, position)
    """,
)


def build_sphere_records(sphere_rows: list[dict], source_hash: str) -> list[tuple]:
    return [
        (
            row["id"],
            row["name"],
            row.get("url"),
            source_hash,
        )
        for row in sphere_rows
    ]


def build_category_parent_assignments(category_rows: list[dict]) -> list[tuple]:
    valid_category_ids = {
        row.get("id")
        for row in category_rows
        if isinstance(row, dict) and row.get("id") is not None
    }
    assignments: list[tuple] = []
    for row in category_rows:
        if not isinstance(row, dict):
            continue
        parent = row.get("parent")
        parent_id = parent.get("id") if isinstance(parent, dict) else None
        if parent_id not in valid_category_ids:
            parent_id = None
        assignments.append((row["id"], parent_id))
    return assignments


async def ensure_rfc026_schema(conn, sources_dir: Path) -> dict[str, int]:
    categories_path = sources_dir / "categories.json"
    spheres_path = sources_dir / "spheres.json"

    category_rows = load_json_file(categories_path)["categories"]
    sphere_rows = load_json_file(spheres_path)["spheres"]

    sphere_hash = sha256_file(spheres_path)
    category_parent_records = build_category_parent_records(category_rows)
    category_parent_assignments = build_category_parent_assignments(category_rows)
    sphere_records = build_sphere_records(sphere_rows, sphere_hash)
    curated_records = build_sphere_curated_category_records(sphere_rows, sphere_hash)
    source_sphere_ids = sorted({row["id"] for row in sphere_rows})

    async with conn.transaction():
        for statement in RFC026_SCHEMA_STATEMENTS:
            await conn.execute(statement)

        if sphere_records:
            await conn.executemany(
                """
                INSERT INTO corp.spheres (sphere_id, name, url, source_hash)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (sphere_id) DO UPDATE
                SET
                    name = EXCLUDED.name,
                    url = EXCLUDED.url,
                    source_hash = EXCLUDED.source_hash,
                    updated_at = now()
                """,
                sphere_records,
            )

        if category_parent_assignments:
            # Converge category parents for every source category, including explicit NULL when
            # a category no longer has a parent in categories.json.
            await conn.executemany(
                """
                UPDATE corp.categories
                SET
                    parent_category_id = $2,
                    updated_at = now()
                WHERE category_id = $1
                  AND parent_category_id IS DISTINCT FROM $2
                """,
                category_parent_assignments,
            )

        if source_sphere_ids:
            # Reset curated edges for every source sphere before re-inserting the canonical set so
            # repeated runs remove stale links even when curatedCategoryIds becomes empty.
            await conn.execute(
                """
                DELETE FROM corp.sphere_curated_categories
                WHERE sphere_id = ANY($1::bigint[])
                """,
                source_sphere_ids,
            )

        if curated_records:
            await conn.executemany(
                """
                INSERT INTO corp.sphere_curated_categories (
                    sphere_id, category_id, position, source_hash
                )
                VALUES ($1, $2, $3, $4)
                """,
                curated_records,
            )

    return {
        "schema_statements": len(RFC026_SCHEMA_STATEMENTS),
        "parent_links": len(category_parent_records),
        "spheres": len(sphere_records),
        "sphere_curated_categories": len(curated_records),
    }
