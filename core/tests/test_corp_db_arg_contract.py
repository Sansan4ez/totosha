"""Contract tests for corp_db kind-specific selector argument filtering."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE_DIR))

from documents import routing
from documents.route_schema import selector_arg_keys_for_kind


class CorpDbArgContractTests(unittest.TestCase):
    def test_allowed_args_cover_every_schema_property_for_filtered_kinds(self):
        module_path = CORE_DIR / "tools" / "corp_db.py"
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("KIND_SPECIFIC_ARG_ALLOWLISTS", source)
        tree = ast.parse(source)
        kinds = self._constant_string_set(tree, "KIND_SPECIFIC_ARG_KINDS")
        transport_keys = self._constant_string_set(tree, "TRANSPORT_ARG_KEYS")
        self.assertTrue(kinds)

        routes = routing.load_static_route_cards()
        for kind in kinds:
            matching = [
                route
                for route in routes
                if str((route.get("executor_args_template") or {}).get("kind") or "") == kind
            ]
            self.assertTrue(matching, kind)
            allowed = transport_keys | selector_arg_keys_for_kind(kind)
            for route in matching:
                with self.subTest(kind=kind, route=route.get("route_id")):
                    properties = set((route.get("argument_schema") or {}).get("properties") or {})
                    self.assertLessEqual(properties, allowed, f"{route.get('route_id')}: {properties - allowed}")

    @staticmethod
    def _constant_string_set(tree: ast.Module, name: str) -> frozenset[str]:
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            ):
                value = node.value.args[0] if isinstance(node.value, ast.Call) else node.value
                return frozenset(ast.literal_eval(value))
        raise AssertionError(f"missing {name}")

    def test_selector_keys_are_read_from_schema_files(self):
        selector_arg_keys_for_kind.cache_clear()
        keys = selector_arg_keys_for_kind("application_recommendation")
        self.assertIn("application_key", keys)
        self.assertIn("context_profile", keys)
        self.assertNotIn("kind", keys)


if __name__ == "__main__":
    unittest.main()
