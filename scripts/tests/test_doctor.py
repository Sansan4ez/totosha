import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doctor import SecurityDoctor


class SecurityDoctorRfc026Tests(unittest.TestCase):
    def test_expected_rfc026_counts_ignore_orphan_parent_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "db").mkdir()
            (root / "db" / "categories.json").write_text(
                json.dumps(
                    {
                        "categories": [
                            {"id": 1, "name": "Root", "parent": None},
                            {"id": 2, "name": "Child", "parent": {"id": 1, "name": "Root"}},
                            {"id": 3, "name": "Orphan", "parent": {"id": 999, "name": "Missing"}},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "db" / "spheres.json").write_text(
                json.dumps({"spheres": []}, ensure_ascii=False),
                encoding="utf-8",
            )

            doctor = SecurityDoctor(root)
            self.assertEqual(doctor._expected_rfc026_counts(), {"parent_links": 1, "curated_rows": 0})

    def test_check_corp_db_rfc026_schema_reports_missing_objects(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "db").mkdir()
            (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
            (root / "db" / "categories.json").write_text(
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
            (root / "db" / "spheres.json").write_text(
                json.dumps(
                    {
                        "spheres": [
                            {
                                "id": 7,
                                "name": "РЖД",
                                "curatedCategoryIds": [{"id": 2, "position": 1}],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            doctor = SecurityDoctor(root)
            payload = {
                "sphere_curated_categories_table": False,
                "categories_parent_category_id_column": True,
                "categories_parent_fk": True,
                "idx_categories_parent_category_id": True,
                "idx_sphere_curated_categories_category_id": True,
                "idx_sphere_curated_categories_sphere_position": True,
                "curated_rows": 1,
                "parent_links": 1,
            }

            ps_result = type("Result", (), {"returncode": 0, "stdout": "corp-db-id\n", "stderr": ""})()
            exec_result = type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

            with patch("doctor.shutil.which", return_value="/usr/bin/docker"), patch.object(
                doctor,
                "_run_docker_compose",
                side_effect=[ps_result, exec_result],
            ):
                doctor.check_corp_db_rfc026_schema()

        results = {result.name: result for result in doctor.results}
        self.assertIn("corp_db_rfc026_schema_objects", results)
        self.assertFalse(results["corp_db_rfc026_schema_objects"].passed)
        self.assertIn("corp.sphere_curated_categories", results["corp_db_rfc026_schema_objects"].message)
        self.assertTrue(results["corp_db_rfc026_curated_seed"].passed)
        self.assertTrue(results["corp_db_rfc026_parent_links"].passed)


if __name__ == "__main__":
    unittest.main()
