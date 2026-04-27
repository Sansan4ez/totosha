import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_loader import (
    build_category_parent_records,
    build_sphere_curated_category_records,
    seed_json_sources,
)


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


class CatalogLoaderTests(unittest.TestCase):
    def test_build_category_parent_records_preserves_parent_ids(self):
        rows = [
            {"id": 37, "name": "LAD LED R500", "parent": None},
            {
                "id": 63,
                "name": "LAD LED R500 ZD",
                "parent": {"id": 62, "name": "LAD LED R500 РЖД"},
            },
            {
                "id": 147,
                "name": "LAD LED R320 Ex (36V)",
                "parent": {"id": 18, "name": "LAD LED R320 Ex"},
            },
        ]
        self.assertEqual(build_category_parent_records(rows), [(63, 62), (147, 18)])

    def test_build_sphere_curated_category_records_match_rfc_026_shape(self):
        sphere_rows = json.loads(Path("db/spheres.json").read_text(encoding="utf-8"))["spheres"]
        records = build_sphere_curated_category_records(sphere_rows, "sphere-hash")

        self.assertEqual(len(records), 33)
        self.assertEqual(len({category_id for _, category_id, _, _ in records}), 25)
        self.assertEqual(
            [record[:3] for record in records if record[0] == 3],
            [(3, 37, 1), (3, 34, 2), (3, 39, 3), (3, 33, 4), (3, 13, 5)],
        )
        self.assertEqual(
            [record[:3] for record in records if record[0] == 5],
            [(5, 63, 1), (5, 64, 2)],
        )

    def test_seed_json_sources_backfills_parent_links_and_curated_relations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "categories.json").write_text(
                json.dumps(
                    {
                        "categories": [
                            {
                                "id": 1,
                                "name": "Root",
                                "url": "https://example.test/root",
                                "image": None,
                                "parent": None,
                            },
                            {
                                "id": 2,
                                "name": "Child",
                                "url": "https://example.test/child",
                                "image": None,
                                "parent": {"id": 1, "name": "Root"},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (base / "etm_oracl_catalog_sku.json").write_text("[]", encoding="utf-8")
            (base / "lamp_mountings.json").write_text('{"lampMountings":[]}', encoding="utf-8")
            (base / "mounting_types.json").write_text('{"mountingTypes":[]}', encoding="utf-8")
            (base / "portfolio.json").write_text('{"portfolio":[]}', encoding="utf-8")
            (base / "spheres.json").write_text(
                json.dumps(
                    {
                        "spheres": [
                            {
                                "id": 1,
                                "name": "Складские помещения",
                                "url": "https://example.test/sphere",
                                "categoriesId": [{"id": 2}],
                                "curatedCategoryIds": [{"id": 1, "position": 1}],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (base / "catalog.json").write_text("{}", encoding="utf-8")

            conn = FakeConn()
            with patch(
                "catalog_loader.transform_catalog",
                return_value={"lamps": [], "documents": [], "raw_properties": []},
            ):
                stats = asyncio.run(seed_json_sources(conn, base))

        self.assertIn("corp.sphere_curated_categories", conn.execute_calls[0][0])
        self.assertEqual(stats["category_parent_links"], 1)
        self.assertEqual(stats["sphere_categories"], 1)
        self.assertEqual(stats["sphere_curated_categories"], 1)

        update_calls = [
            args for sql, args in conn.executemany_calls if "UPDATE corp.categories" in sql
        ]
        curated_calls = [
            args for sql, args in conn.executemany_calls if "INSERT INTO corp.sphere_curated_categories" in sql
        ]

        self.assertEqual(update_calls, [[(2, 1)]])
        self.assertEqual(len(curated_calls), 1)
        self.assertEqual(curated_calls[0][0][:3], (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
