import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_migration import ensure_rfc026_schema


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self):
        self.execute_calls = []
        self.executemany_calls = []

    async def execute(self, query, *args):
        self.execute_calls.append((str(query), list(args)))
        return "OK"

    async def executemany(self, query, args):
        self.executemany_calls.append((str(query), list(args)))
        return None

    def transaction(self):
        return _Tx()


class LiveMigrationTests(unittest.TestCase):
    def test_ensure_rfc026_schema_backfills_parent_links_and_curated_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "categories.json").write_text(
                json.dumps(
                    {
                        "categories": [
                            {"id": 1, "name": "Root", "parent": None},
                            {"id": 2, "name": "Child", "parent": {"id": 1, "name": "Root"}},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (base / "spheres.json").write_text(
                json.dumps(
                    {
                        "spheres": [
                            {
                                "id": 7,
                                "name": "РЖД",
                                "url": "https://example.test/rzd",
                                "curatedCategoryIds": [
                                    {"id": 2, "position": 1},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            conn = FakeConn()
            stats = asyncio.run(ensure_rfc026_schema(conn, base))

        self.assertEqual(stats["parent_links"], 1)
        self.assertEqual(stats["spheres"], 1)
        self.assertEqual(stats["sphere_curated_categories"], 1)

        executed_sql = "\n".join(sql for sql, _ in conn.execute_calls)
        self.assertIn("ADD COLUMN IF NOT EXISTS parent_category_id", executed_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS corp.sphere_curated_categories", executed_sql)
        self.assertIn("DELETE FROM corp.sphere_curated_categories", executed_sql)

        sphere_upserts = [
            args for sql, args in conn.executemany_calls if "INSERT INTO corp.spheres" in sql
        ]
        parent_updates = [
            args for sql, args in conn.executemany_calls if "UPDATE corp.categories" in sql
        ]
        curated_inserts = [
            args for sql, args in conn.executemany_calls if "INSERT INTO corp.sphere_curated_categories" in sql
        ]

        self.assertEqual(len(sphere_upserts), 1)
        self.assertEqual(sphere_upserts[0][0][:3], (7, "РЖД", "https://example.test/rzd"))
        self.assertEqual(parent_updates, [[(1, None), (2, 1)]])
        self.assertEqual(curated_inserts, [[(7, 2, 1, curated_inserts[0][0][3])]])
        self.assertEqual(conn.execute_calls[-1][1], [[7]])

    def test_ensure_rfc026_schema_clears_removed_parent_links_and_empty_curated_sets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "categories.json").write_text(
                json.dumps(
                    {
                        "categories": [
                            {"id": 1, "name": "Root", "parent": None},
                            {"id": 2, "name": "Child", "parent": None},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (base / "spheres.json").write_text(
                json.dumps(
                    {
                        "spheres": [
                            {
                                "id": 7,
                                "name": "РЖД",
                                "url": "https://example.test/rzd",
                                "curatedCategoryIds": [
                                    {"id": 2, "position": 1},
                                ],
                            },
                            {
                                "id": 8,
                                "name": "Метро",
                                "url": "https://example.test/metro",
                                "curatedCategoryIds": [],
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            conn = FakeConn()
            stats = asyncio.run(ensure_rfc026_schema(conn, base))

        self.assertEqual(stats["parent_links"], 0)
        self.assertEqual(stats["spheres"], 2)
        self.assertEqual(stats["sphere_curated_categories"], 1)

        parent_updates = [
            args for sql, args in conn.executemany_calls if "UPDATE corp.categories" in sql
        ]
        curated_inserts = [
            args for sql, args in conn.executemany_calls if "INSERT INTO corp.sphere_curated_categories" in sql
        ]

        self.assertEqual(parent_updates, [[(1, None), (2, None)]])
        self.assertEqual(curated_inserts, [[(7, 2, 1, curated_inserts[0][0][3])]])
        self.assertEqual(conn.execute_calls[-1][1], [[7, 8]])


if __name__ == "__main__":
    unittest.main()
