import json
import unittest
from pathlib import Path


DB_DIR = Path(__file__).resolve().parents[1]


def _category_root_name(category_id: int, categories_by_id: dict[int, dict]) -> str | None:
    category = categories_by_id.get(category_id)
    seen: set[int] = set()
    root_name: str | None = None
    while category is not None and category["id"] not in seen:
        seen.add(category["id"])
        root_name = str(category["name"])
        parent = category.get("parent")
        category = categories_by_id.get(parent.get("id")) if isinstance(parent, dict) else None
    return root_name


class CatalogLampsAgentViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.categories = json.loads((DB_DIR / "categories.json").read_text(encoding="utf-8"))["categories"]
        cls.categories_by_id = {row["id"]: row for row in cls.categories}
        cls.products = json.loads((DB_DIR / "catalog.json").read_text(encoding="utf-8"))["products"]
        cls.canonical_series = [
            row["name"]
            for row in json.loads((DB_DIR / "series_catalog.json").read_text(encoding="utf-8"))["series"]
        ]
        cls.view_sql = (DB_DIR / "sql" / "catalog_lamps_agent.sql").read_text(encoding="utf-8")

    def test_view_derives_series_name_from_recursive_category_ancestry(self):
        self.assertIn("WITH RECURSIVE category_ancestry", self.view_sql)
        self.assertIn("ca.ancestor_name AS series_name", self.view_sql)
        self.assertIn("LEFT JOIN category_series ON category_series.category_id = l.category_id", self.view_sql)
        self.assertRegex(self.view_sql, r"\) AS search_aliases,\s+b\.series_name\s+FROM base b;")
        self.assertNotIn("R320-2", self.view_sql)
        self.assertNotIn("R500-", self.view_sql)

    def test_every_canonical_series_has_a_category_root(self):
        root_names = {
            row["name"]
            for row in self.categories
            if not isinstance(row.get("parent"), dict)
        }
        self.assertTrue(set(self.canonical_series).issubset(root_names))

    def test_incident_skus_resolve_to_distinct_canonical_roots(self):
        r320 = next(row for row in self.products if row["name"] == "LAD LED R320-2-10G-230AC-50K Ex")
        r500 = next(row for row in self.products if row["name"] == "LAD LED R500-2-O-6-110L 2Ex")

        self.assertEqual(_category_root_name(r320["categoryId"], self.categories_by_id), "LAD LED R320 Ex")
        self.assertEqual(_category_root_name(r500["categoryId"], self.categories_by_id), "LAD LED R500 2Ex")
        self.assertNotEqual(_category_root_name(r320["categoryId"], self.categories_by_id), "LAD LED R500 2Ex")


if __name__ == "__main__":
    unittest.main()
