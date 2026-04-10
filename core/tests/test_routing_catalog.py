import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from documents.routing import (
    ROUTING_CATALOG_FILENAME,
    build_routing_index,
    load_routing_index,
    select_route,
)


class RoutingCatalogTests(unittest.TestCase):
    def _write_repo_manifest(self, repo_root: Path, payload: dict) -> None:
        route_dir = repo_root / "doc-corpus" / "manifests" / "routes"
        route_dir.mkdir(parents=True, exist_ok=True)
        (route_dir / "test-catalog.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _write_live_document(
        self,
        docs_root: Path,
        *,
        document_id: str,
        title: str,
        summary: str,
        routing: dict | None = None,
    ) -> None:
        live_dir = docs_root / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "document_id": document_id,
            "sha256": "abc123",
            "relative_path": f"{document_id}.pdf",
            "original_filename": f"{document_id}.pdf",
            "aliases": [
                {
                    "relative_path": f"{document_id}.pdf",
                    "metadata": {
                        "title": title,
                        "summary": summary,
                        "tags": ["сертификат", "line"],
                    },
                }
            ],
        }
        if routing:
            payload["routing"] = routing
        (live_dir / f"{document_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_load_routing_index_uses_repo_published_catalog(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            repo_root = Path(repo_tmp)
            self._write_repo_manifest(
                repo_root,
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "repo-v1",
                    "routes": [
                        {
                            "route_id": "corp_db.custom_lookup",
                            "route_family": "corp_db.custom_lookup",
                            "route_kind": "corp_table",
                            "authority": "primary",
                            "title": "Custom lookup",
                            "keywords": ["custom"],
                            "patterns": ["custom lookup"],
                            "executor": "corp_db_search",
                            "executor_args_template": {"kind": "lamp_exact"},
                        }
                    ],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(repo_root), "CORP_DOCS_ROOT": str(Path(docs_tmp))},
                clear=False,
            ):
                payload = load_routing_index()
            self.assertEqual(payload["manifest_origin"], "published")
            self.assertEqual(payload["catalog_version"], "repo-v1")
            self.assertEqual(payload["routes"][0]["route_id"], "corp_db.custom_lookup")

    def test_build_routing_index_merges_repo_manifest_and_live_doc_routes(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            repo_root = Path(repo_tmp)
            docs_root = Path(docs_tmp)
            self._write_repo_manifest(
                repo_root,
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "repo-v1",
                    "routes": [
                        {
                            "route_id": "corp_kb.company_common",
                            "route_family": "corp_kb.company_common",
                            "route_kind": "corp_table",
                            "authority": "primary",
                            "title": "Company common knowledge base",
                            "keywords": ["контакты"],
                            "patterns": ["контакты компании"],
                            "executor": "corp_db_search",
                            "executor_args_template": {
                                "kind": "hybrid_search",
                                "profile": "kb_route_lookup",
                                "knowledge_route_id": "corp_kb.company_common",
                                "source_files": ["common_information_about_company.md"],
                            },
                        }
                    ],
                },
            )
            self._write_live_document(
                docs_root,
                document_id="doc_fire_line",
                title="Пожарный сертификат LINE",
                summary="Пожарный сертификат LINE с прямой ссылкой.",
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(repo_root), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                payload = build_routing_index()
            route_ids = {route["route_id"] for route in payload["routes"]}
            self.assertIn("corp_kb.company_common", route_ids)
            self.assertIn("doc_search.doc_fire_line", route_ids)
            runtime_catalog = docs_root / "manifests" / "routes" / ROUTING_CATALOG_FILENAME
            self.assertTrue(runtime_catalog.exists())

    def test_document_routing_metadata_can_override_route_identity_and_win_selection(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            docs_root = Path(docs_tmp)
            self._write_live_document(
                docs_root,
                document_id="doc_sports_norms",
                title="СП 440.1325800.2023 Освещение спортивных сооружений",
                summary="Нормы освещенности спортивных объектов, спортивных залов и спортивных сооружений.",
                routing={
                    "route_id": "doc_search.sports_lighting_norms",
                    "route_family": "doc_search.sports_lighting_norms",
                    "topics": ["sports_lighting", "sports_halls"],
                    "keywords": [
                        "нормы освещенности спортивных объектов",
                        "нормы освещенности спортивного зала",
                        "требования к освещению спортивных сооружений",
                    ],
                    "patterns": [
                        "какие нормы освещенности для спортивных объектов",
                        "найди в документе нормы освещенности для спортивного зала",
                    ],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                payload = build_routing_index()
                selection = select_route("Какие нормы освещенности для спортивных объектов?")

            route = next(route for route in payload["routes"] if route["route_id"] == "doc_search.sports_lighting_norms")
            self.assertEqual(route["route_family"], "doc_search.sports_lighting_norms")
            self.assertEqual(route["topics"], ["sports_lighting", "sports_halls"])
            self.assertEqual(selection["selected"]["route_id"], "doc_search.sports_lighting_norms")
            self.assertEqual(selection["selected_route_kind"], "doc_domain")

    def test_load_routing_index_falls_back_to_bootstrap(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = load_routing_index()
            self.assertEqual(payload["manifest_origin"], "bootstrap")
            route_kinds = {route["route_kind"] for route in payload["routes"]}
            self.assertIn("corp_table", route_kinds)
            self.assertIn("corp_script", route_kinds)
            self.assertIn("doc_domain", route_kinds)

    def test_select_route_returns_candidates_reason_and_kind(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                selection = select_route(
                    "Нужен пожарный сертификат LINE, дай прямую ссылку.",
                    explicit_document_request=True,
                )
            self.assertEqual(selection["selected"]["route_id"], "doc_search.document_lookup")
            self.assertEqual(selection["selected_route_kind"], "doc_domain")
            self.assertIn("explicit_document_request", selection["selection_reason"])
            self.assertTrue(selection["candidate_route_ids"])

    def test_select_route_keeps_generic_link_requests_on_authoritative_kb_routes(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                company_selection = select_route("Ссылка на контакты компании")
                luxnet_selection = select_route("Нужна ссылка на страницу Luxnet")

            self.assertEqual(company_selection["selected"]["route_id"], "corp_kb.company_common")
            self.assertNotIn("explicit_document_request", company_selection["selection_reason"])
            self.assertEqual(luxnet_selection["selected"]["route_id"], "corp_kb.luxnet")
            self.assertNotIn("explicit_document_request", luxnet_selection["selection_reason"])

    def test_select_route_matches_application_recommendation_for_inflected_environment_phrase(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                selection = select_route("Какие светильники подходят для агрессивной среды?")

            self.assertEqual(selection["selected"]["route_id"], "corp_db.application_recommendation")
            self.assertEqual(selection["selected_route_kind"], "corp_script")
            self.assertIn("corp_db.application_recommendation", selection["candidate_route_ids"])


if __name__ == "__main__":
    unittest.main()
