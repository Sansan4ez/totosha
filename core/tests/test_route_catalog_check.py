import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from documents.route_catalog_check import (
    check_executor_resolution,
    check_schema_closed,
    check_sibling_fallback_coverage,
    run_checks,
)


def _kb_route(route_id: str, family_id: str, *, fallback_route_ids=None, fallback_policy=None) -> dict:
    return {
        "route_id": route_id,
        "family_id": family_id,
        "executor": "corp_db_search",
        "executor_args_template": {
            "kind": "hybrid_search",
            "knowledge_route_id": "corp_kb.shared_scope",
            "source_files": ["shared.md"],
        },
        "fallback_route_ids": fallback_route_ids or [],
        "fallback_policy": fallback_policy or {},
        "argument_schema": {"additionalProperties": False, "properties": {}},
        "execution_argument_schema": {"additionalProperties": False, "properties": {}},
    }


class RouteCatalogCheckTests(unittest.TestCase):
    def test_current_bootstrap_catalog_passes_all_checks(self):
        # Regression guard for RFC-028 workstream 2: the live routes/ catalog (including the
        # 2026-07-06 incident fix for corp_kb.company_common/corp_kb.series_description) must
        # pass with zero errors.
        errors = run_checks()
        self.assertEqual(errors, [])

    def test_sibling_kb_scope_without_mutual_fallback_is_flagged(self):
        route_a = _kb_route("family.a", "family_x")
        route_b = _kb_route("family.b", "family_x")

        errors = check_sibling_fallback_coverage([route_a, route_b])

        self.assertEqual(len(errors), 2)
        self.assertIn("family.a", errors[0])
        self.assertIn("family.b", errors[1])

    def test_sibling_kb_scope_with_mutual_fallback_passes(self):
        route_a = _kb_route("family.a", "family_x", fallback_route_ids=["family.b"])
        route_b = _kb_route("family.b", "family_x", fallback_route_ids=["family.a"])

        errors = check_sibling_fallback_coverage([route_a, route_b])

        self.assertEqual(errors, [])

    def test_sibling_kb_scope_with_documented_opt_out_passes(self):
        route_a = _kb_route(
            "family.a",
            "family_x",
            fallback_policy={"no_sibling_fallback": True, "no_sibling_fallback_reason": "narrower specialization"},
        )
        route_b = _kb_route(
            "family.b",
            "family_x",
            fallback_policy={"no_sibling_fallback": True, "no_sibling_fallback_reason": "narrower specialization"},
        )

        errors = check_sibling_fallback_coverage([route_a, route_b])

        self.assertEqual(errors, [])

    def test_opt_out_without_reason_still_fails(self):
        route_a = _kb_route("family.a", "family_x", fallback_policy={"no_sibling_fallback": True})
        route_b = _kb_route("family.b", "family_x")

        errors = check_sibling_fallback_coverage([route_a, route_b])

        self.assertEqual(len(errors), 2)

    def test_different_families_are_not_compared(self):
        route_a = _kb_route("family.a", "family_x")
        route_b = _kb_route("family.b", "family_y")

        errors = check_sibling_fallback_coverage([route_a, route_b])

        self.assertEqual(errors, [])

    def test_unregistered_executor_is_flagged(self):
        # known_executors is injected explicitly so this stays deterministic regardless of
        # whether an unrelated test elsewhere in the suite has stubbed sys.modules["tools"].
        route = {"route_id": "bad.route", "executor": "does_not_exist"}

        errors = check_executor_resolution([route], known_executors={"corp_db_search": object()})

        self.assertEqual(len(errors), 1)
        self.assertIn("does_not_exist", errors[0])

    def test_open_schema_is_flagged(self):
        route = {
            "route_id": "bad.route",
            "argument_schema": {"additionalProperties": True},
            "execution_argument_schema": {"additionalProperties": False},
        }

        errors = check_schema_closed([route])

        self.assertEqual(len(errors), 1)
        self.assertIn("argument_schema", errors[0])


if __name__ == "__main__":
    unittest.main()
