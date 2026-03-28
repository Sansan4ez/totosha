import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_loader import build_portfolio_records
from common import stable_portfolio_id


class CommonTests(unittest.TestCase):
    def test_stable_portfolio_id_is_hashed_and_deterministic(self):
        first = stable_portfolio_id(
            "Проект",
            "https://ladzavod.ru/portfolio/project",
            "Портфолио",
            3,
        )
        second = stable_portfolio_id(
            "Проект",
            "https://ladzavod.ru/portfolio/project",
            "Портфолио",
            3,
        )
        variant = stable_portfolio_id(
            "Другой проект",
            "https://ladzavod.ru/portfolio/project",
            "Портфолио",
            3,
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, variant)
        self.assertTrue(first.startswith("portfolio:"))
        self.assertNotIn("https://", first)

    def test_build_portfolio_records_deduplicates_identical_rows(self):
        row = {
            "name": "Проект",
            "url": "https://ladzavod.ru/portfolio/project",
            "image": "https://ladzavod.ru/static/project.jpg",
            "groupName": "Портфолио",
            "sphereId": 2,
        }
        records = build_portfolio_records([row, row], "hash")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][1], "Проект")


if __name__ == "__main__":
    unittest.main()
