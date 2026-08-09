import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doctor import (
    COMPOSE_FILES,
    PUBLIC_BY_DESIGN,
    SecurityDoctor,
    iter_published_ports,
    service_networks,
)


class SecurityDoctorComposeTests(unittest.TestCase):
    def test_repository_compose_ports_and_admin_networks_are_isolated(self):
        root = Path(__file__).resolve().parents[2]
        published_ports = []
        networks_by_service = {}

        for relative_path in COMPOSE_FILES:
            compose_path = root / relative_path
            self.assertTrue(compose_path.exists(), relative_path)
            published_ports.extend(iter_published_ports(compose_path))
            networks_by_service.update(service_networks(compose_path))

        for service, raw_spec in published_ports:
            target_port = int(raw_spec.rsplit(":", 1)[-1].split("/", 1)[0])
            self.assertTrue(
                raw_spec.startswith("127.0.0.1:") or (service, target_port) in PUBLIC_BY_DESIGN,
                f"{service} publishes {raw_spec} beyond loopback",
            )

        self.assertEqual(networks_by_service["admin"], ["admin-net"])
        self.assertNotIn("agent-net", networks_by_service["admin"])
        self.assertTrue({"agent-net", "admin-net"}.issubset(networks_by_service["core"]))
        self.assertEqual(
            sorted(
                service
                for service, networks in networks_by_service.items()
                if "admin-net" in networks
            ),
            ["admin", "core"],
        )

    def test_network_check_rejects_unbound_port_and_admin_on_agent_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "docker-compose.yml").write_text(
                """
services:
  admin:
    ports:
      - "127.0.0.1:3000:3000"
    networks:
      - admin-net
      - agent-net
  core:
    networks:
      - agent-net
      - admin-net
  victoriametrics:
    ports:
      - "8428:8428"
    networks:
      - agent-net
networks:
  agent-net:
    internal: false
  admin-net: {}
""".lstrip(),
                encoding="utf-8",
            )

            doctor = SecurityDoctor(root)
            doctor.check_network_exposure()

        results = {result.name: result for result in doctor.results}
        self.assertFalse(results["port_victoriametrics_8428"].passed)
        self.assertFalse(results["admin_networks"].passed)
        self.assertTrue(results["internal_network"].passed)




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
