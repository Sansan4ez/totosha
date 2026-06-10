import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common as common_module
from catalog_loader import build_portfolio_records
from common import get_admin_dsn, stable_portfolio_id


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

    def test_get_admin_dsn_percent_encodes_reserved_characters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(common_module, "DEFAULT_ADMIN_PASSWORD_SECRET", Path(tmpdir) / "missing-secret"):
                with mock.patch.dict(
                    os.environ,
                    {
                        "POSTGRES_PASSWORD": "pa:ss@word /with?reserved#chars",
                        "CORP_DB_ADMIN_USER": "ops/user:name",
                        "CORP_DB_ADMIN_HOST": "db.internal",
                        "CORP_DB_PORT": "5433",
                        "CORP_DB_NAME": "corp db/prod@primary",
                    },
                    clear=False,
                ):
                    dsn = get_admin_dsn()

        self.assertEqual(
            dsn,
            "postgresql://ops%2Fuser%3Aname:pa%3Ass%40word%20%2Fwith%3Freserved%23chars@db.internal:5433/corp%20db%2Fprod%40primary",
        )
        parts = urlsplit(dsn)
        self.assertEqual(unquote(parts.username or ""), "ops/user:name")
        self.assertEqual(unquote(parts.password or ""), "pa:ss@word /with?reserved#chars")
        self.assertEqual(unquote(parts.path.lstrip("/")), "corp db/prod@primary")
        self.assertEqual(parts.hostname, "db.internal")
        self.assertEqual(parts.port, 5433)

    def test_get_admin_dsn_keeps_happy_path_readable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(common_module, "DEFAULT_ADMIN_PASSWORD_SECRET", Path(tmpdir) / "missing-secret"):
                with mock.patch.dict(
                    os.environ,
                    {
                        "POSTGRES_PASSWORD": "simplepass",
                        "CORP_DB_ADMIN_USER": "postgres",
                        "CORP_DB_ADMIN_HOST": "corp-db",
                        "CORP_DB_PORT": "5432",
                        "CORP_DB_NAME": "corp_pg_db",
                    },
                    clear=False,
                ):
                    self.assertEqual(
                        get_admin_dsn(),
                        "postgresql://postgres:simplepass@corp-db:5432/corp_pg_db",
                    )


if __name__ == "__main__":
    unittest.main()
