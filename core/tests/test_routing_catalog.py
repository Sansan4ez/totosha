import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from documents.argument_catalogs import (
    canonical_mounting_type_names,
    canonical_sphere_names,
    curated_category_names_for_sphere,
)
from documents.routing import (
    ROUTING_CATALOG_FILENAME,
    RouteCatalogUnavailable,
    build_route_selector_payload,
    build_routing_index,
    load_routing_index,
    routing_catalog_health,
    select_route,
)
from documents.series_catalog import SERIES_KB_PATH, canonical_series_names, extract_kb_series_labels, load_canonical_series_catalog


class RoutingCatalogTests(unittest.TestCase):
    def test_canonical_series_catalog_matches_kb_and_expected_runtime_names(self):
        kb_labels = extract_kb_series_labels(SERIES_KB_PATH.read_text(encoding="utf-8"))
        catalog = load_canonical_series_catalog()

        self.assertEqual(
            canonical_series_names(),
            [
                "LAD LED R500",
                "LAD LED R700",
                "LAD LED R500 2Ex",
                "LAD LED R320 Ex",
                "LAD LED LINE",
                "NL Nova",
                "NL VEGA",
            ],
        )
        self.assertEqual(
            {entry["knowledge_base_label"] for entry in catalog["series"]},
            set(kb_labels),
        )

    def _write_repo_manifest(self, repo_root: Path, payload: dict) -> None:
        route_dir = repo_root / "doc-corpus" / "manifests" / "routes"
        route_dir.mkdir(parents=True, exist_ok=True)
        (route_dir / "test-catalog.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _write_repo_manifest_named(self, repo_root: Path, name: str, payload: dict) -> None:
        route_dir = repo_root / "doc-corpus" / "manifests" / "routes"
        route_dir.mkdir(parents=True, exist_ok=True)
        (route_dir / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

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
            self.assertIn("source_manifests", payload)
            self.assertIn("source_digests", payload)
            self.assertIn("route_count_by_kind", payload)
            self.assertGreaterEqual(payload["route_count_by_kind"]["doc_domain"], 1)
            self.assertTrue(payload["validation_report"]["valid"])
            self.assertIn("missing_corp_db_domains", payload["validation_report"])
            runtime_catalog = docs_root / "manifests" / "routes" / ROUTING_CATALOG_FILENAME
            self.assertTrue(runtime_catalog.exists())

    def test_load_routing_index_revalidates_persisted_runtime_catalog(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            docs_root = Path(docs_tmp)
            runtime_dir = docs_root / "manifests" / "routes"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_catalog = runtime_dir / ROUTING_CATALOG_FILENAME
            runtime_catalog.write_text(
                json.dumps(
                    {
                        "catalog_id": "test-routing",
                        "schema_version": 1,
                        "catalog_version": "stale-runtime-v1",
                        "source_owner": "runtime_merged",
                        "validation_report": {"valid": True, "errors": []},
                        "routes": [
                            {
                                "route_id": "corp_db.runtime_lookup",
                                "route_family": "corp_db.runtime_lookup",
                                "route_kind": "corp_table",
                                "authority": "primary",
                                "title": "Runtime lookup",
                                "executor": "corp_db_search",
                                "executor_args_template": {"kind": "lamp_exact"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                payload = load_routing_index()

            self.assertEqual(payload["manifest_origin"], "runtime_merged")
            self.assertGreaterEqual(payload["route_count"], 1)
            self.assertIn("corp_db.runtime_lookup", {route["route_id"] for route in payload["routes"]})
            self.assertIn("corp_db.portfolio_lookup", {route["route_id"] for route in payload["routes"]})
            self.assertTrue(payload["validation_report"]["valid"])
            self.assertIn("runtime_merged", {item["source_owner"] for item in payload["source_manifests"]})

    def test_load_routing_index_rejects_runtime_catalog_with_stale_valid_report(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            docs_root = Path(docs_tmp)
            runtime_dir = docs_root / "manifests" / "routes"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            runtime_catalog = runtime_dir / ROUTING_CATALOG_FILENAME
            runtime_catalog.write_text(
                json.dumps(
                    {
                        "catalog_id": "test-routing",
                        "schema_version": 1,
                        "catalog_version": "stale-runtime-v1",
                        "source_owner": "runtime_merged",
                        "validation_report": {"valid": True, "errors": []},
                        "route_count": 1,
                        "routes": [
                            {
                                "route_id": "corp_db.stale_lookup",
                                "route_family": "corp_db.stale_lookup",
                                "route_kind": "corp_table",
                                "authority": "primary",
                                "title": "Stale lookup",
                                "executor": "corp_db_search",
                                "executor_args_template": {"kind": 123},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                payload = load_routing_index()

            self.assertEqual(payload["manifest_origin"], "bootstrap")
            self.assertNotIn("corp_db.stale_lookup", {route["route_id"] for route in payload["routes"]})

    def test_generated_source_owned_route_overrides_bootstrap_route_id(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            repo_root = Path(repo_tmp)
            self._write_repo_manifest(
                repo_root,
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "generated-v1",
                    "source_owner": "corp_db",
                    "routes": [
                        {
                            "route_id": "corp_db.catalog_lookup",
                            "route_family": "corp_db.catalog_lookup",
                            "route_kind": "corp_table",
                            "authority": "primary",
                            "title": "Generated catalog lookup",
                            "keywords": ["generated"],
                            "patterns": ["generated catalog"],
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
                payload = build_routing_index()

            route = next(route for route in payload["routes"] if route["route_id"] == "corp_db.catalog_lookup")
            self.assertEqual(route["title"], "Generated catalog lookup")
            self.assertEqual(route["route_owner"], "corp_db")
            self.assertTrue(payload["validation_report"]["valid"])
            self.assertEqual(payload["validation_report"]["overrides"][0]["reason"], "bootstrap_precedence")

    def test_duplicate_route_ids_from_different_owners_require_explicit_override(self):
        base_route = {
            "route_id": "corp_db.conflict",
            "route_family": "corp_db.conflict",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Conflict",
            "keywords": ["conflict"],
            "patterns": ["conflict"],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "lamp_exact"},
        }
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            repo_root = Path(repo_tmp)
            self._write_repo_manifest_named(
                repo_root,
                "01-static.json",
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "static-v1",
                    "source_owner": "repo_static",
                    "routes": [base_route],
                },
            )
            self._write_repo_manifest_named(
                repo_root,
                "02-generated.json",
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "generated-v1",
                    "source_owner": "corp_db",
                    "routes": [{**base_route, "title": "Generated conflict"}],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(repo_root), "CORP_DOCS_ROOT": str(Path(docs_tmp))},
                clear=False,
            ):
                payload = build_routing_index()

            self.assertFalse(payload["validation_report"]["valid"])
            self.assertEqual(payload["validation_report"]["duplicate_route_ids"][0]["route_id"], "corp_db.conflict")

        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            repo_root = Path(repo_tmp)
            self._write_repo_manifest_named(
                repo_root,
                "01-static.json",
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "static-v1",
                    "source_owner": "repo_static",
                    "routes": [base_route],
                },
            )
            self._write_repo_manifest_named(
                repo_root,
                "02-generated.json",
                {
                    "catalog_id": "test-routing",
                    "schema_version": 1,
                    "catalog_version": "generated-v1",
                    "source_owner": "corp_db",
                    "routes": [{**base_route, "title": "Generated conflict", "overrides_route_ids": ["corp_db.conflict"]}],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(repo_root), "CORP_DOCS_ROOT": str(Path(docs_tmp))},
                clear=False,
            ):
                payload = build_routing_index()

            route = next(route for route in payload["routes"] if route["route_id"] == "corp_db.conflict")
            self.assertTrue(payload["validation_report"]["valid"])
            self.assertEqual(route["title"], "Generated conflict")
            self.assertEqual(payload["validation_report"]["overrides"][0]["reason"], "explicit_override")

    def test_production_runtime_reports_unavailable_without_valid_active_catalog(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {
                    "DOC_REPO_ROOT": repo_tmp,
                    "CORP_DOCS_ROOT": docs_tmp,
                    "ROUTING_CATALOG_REQUIRED": "true",
                },
                clear=False,
            ):
                selection = select_route("Какие есть сертификаты?")
                health = routing_catalog_health()

            self.assertTrue(selection["temporary_unavailable"])
            self.assertEqual(selection["route_count"], 0)
            self.assertEqual(health["status"], "unavailable")

    def test_required_runtime_catalog_fails_closed_even_with_repo_manifests(self):
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
                {
                    "DOC_REPO_ROOT": str(repo_root),
                    "CORP_DOCS_ROOT": str(Path(docs_tmp)),
                    "ROUTING_CATALOG_REQUIRED": "true",
                },
                clear=False,
            ):
                with self.assertRaises(RouteCatalogUnavailable):
                    load_routing_index()
                with self.assertRaises(RouteCatalogUnavailable):
                    build_route_selector_payload("custom lookup")
                selection = select_route("custom lookup")
                health = routing_catalog_health()

            self.assertTrue(selection["temporary_unavailable"])
            self.assertTrue(selection["catalog_unavailable"])
            self.assertEqual(selection["route_count"], 0)
            self.assertEqual(health["status"], "unavailable")

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
            self.assertNotIn("doc_search.document_lookup", {route["route_id"] for route in payload["routes"]})

    def test_loaded_runtime_catalog_revalidates_with_current_bootstrap_routes(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = build_routing_index()
                route_dir = Path(docs_tmp) / "manifests" / "routes"
                catalog_path = route_dir / ROUTING_CATALOG_FILENAME
                stale_payload = dict(payload)
                stale_payload["routes"] = [
                    route for route in payload["routes"] if route.get("route_id") != "corp_db.portfolio_lookup"
                ]
                catalog_path.write_text(json.dumps(stale_payload, ensure_ascii=False), encoding="utf-8")

                loaded = load_routing_index()

        self.assertIn("corp_db.portfolio_lookup", {route["route_id"] for route in loaded["routes"]})
        self.assertTrue(loaded["validation_report"]["valid"])

    def test_select_route_returns_candidates_reason_and_kind(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            docs_root = Path(docs_tmp)
            self._write_live_document(
                docs_root,
                document_id="doc_fire_line",
                title="Пожарный сертификат LINE",
                summary="Пожарный сертификат LINE с прямой ссылкой.",
                routing={
                    "route_id": "doc_search.fire_line_certificate",
                    "route_family": "doc_search.fire_line_certificate",
                    "topics": ["fire_certificate", "line"],
                    "keywords": ["пожарный сертификат line", "сертификат line"],
                    "patterns": ["пожарный сертификат line"],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                build_routing_index()
                selection = select_route(
                    "Нужен пожарный сертификат LINE, дай прямую ссылку.",
                    explicit_document_request=True,
                )
            self.assertEqual(selection["selected"]["route_id"], "doc_search.fire_line_certificate")
            self.assertEqual(selection["primary_candidate"]["route_id"], "doc_search.fire_line_certificate")
            self.assertEqual(selection["selected_route_kind"], "doc_domain")
            self.assertEqual(selection["intent_family"], "document_lookup")
            self.assertEqual(selection["selection_reason"], "degraded_intent_order:document_lookup")
            self.assertTrue(selection["candidate_route_ids"])

    def test_fire_certificate_query_does_not_select_unrelated_sports_document_route(self):
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
                    ],
                    "patterns": ["нормы освещенности для спортивных объектов"],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                build_routing_index()
                selection = select_route("Найди пожарный сертификат LINE и дай прямую ссылку.")

            self.assertEqual(selection["intent_family"], "document_lookup")
            self.assertIsNone(selection["selected"])
            self.assertIsNone(selection["primary_candidate"])
            self.assertNotIn("doc_search.sports_lighting_norms", selection["candidate_route_ids"])

    def test_explicit_sports_norms_document_query_selects_matching_document_route(self):
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
                    ],
                    "patterns": ["нормы освещенности для спортивных объектов"],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                build_routing_index()
                selection = select_route("Найди в документе нормы освещенности для спортивных объектов.")

            self.assertEqual(selection["selected"]["route_id"], "doc_search.sports_lighting_norms")
            self.assertEqual(selection["primary_candidate"]["route_id"], "doc_search.sports_lighting_norms")
            self.assertEqual(selection["selected_route_kind"], "doc_domain")
            self.assertEqual(selection["intent_family"], "document_lookup")

    def test_generic_document_lookup_route_is_filtered_from_manifests(self):
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
                            "route_id": "doc_search.document_lookup",
                            "route_family": "doc_domain.document_lookup",
                            "route_kind": "doc_domain",
                            "authority": "secondary",
                            "title": "Generic document lookup",
                            "keywords": ["сертификат", "pdf"],
                            "patterns": ["сертификат"],
                            "executor": "doc_search",
                            "executor_args_template": {"top": 5},
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
                selection = select_route("Нужен пожарный сертификат LINE, дай прямую ссылку.")

            self.assertNotIn("doc_search.document_lookup", {route["route_id"] for route in payload["routes"]})
            self.assertIsNone(selection["selected"])

    def test_live_document_can_publish_multiple_thematic_routes_with_shared_selectors(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            docs_root = Path(docs_tmp)
            self._write_live_document(
                docs_root,
                document_id="doc_sports_norms",
                title="СП 440.1325800.2023",
                summary="Освещение спортивных сооружений.",
                routing={
                    "routes": [
                        {
                            "route_id": "doc_search.sports_lighting_norms",
                            "route_family": "doc_search.sports_lighting_norms",
                            "topics": ["sports_lighting"],
                            "keywords": ["нормы освещенности спортивных объектов"],
                            "patterns": ["нормы освещенности для спортивных объектов"],
                        },
                        {
                            "route_id": "doc_search.sports_tv_lighting",
                            "route_family": "doc_search.sports_tv_lighting",
                            "topics": ["sports_tv_lighting"],
                            "keywords": ["телевизионная трансляция спортивных игр"],
                            "patterns": ["требования для телевизионной трансляции"],
                        },
                    ]
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                payload = build_routing_index()

            routes = {route["route_id"]: route for route in payload["routes"]}
            self.assertIn("doc_search.sports_lighting_norms", routes)
            self.assertIn("doc_search.sports_tv_lighting", routes)
            for route_id in ("doc_search.sports_lighting_norms", "doc_search.sports_tv_lighting"):
                route = routes[route_id]
                self.assertIn("doc_sports_norms", route["document_selectors"])
                self.assertIn("doc_sports_norms.pdf", route["document_selectors"])
                self.assertEqual(route["executor_args_template"]["preferred_document_ids"], route["document_selectors"])

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

    def test_select_route_routes_generic_certification_and_quality_to_company_common(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                cases = (
                    ("какие есть сертификаты?", "certification"),
                    ("Какие используются комплектующие?", "quality"),
                )
                for query, facet in cases:
                    with self.subTest(query=query):
                        selection = select_route(query)

                        self.assertEqual(selection["intent_family"], "company_fact")
                        self.assertEqual(selection["selected"]["route_id"], "corp_kb.company_common")
                        self.assertEqual(selection["primary_candidate"]["route_id"], "corp_kb.company_common")
                        self.assertEqual(selection["selected_route_kind"], "corp_table")
                        self.assertIn("corp_kb.company_common", selection["candidate_route_ids"])
                        self.assertNotEqual(selection["selected"]["route_id"], "doc_search.document_lookup")

    def test_select_route_prefers_company_common_for_broad_series_questions(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                for query in (
                    "какие у вас есть серии светильников?",
                    "в общей базе есть описание всех серий",
                ):
                    with self.subTest(query=query):
                        selection = select_route(query)
                        payload = build_route_selector_payload(query, limit=5)

                        self.assertEqual(selection["intent_family"], "catalog_lookup")
                        self.assertEqual(selection["selected"]["route_id"], "corp_kb.company_common")
                        self.assertEqual(selection["primary_candidate"]["route_id"], "corp_kb.company_common")
                        self.assertEqual(payload["candidate_route_ids"][0], "corp_kb.company_common")

    def test_select_route_prefers_curated_sphere_categories_for_broad_category_questions(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                selection = select_route("Какие категории подходят для склада?")
                payload = build_route_selector_payload("Какие категории подходят для склада?", limit=5)

        self.assertEqual(selection["intent_family"], "catalog_lookup")
        self.assertEqual(selection["selected"]["route_id"], "corp_db.sphere_curated_categories")
        self.assertEqual(payload["candidate_route_ids"][0], "corp_db.sphere_curated_categories")

    def test_select_route_prefers_category_mountings_for_series_mounting_questions(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                selection = select_route("Какие крепления доступны у серии NL Nova?")
                payload = build_route_selector_payload("Какие крепления доступны у серии NL Nova?", limit=5)

        self.assertEqual(selection["intent_family"], "catalog_lookup")
        self.assertEqual(selection["selected"]["route_id"], "corp_db.category_mountings")
        self.assertEqual(payload["candidate_route_ids"][0], "corp_db.category_mountings")

    def test_default_corp_db_routes_cover_structured_domains(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = load_routing_index()

        routes = {route["route_id"]: route for route in payload["routes"]}
        expected_route_ids = {
            "corp_kb.company_common",
            "corp_db.catalog_lookup",
            "corp_db.sku_lookup",
            "corp_db.category_lamps",
            "corp_db.sphere_curated_categories",
            "corp_db.sphere_categories",
            "corp_db.lamp_filters",
            "corp_db.category_mountings",
            "corp_db.lamp_mounting_compatibility",
            "corp_db.portfolio_lookup",
            "corp_db.portfolio_by_sphere",
            "corp_db.portfolio_examples_by_lamp",
            "corp_db.application_recommendation",
        }
        self.assertTrue(expected_route_ids.issubset(routes))
        self.assertEqual(payload["validation_report"]["missing_corp_db_domains"], [])

        for route_id in expected_route_ids:
            route = routes[route_id]
            self.assertEqual(route["executor"], "corp_db_search")
            self.assertIn("kind", route["locked_args"])
            self.assertIn("kind", route["argument_schema"]["properties"])
            self.assertTrue(route["evidence_policy"])
            self.assertTrue(route["table_scopes"])

        self.assertNotIn("enum", routes["corp_db.sku_lookup"]["argument_schema"]["properties"]["etm"])
        self.assertNotIn("enum", routes["corp_db.sku_lookup"]["argument_schema"]["properties"]["oracl"])
        self.assertEqual(
            routes["corp_db.sphere_curated_categories"]["argument_schema"]["properties"]["sphere"]["enum"],
            canonical_sphere_names(),
        )
        self.assertEqual(
            routes["corp_db.sphere_categories"]["argument_schema"]["properties"]["sphere"]["enum"],
            canonical_sphere_names(),
        )
        self.assertEqual(
            routes["corp_db.portfolio_by_sphere"]["argument_schema"]["properties"]["sphere"]["enum"],
            canonical_sphere_names(),
        )
        self.assertEqual(
            routes["corp_db.category_mountings"]["argument_schema"]["properties"]["mounting_type"]["enum"],
            canonical_mounting_type_names(),
        )
        self.assertEqual(
            routes["corp_db.lamp_mounting_compatibility"]["argument_schema"]["properties"]["mounting_type"]["enum"],
            canonical_mounting_type_names(),
        )
        self.assertEqual(
            routes["corp_db.lamp_filters"]["argument_schema"]["properties"]["mounting_type"]["enum"],
            canonical_mounting_type_names(),
        )
        self.assertEqual(
            routes["corp_db.category_mountings"]["argument_schema"]["properties"]["series"]["enum"],
            canonical_series_names(),
        )
        self.assertEqual(
            routes["corp_db.lamp_mounting_compatibility"]["argument_schema"]["properties"]["series"]["enum"],
            canonical_series_names(),
        )
        self.assertEqual(
            routes["corp_db.portfolio_lookup"]["argument_schema"]["required"],
            ["kind", "query"],
        )
        self.assertEqual(
            routes["corp_db.portfolio_by_sphere"]["argument_schema"]["required"],
            ["kind", "sphere"],
        )
        self.assertEqual(
            routes["corp_db.sphere_curated_categories"]["argument_schema"]["required"],
            ["kind", "sphere"],
        )
        self.assertNotIn("sphere", routes["corp_db.portfolio_lookup"]["argument_schema"]["properties"])
        self.assertNotIn("category", routes["corp_db.sphere_curated_categories"]["argument_schema"]["properties"])
        self.assertNotIn("series", routes["corp_db.catalog_lookup"]["argument_schema"]["properties"])

    def test_selector_payload_uses_compact_route_specific_enums(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = build_route_selector_payload("Какие крепления доступны у серии NL Nova?")

        routes = {route["route_id"]: route for route in payload["routes"]}
        self.assertEqual(
            routes["corp_db.category_mountings"]["argument_schema"]["properties"]["series"]["enum"],
            canonical_series_names(),
        )
        self.assertEqual(
            routes["corp_db.lamp_mounting_compatibility"]["argument_schema"]["properties"]["series"]["enum"],
            canonical_series_names(),
        )
        self.assertEqual(
            routes["corp_db.portfolio_by_sphere"]["argument_schema"]["properties"]["sphere"]["enum"],
            canonical_sphere_names(),
        )
        self.assertEqual(
            routes["corp_db.category_mountings"]["argument_schema"]["properties"]["mounting_type"]["enum"],
            canonical_mounting_type_names(),
        )
        self.assertEqual(
            routes["corp_db.lamp_filters"]["argument_schema"]["properties"]["mounting_type"]["enum"],
            canonical_mounting_type_names(),
        )
        self.assertNotIn("series", routes["corp_db.catalog_lookup"]["argument_schema"]["properties"])
        for route in routes.values():
            category_schema = route["argument_schema"]["properties"].get("category")
            if isinstance(category_schema, dict):
                self.assertNotIn("enum", category_schema)

    def test_selector_payload_injects_scoped_curated_category_enum_for_local_follow_up(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = build_route_selector_payload(
                    "Покажи модели из этой категории",
                    sphere_context={
                        "sphere_name": "Складские помещения",
                        "category_names": curated_category_names_for_sphere("Складские помещения"),
                        "source_turn_id": 1,
                        "confirmed": True,
                    },
                )

        routes = {route["route_id"]: route for route in payload["routes"]}
        expected_categories = curated_category_names_for_sphere("Складские помещения")
        self.assertEqual(payload["resolved_sphere_context"]["sphere_name"], "Складские помещения")
        self.assertEqual(
            routes["corp_db.category_mountings"]["argument_schema"]["properties"]["category"]["enum"],
            expected_categories,
        )
        self.assertEqual(
            routes["corp_db.lamp_filters"]["argument_schema"]["properties"]["category"]["enum"],
            expected_categories,
        )
        self.assertEqual(
            routes["corp_db.category_mountings"]["argument_hints"]["category"],
            "Choose one curated category from the active sphere context: Складские помещения.",
        )

    def test_select_route_matches_portfolio_lookup_for_realized_project_queries(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                named_project = select_route("Расскажи подробнее про терминально-логистический центр Белый Раст")
                rzd_projects = select_route("Какие объекты были реализованы для РЖД?")
                payload = build_route_selector_payload("Какие реализованные проекты есть у компании?")

        self.assertEqual(named_project["intent_family"], "portfolio_lookup")
        self.assertEqual(named_project["selected"]["route_id"], "corp_db.portfolio_lookup")
        self.assertEqual(rzd_projects["intent_family"], "portfolio_lookup")
        self.assertEqual(rzd_projects["selected"]["route_id"], "corp_db.portfolio_by_sphere")
        self.assertIn("corp_db.portfolio_lookup", payload["candidate_route_ids"])
        self.assertNotIn("score", payload["routes"][0])
        self.assertNotIn("selection_score", named_project)

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
            self.assertEqual(selection["intent_family"], "application_recommendation")
            self.assertIn("corp_db.application_recommendation", selection["candidate_route_ids"])

    def test_select_route_biases_broad_recommendation_queries_away_from_live_doc_routes(self):
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
                    ],
                    "patterns": [
                        "какие нормы освещенности для спортивных объектов",
                    ],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                for query in (
                    "Подбери освещение для спортивного стадиона",
                    "Подбери освещение для склада",
                    "Подбери освещение для аэропорта",
                ):
                    selection = select_route(query)
                    self.assertEqual(selection["selected"]["route_id"], "corp_db.application_recommendation")
                    self.assertEqual(selection["intent_family"], "application_recommendation")
                    self.assertEqual(selection["primary_candidate"]["route_id"], "corp_db.application_recommendation")
                    self.assertTrue(selection["secondary_candidates"])
                    self.assertIn("corp_db.application_recommendation", selection["candidate_route_ids"])
                    self.assertNotEqual(selection["primary_candidate"]["route_id"], "doc_search.sports_lighting_norms")

    def test_passport_query_does_not_match_unrelated_sports_document_route(self):
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
                    ],
                    "patterns": ["нормы освещенности для спортивных объектов"],
                },
            )
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": str(Path(repo_tmp)), "CORP_DOCS_ROOT": str(docs_root)},
                clear=False,
            ):
                selection = select_route("Нужен паспорт светильника LINE.")

            selected = selection.get("selected")
            self.assertNotEqual((selected or {}).get("route_id"), "doc_search.sports_lighting_norms")
            self.assertNotIn("doc_search.sports_lighting_norms", selection["candidate_route_ids"][:1])


if __name__ == "__main__":
    unittest.main()
