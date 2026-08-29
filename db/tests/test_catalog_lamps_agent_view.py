import json
import unittest
from pathlib import Path


DB_DIR = Path(__file__).resolve().parents[1]


def _category_series_name(
    category_id: int,
    categories_by_id: dict[int, dict],
    family_to_series: dict[str, str],
) -> str | None:
    category = categories_by_id.get(category_id)
    seen: set[int] = set()
    while category is not None and category["id"] not in seen:
        seen.add(category["id"])
        series_name = family_to_series.get(str(category["name"]))
        if series_name is not None:
            return series_name
        parent = category.get("parent")
        category = categories_by_id.get(parent.get("id")) if isinstance(parent, dict) else None
    return None


class CatalogLampsAgentViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.categories = json.loads((DB_DIR / "categories.json").read_text(encoding="utf-8"))["categories"]
        cls.categories_by_id = {row["id"]: row for row in cls.categories}
        cls.products = json.loads((DB_DIR / "catalog.json").read_text(encoding="utf-8"))["products"]
        cls.series_catalog = json.loads(
            (DB_DIR / "series_catalog.json").read_text(encoding="utf-8")
        )["series"]
        cls.canonical_series = [row["name"] for row in cls.series_catalog]
        cls.family_to_series = {
            family_name: row["name"]
            for row in cls.series_catalog
            for family_name in [row["name"], *row.get("category_families", [])]
        }
        cls.view_sql = (DB_DIR / "sql" / "catalog_lamps_agent.sql").read_text(encoding="utf-8")
        cls.fresh_seed_sql = (DB_DIR / "sql" / "catalog_series_families_seed.sql").read_text(
            encoding="utf-8"
        )

    def _series_for_product(self, product: dict) -> str | None:
        return _category_series_name(
            product["categoryId"],
            self.categories_by_id,
            self.family_to_series,
        )

    def test_view_derives_canonical_series_from_nearest_mapped_ancestor(self):
        self.assertIn("WITH RECURSIVE category_ancestry", self.view_sql)
        self.assertIn("JOIN corp.catalog_series_families family", self.view_sql)
        self.assertIn("family.canonical_series_name AS series_name", self.view_sql)
        self.assertIn("ORDER BY ca.descendant_category_id, ca.depth ASC", self.view_sql)
        self.assertIn("LEFT JOIN category_series ON category_series.category_id = l.category_id", self.view_sql)
        self.assertRegex(self.view_sql, r"\) AS search_aliases,\s+b\.series_name\s+FROM base b;")
        for row in self.series_catalog:
            self.assertNotIn(f"'{row['name']}'", self.view_sql)
            for family_name in row.get("category_families", []):
                self.assertNotIn(f"'{family_name}'", self.view_sql)

    def test_fresh_init_seed_reads_json_without_hardcoded_taxonomy(self):
        self.assertIn("pg_read_file('/docker-entrypoint-initdb.d/series_catalog.json')", self.fresh_seed_sql)
        self.assertIn("TRUNCATE TABLE corp.catalog_series_families", self.fresh_seed_sql)
        self.assertIn("jsonb_array_elements(series_payload->'series')", self.fresh_seed_sql)
        for row in self.series_catalog:
            self.assertNotIn(f"'{row['name']}'", self.fresh_seed_sql)
            for family_name in row.get("category_families", []):
                self.assertNotIn(f"'{family_name}'", self.fresh_seed_sql)

    def test_current_catalog_has_full_canonical_series_coverage(self):
        resolved = [self._series_for_product(product) for product in self.products]

        self.assertEqual(len(self.products), 709)
        self.assertNotIn(None, resolved)
        self.assertEqual(set(resolved), set(self.canonical_series))
        self.assertFalse(set(resolved) - set(self.canonical_series))

    def test_r500_and_line_declared_families_resolve_to_canonical_series(self):
        expected_by_category = {
            "LAD LED R500 12/24/36V": "LAD LED R500",
            "LAD LED R500 РЖД": "LAD LED R500",
            "LAD LED R500 периметральное": "LAD LED R500",
            "LAD LED R500 A": "LAD LED R500",
            "LAD LED LINE-OZ": "LAD LED LINE",
        }
        for category_name, expected_series in expected_by_category.items():
            category = next(row for row in self.categories if row["name"] == category_name)
            self.assertEqual(
                _category_series_name(category["id"], self.categories_by_id, self.family_to_series),
                expected_series,
            )

    def test_intermediate_family_under_nonseries_root_wins(self):
        category = next(row for row in self.categories if row["name"] == "LAD LED R500 A")
        self.assertEqual(category["parent"]["name"], "АЗС")
        self.assertEqual(
            _category_series_name(category["id"], self.categories_by_id, self.family_to_series),
            "LAD LED R500",
        )

    def test_root_family_and_ex_2ex_counterexample_remain_distinct(self):
        root_category = next(row for row in self.categories if row["name"] == "NL Nova")
        self.assertEqual(
            _category_series_name(root_category["id"], self.categories_by_id, self.family_to_series),
            "NL Nova",
        )

        r320 = next(row for row in self.products if row["name"] == "LAD LED R320-2-10G-230AC-50K Ex")
        r500 = next(row for row in self.products if row["name"] == "LAD LED R500-2-O-6-110L 2Ex")
        self.assertEqual(self._series_for_product(r320), "LAD LED R320 Ex")
        self.assertEqual(self._series_for_product(r500), "LAD LED R500 2Ex")
        self.assertNotEqual(self._series_for_product(r320), self._series_for_product(r500))


if __name__ == "__main__":
    unittest.main()
