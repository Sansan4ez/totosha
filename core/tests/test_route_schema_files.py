"""RFC-029 workstream 4: standalone JSON Schema files are the argument contract.

Locks three invariants:
1. every route card YAML has a sibling .schema.json and no inline argument_schema;
2. every schema file is a valid (normalizable) closed schema;
3. every schema file matches what scripts/generate_route_argument_schemas.py would
   regenerate from the executor template + allowlists, so the files cannot silently
   drift from the runtime contract (the RFC's byte-for-byte migration equivalence,
   kept as a permanent regression lock).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from documents import routing
from documents.route_schema import (
    normalize_argument_schema,
    normalize_route_card_contract,
    validate_route_choice_output,
)


class RouteSchemaFilesTests(unittest.TestCase):
    def _card_paths(self) -> list[Path]:
        paths = sorted(routing.static_route_catalog_dir().glob("*/*.yaml"))
        self.assertTrue(paths)
        return paths

    def test_every_card_has_valid_schema_file_and_no_inline_schema(self):
        for card_path in self._card_paths():
            with self.subTest(card=card_path.name):
                payload = yaml.safe_load(card_path.read_text(encoding="utf-8"))
                self.assertNotIn("argument_schema", payload)
                self.assertTrue(str(payload.get("schema_ref") or "").strip())
                schema_path = routing._route_schema_file_path(card_path, payload)
                self.assertTrue(schema_path.is_file(), schema_path)
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                normalized = normalize_argument_schema(schema)
                self.assertIs(normalized["additionalProperties"], False)

    def test_schema_files_match_generator_output(self):
        for card_path in self._card_paths():
            with self.subTest(card=card_path.name):
                payload = yaml.safe_load(card_path.read_text(encoding="utf-8"))
                route = dict(payload)
                route.pop("argument_schema", None)
                route.pop("argument_schema_origin", None)
                routing._apply_runtime_argument_overrides(route)
                schema_path = routing._route_schema_file_path(card_path, payload)
                on_disk = json.loads(schema_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    on_disk,
                    route["argument_schema"],
                    f"{schema_path.name} is stale; re-run scripts/generate_route_argument_schemas.py",
                )

    def test_loaded_catalog_uses_schema_files(self):
        routing._load_static_route_cards_from_disk.cache_clear()
        routes = routing.load_static_route_cards()
        self.assertTrue(routes)
        for route in routes:
            with self.subTest(route=route.get("route_id")):
                self.assertEqual(route.get("argument_schema_origin"), "schema_file")
                self.assertIsInstance(route.get("argument_schema"), dict)

    def test_catalog_selector_preserves_declared_cross_family_fallbacks(self):
        routes = routing.bootstrap_route_cards()
        routes_by_id = {route["route_id"]: route for route in routes}
        fallback_ids = ["corp_db.series_models", "corp_db.sku_lookup"]
        catalog = normalize_route_card_contract(routes_by_id["corp_db.catalog_lookup"])
        self.assertEqual(catalog["fallback_policy"]["cross_family_route_ids"], fallback_ids)
        result = validate_route_choice_output(
            {
                "selected_route_id": "corp_db.catalog_lookup",
                "fallback_route_ids": fallback_ids,
            },
            routes,
        )
        self.assertTrue(result.valid, result.error)
        self.assertEqual(result.fallback_route_ids, fallback_ids)
        self.assertEqual(result.sanitization_actions, [])

    def test_catalog_fallback_review_keeps_undeclared_routes_blocked(self):
        routes = routing.bootstrap_route_cards()
        for selected, proposed in (
            ("corp_db.catalog_lookup", "corp_db.lamp_filters"),
            ("corp_db.application_recommendation", "corp_db.catalog_lookup"),
            ("corp_db.sku_lookup", "corp_db.catalog_lookup"),
        ):
            with self.subTest(selected=selected, proposed=proposed):
                result = validate_route_choice_output(
                    {"selected_route_id": selected, "fallback_route_ids": [proposed]},
                    routes,
                )
                self.assertTrue(result.valid, result.error)
                self.assertEqual(result.fallback_route_ids, [])
                self.assertIn("dropped_undeclared_fallback", result.sanitization_actions)

    def test_document_routes_accept_bounded_names_array(self):
        routing._load_static_route_cards_from_disk.cache_clear()
        routes = {str(route.get("route_id")): route for route in routing.load_static_route_cards()}
        for route_id in (
            "corp_db.documents_by_lamp_name",
            "corp_db.certificate_by_lamp_name",
            "corp_db.passport_by_lamp_name",
            "corp_db.manual_by_lamp_name",
            "corp_db.ies_by_lamp_name",
        ):
            with self.subTest(route=route_id):
                properties = routes[route_id]["argument_schema"]["properties"]
                self.assertIn("names", properties)
                self.assertNotIn("name", properties)
                self.assertEqual(properties["names"]["minItems"], 1)
                self.assertEqual(properties["names"]["maxItems"], 5)


if __name__ == "__main__":
    unittest.main()
