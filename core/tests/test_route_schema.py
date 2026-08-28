import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from documents.route_schema import (
    RouteCardContractError,
    merge_route_tool_args,
    normalize_route_card_contract,
    validate_selector_output,
)
from documents.routing import load_routing_index
from agent import _compact_selector_argument_schema


def _route(payload: dict) -> dict:
    base = {
        "route_id": "corp_kb.company_common",
        "route_family": "corp_kb.company_common",
        "family_id": "company_info",
        "family_title": "Company information",
        "leaf_route_id": "company_general",
        "route_stage": "stage1_general",
        "route_kind": "corp_table",
        "authority": "primary",
        "title": "Company common knowledge base",
        "summary": "Company facts.",
        "executor": "corp_db_search",
        "executor_args_template": {
            "kind": "hybrid_search",
            "profile": "kb_route_lookup",
            "knowledge_route_id": "corp_kb.company_common",
            "source_files": ["common_information_about_company.md"],
        },
    }
    base.update(payload)
    return normalize_route_card_contract(base)


class RouteSchemaTests(unittest.TestCase):
    def test_bootstrap_routes_expose_rfc025_contract_fields(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            payload = None
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = load_routing_index()
        route = next(item for item in payload["routes"] if item["route_id"] == "corp_kb.company_common")

        for field_name in (
            "argument_schema",
            "locked_args",
            "argument_hints",
            "evidence_policy",
            "fallback_route_ids",
            "cross_family_fallback_route_ids",
            "fallback_policy",
            "document_selectors",
            "table_scopes",
            "negative_keywords",
        ):
            self.assertIn(field_name, route)

        self.assertFalse(route["argument_schema"]["additionalProperties"])
        self.assertEqual(route["locked_args"]["kind"], "hybrid_search")
        self.assertIn("corp_kb.company_common", route["table_scopes"])
        self.assertEqual(route["tool_args"]["kind"], "hybrid_search")

    def test_selector_args_merge_defaults_then_valid_selector_args_then_locked_args(self):
        route = _route(
            {
                "locked_args": {
                    "kind": "hybrid_search",
                    "profile": "kb_route_lookup",
                    "knowledge_route_id": "corp_kb.company_common",
                    "source_files": ["common_information_about_company.md"],
                }
            }
        )

        final_args = merge_route_tool_args(
            route,
            {
                "query": "контакты компании",
                "topic_facets": ["contacts"],
                "limit": 3,
            },
        )

        self.assertEqual(final_args["query"], "контакты компании")
        self.assertEqual(final_args["limit"], 3)
        self.assertEqual(final_args["profile"], "kb_route_lookup")
        self.assertEqual(final_args["source_files"], ["common_information_about_company.md"])

    def test_selector_rejects_locked_override(self):
        route = _route({})
        result = validate_selector_output(
            {
                "selected_route_id": "corp_kb.company_common",
                "tool_args": {"query": "контакты", "kind": "lamp_exact"},
            },
            [route],
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.error_code, "unsafe_selector_output")
        self.assertFalse(result.repairable)

    def test_selector_rejects_undeclared_args_and_can_repair_once(self):
        route = _route({})
        result = validate_selector_output(
            {
                "selected_route_id": "corp_kb.company_common",
                "tool_args": {"query": "контакты", "sql": "select * from corp.lamps"},
            },
            [route],
        )
        retried = validate_selector_output("not json", [route], repair_attempted=True)

        self.assertFalse(result.valid)
        self.assertEqual(result.error_code, "unsafe_selector_output")
        self.assertFalse(retried.valid)
        self.assertFalse(retried.repairable)

    def test_invalid_json_and_missing_required_args_are_repairable_once(self):
        doc_route = normalize_route_card_contract(
            {
                "route_id": "doc_search.sports_norms",
                "route_family": "doc_domain.sports_norms",
                "route_kind": "doc_domain",
                "authority": "primary",
                "title": "Sports lighting norms",
                "executor": "doc_search",
                "executor_args_template": {"preferred_document_ids": ["doc_sports_norms"]},
            }
        )

        invalid_json = validate_selector_output("not json", [doc_route])
        missing_query = validate_selector_output(
            {"selected_route_id": "doc_search.sports_norms", "tool_args": {}},
            [doc_route],
        )

        self.assertFalse(invalid_json.valid)
        self.assertTrue(invalid_json.repairable)
        self.assertIn("strict JSON", invalid_json.repair_prompt)
        self.assertFalse(missing_query.valid)
        self.assertEqual(missing_query.error_code, "missing_required")
        self.assertTrue(missing_query.repairable)

    def test_selector_accepts_valid_args_and_declared_fallbacks(self):
        fallback = _route(
            {
                "route_id": "corp_kb.luxnet",
                "route_family": "corp_kb.luxnet",
                "executor_args_template": {
                    "kind": "hybrid_search",
                    "profile": "kb_route_lookup",
                    "knowledge_route_id": "corp_kb.luxnet",
                    "source_files": ["about_Luxnet.md"],
                },
            }
        )
        route = _route({"fallback_route_ids": ["corp_kb.luxnet"]})
        result = validate_selector_output(
            json.dumps(
                {
                    "selected_family_id": "company_info",
                    "selected_route_id": "corp_kb.company_common",
                    "tool_args": {"query": "контакты", "topic_facets": ["contacts"]},
                    "fallback_route_ids": ["corp_kb.luxnet"],
                }
            ),
            [route, fallback],
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.selected_family_id, "company_info")
        self.assertEqual(result.tool_args["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(result.fallback_route_ids, ["corp_kb.luxnet"])

    def test_selector_accepts_explicit_cross_family_fallbacks_only_when_declared(self):
        catalog_route = _route(
            {
                "route_id": "corp_db.catalog_lookup",
                "route_family": "corp_db.catalog_lookup",
                "family_id": "catalog",
                "family_title": "Catalog",
                "leaf_route_id": "catalog_entity_lookup",
                "executor_args_template": {"kind": "lamp_exact"},
            }
        )
        route = _route(
            {
                "route_id": "corp_db.documents_by_lamp_name",
                "route_family": "corp_db.documents_by_lamp_name",
                "family_id": "documents",
                "family_title": "Documents",
                "leaf_route_id": "documents_by_lamp_name",
                "executor_args_template": {"kind": "lamp_exact", "limit": 3},
                "fallback_route_ids": ["corp_db.catalog_lookup"],
                "cross_family_fallback_route_ids": ["corp_db.catalog_lookup"],
            }
        )

        result = validate_selector_output(
            {
                "selected_family_id": "documents",
                "selected_route_id": "corp_db.documents_by_lamp_name",
                "tool_args": {"name": "NL Nova"},
                "fallback_route_ids": ["corp_db.catalog_lookup"],
            },
            [route, catalog_route],
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.fallback_route_ids, ["corp_db.catalog_lookup"])

    def test_selector_accepts_same_family_documents_fallback_for_subtype_leaf(self):
        general_route = _route(
            {
                "route_id": "corp_db.documents_by_lamp_name",
                "route_family": "corp_db.documents_by_lamp_name",
                "family_id": "documents",
                "family_title": "Documents",
                "leaf_route_id": "documents_by_lamp_name",
                "executor_args_template": {"kind": "lamp_exact", "limit": 3},
            }
        )
        subtype_route = _route(
            {
                "route_id": "corp_db.passport_by_lamp_name",
                "route_family": "corp_db.documents_by_lamp_name",
                "family_id": "documents",
                "family_title": "Documents",
                "leaf_route_id": "passport_by_lamp_name",
                "executor_args_template": {"kind": "lamp_exact", "limit": 3, "document_type": "passport"},
                "fallback_route_ids": ["corp_db.documents_by_lamp_name"],
            }
        )

        result = validate_selector_output(
            {
                "selected_family_id": "documents",
                "selected_route_id": "corp_db.passport_by_lamp_name",
                "tool_args": {"name": "NL Nova"},
                "fallback_route_ids": ["corp_db.documents_by_lamp_name"],
            },
            [subtype_route, general_route],
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.tool_args["document_type"], "passport")
        self.assertEqual(result.fallback_route_ids, ["corp_db.documents_by_lamp_name"])

    def test_selector_rejects_hidden_selected_route_but_sanitizes_undeclared_fallback(self):
        # RFC-028: selecting a hidden/invisible route stays a material failure (the primary
        # route choice is unrecoverable), but an undeclared fallback hint on an otherwise valid
        # selection is dropped rather than failing the whole request (2026-07-06 incident class).
        route = _route({})
        hidden = _route({"route_id": "corp_kb.hidden", "route_family": "corp_kb.hidden", "hidden": True})

        hidden_result = validate_selector_output(
            {"selected_route_id": "corp_kb.hidden", "tool_args": {"query": "test"}},
            [route, hidden],
        )
        undeclared_fallback = validate_selector_output(
            {
                "selected_route_id": "corp_kb.company_common",
                "tool_args": {"query": "test"},
                "fallback_route_ids": ["corp_kb.hidden"],
            },
            [route, hidden],
        )

        self.assertFalse(hidden_result.valid)
        self.assertEqual(hidden_result.error_code, "unsafe_selector_output")
        self.assertTrue(undeclared_fallback.valid)
        self.assertEqual(undeclared_fallback.fallback_route_ids, [])
        self.assertIn("dropped_undeclared_fallback", undeclared_fallback.sanitization_actions)

    def test_fallback_leaving_family_without_explicit_declaration_is_sanitized(self):
        # RFC-028: this shape is a catalog data bug (fallback_route_ids lists a route from a
        # different family without an explicit cross_family_fallback_route_ids declaration).
        # The primary route selection is still valid; the malformed fallback hint is dropped.
        catalog_route = _route(
            {
                "route_id": "corp_db.catalog_lookup",
                "route_family": "corp_db.catalog_lookup",
                "family_id": "catalog",
                "family_title": "Catalog",
                "leaf_route_id": "catalog_entity_lookup",
                "executor_args_template": {"kind": "lamp_exact"},
            }
        )
        route = _route(
            {
                "route_id": "corp_db.documents_by_lamp_name",
                "route_family": "corp_db.documents_by_lamp_name",
                "family_id": "documents",
                "family_title": "Documents",
                "leaf_route_id": "documents_by_lamp_name",
                "executor_args_template": {"kind": "lamp_exact", "limit": 3},
                "fallback_route_ids": ["corp_db.catalog_lookup"],
            }
        )

        result = validate_selector_output(
            {
                "selected_family_id": "documents",
                "selected_route_id": "corp_db.documents_by_lamp_name",
                "tool_args": {"name": "NL Nova"},
                "fallback_route_ids": ["corp_db.catalog_lookup"],
            },
            [route, catalog_route],
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.fallback_route_ids, [])
        self.assertIn("dropped_undeclared_fallback", result.sanitization_actions)

    def test_selector_family_mismatch_is_sanitized_by_deriving_from_route(self):
        # RFC-028: a mismatched selected_family_id no longer fails the request; the family is
        # derived from the selected route instead, since the route choice is the authoritative
        # signal and the family id is redundant with it.
        route = _route({})
        result = validate_selector_output(
            {
                "selected_family_id": "portfolio",
                "selected_route_id": "corp_kb.company_common",
                "tool_args": {"query": "контакты"},
            },
            [route],
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.selected_family_id, "company_info")
        self.assertIn("derived_family_from_route", result.sanitization_actions)

    def test_argument_schema_enforces_type_enum_bounds_pattern_max_length_and_max_items(self):
        route = _route(
            {
                "argument_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["hybrid_search"]},
                        "profile": {"type": "string", "enum": ["kb_route_lookup"]},
                        "knowledge_route_id": {"type": "string", "pattern": r"^[A-Za-z0-9_.-]+$"},
                        "source_files": {
                            "type": "array",
                            "maxItems": 2,
                            "items": {"type": "string", "maxLength": 120},
                        },
                        "query": {"type": "string", "maxLength": 20},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                        "topic_facets": {
                            "type": "array",
                            "maxItems": 2,
                            "items": {"type": "string", "pattern": r"^[a-z_]+$", "maxLength": 20},
                        },
                    },
                    "required": ["kind", "query"],
                },
                "locked_args": {"kind": "hybrid_search"},
            }
        )

        cases = [
            {"query": "x" * 21},
            {"query": "ok", "limit": 6},
            {"query": "ok", "topic_facets": ["contacts", "legal", "service"]},
            {"query": "ok", "topic_facets": ["невалидно"]},
        ]
        for args in cases:
            with self.subTest(args=args):
                result = validate_selector_output(
                    {"selected_route_id": "corp_kb.company_common", "tool_args": args},
                    [route],
                )
                self.assertFalse(result.valid)
                self.assertIn(result.error_code, {"invalid_tool_args", "unsafe_selector_output"})

    def test_unknown_tool_arg_is_sanitized_instead_of_rejected(self):
        route = _route(
            {
                "argument_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["hybrid_search"]},
                        "query": {"type": "string", "maxLength": 20},
                    },
                    "required": ["kind", "query"],
                },
                "locked_args": {"kind": "hybrid_search"},
            }
        )

        result = validate_selector_output(
            {"selected_route_id": "corp_kb.company_common", "tool_args": {"query": "ok", "extra": "field"}},
            [route],
        )

        self.assertTrue(result.valid)
        self.assertNotIn("extra", result.tool_args)
        self.assertEqual(result.tool_args["query"], "ok")
        self.assertIn("dropped_unknown_tool_arg", result.sanitization_actions)

    def test_document_type_enum_is_enforced_for_documents_routes(self):
        route = normalize_route_card_contract(
            {
                "route_id": "corp_db.documents_by_lamp_name",
                "route_family": "corp_db.documents_by_lamp_name",
                "family_id": "documents",
                "family_title": "Documents",
                "leaf_route_id": "documents_by_lamp_name",
                "route_kind": "corp_table",
                "authority": "primary",
                "title": "Documents by lamp name",
                "executor": "corp_db_search",
                "executor_args_template": {"kind": "lamp_exact", "limit": 3},
            }
        )

        valid = validate_selector_output(
            {
                "selected_family_id": "documents",
                "selected_route_id": "corp_db.documents_by_lamp_name",
                "tool_args": {"name": "NL Nova", "document_type": "passport"},
            },
            [route],
        )
        invalid = validate_selector_output(
            {
                "selected_family_id": "documents",
                "selected_route_id": "corp_db.documents_by_lamp_name",
                "tool_args": {"name": "NL Nova", "document_type": "brochure"},
            },
            [route],
        )

        self.assertTrue(valid.valid)
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.error_code, "invalid_tool_args")

    def test_codes_and_sku_discriminators_are_bounded(self):
        by_code_route = normalize_route_card_contract(
            {
                "route_id": "corp_db.sku_lookup",
                "route_family": "corp_db.sku_lookup",
                "family_id": "codes_and_sku",
                "family_title": "Codes and SKU",
                "leaf_route_id": "sku_by_code",
                "route_kind": "corp_table",
                "authority": "primary",
                "title": "Codes lookup",
                "executor": "corp_db_search",
                "executor_args_template": {"kind": "sku_by_code"},
            }
        )
        by_name_route = normalize_route_card_contract(
            {
                "route_id": "corp_db.sku_codes_lookup",
                "route_family": "corp_db.sku_codes_lookup",
                "family_id": "codes_and_sku",
                "family_title": "Codes and SKU",
                "leaf_route_id": "sku_codes_lookup",
                "route_kind": "corp_table",
                "authority": "primary",
                "title": "Codes by lamp name",
                "executor": "corp_db_search",
                "executor_args_template": {"kind": "lamp_exact"},
            }
        )

        valid_by_code = validate_selector_output(
            {
                "selected_family_id": "codes_and_sku",
                "selected_route_id": "corp_db.sku_lookup",
                "tool_args": {"etm": "123456", "lookup_direction": "by_code", "code_system": "etm"},
            },
            [by_code_route],
        )
        valid_by_name = validate_selector_output(
            {
                "selected_family_id": "codes_and_sku",
                "selected_route_id": "corp_db.sku_codes_lookup",
                "tool_args": {"name": "NL Nova", "lookup_direction": "by_name", "code_system": "oracl"},
            },
            [by_name_route],
        )
        invalid = validate_selector_output(
            {
                "selected_family_id": "codes_and_sku",
                "selected_route_id": "corp_db.sku_lookup",
                "tool_args": {"query": "123456", "lookup_direction": "sideways", "code_system": "sap"},
            },
            [by_code_route],
        )

        self.assertTrue(valid_by_code.valid)
        self.assertTrue(valid_by_name.valid)
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.error_code, "invalid_tool_args")

    def test_any_of_required_arguments_are_enforced(self):
        route = normalize_route_card_contract(
            {
                "route_id": "corp_db.sku_lookup",
                "route_family": "corp_db.sku_lookup",
                "family_id": "codes_and_sku",
                "route_kind": "corp_table",
                "authority": "primary",
                "title": "Code lookup",
                "executor": "corp_db_search",
                "executor_args_template": {"kind": "lamp_code_lookup", "lookup_direction": "by_code"},
                "argument_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string"},
                        "etm": {"type": "string"},
                        "oracl": {"type": "string"},
                    },
                    "required": [],
                    "anyOf": [
                        {"required": ["query"]},
                        {"required": ["etm"]},
                        {"required": ["oracl"]},
                    ],
                },
            }
        )

        missing = validate_selector_output(
            {"selected_route_id": "corp_db.sku_lookup", "tool_args": {}},
            [route],
        )
        valid = validate_selector_output(
            {"selected_route_id": "corp_db.sku_lookup", "tool_args": {"etm": "123456"}},
            [route],
        )

        self.assertFalse(missing.valid)
        self.assertEqual(missing.error_code, "missing_required")
        self.assertTrue(valid.valid)

    def test_compact_selector_schema_preserves_required_alternatives(self):
        compact = _compact_selector_argument_schema(
            {
                "properties": {
                    "query": {"type": "string"},
                    "etm": {"type": "string"},
                },
                "required": [],
                "anyOf": [{"required": ["query"]}, {"required": ["etm"]}],
            },
            {"kind": "lamp_code_lookup", "lookup_direction": "by_code"},
        )

        self.assertEqual(compact["required_any_of"], [["query"], ["etm"]])

    def test_large_enum_domains_are_rejected_by_route_schema(self):
        with self.assertRaises(RouteCardContractError):
            _route(
                {
                    "argument_schema": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["hybrid_search"]},
                            "sku": {"type": "string", "enum": [f"SKU-{idx}" for idx in range(61)]},
                        },
                        "required": ["kind"],
                    }
                }
            )

    def test_2026_07_06_incident_replay_undeclared_series_description_fallback_now_succeeds(self):
        # Regression for production incident (trace 7852fc7fe6909eec06529a124817e571): the
        # selector correctly chose corp_kb.company_common but proposed the sibling leaf
        # corp_kb.series_description as an optional fallback, which the route did not declare.
        # Under the old fail-closed contract this rejected the whole response and the user saw
        # a bounded "service unavailable" answer. RFC-028 sanitizes the undeclared hint instead.
        route = _route({})
        result = validate_selector_output(
            {
                "selected_route_id": "corp_kb.company_common",
                "tool_args": {"query": "светильники в реестре минпромторга"},
                "fallback_route_ids": ["corp_kb.series_description"],
            },
            [route],
        )

        self.assertTrue(result.valid)
        self.assertEqual(result.selected_route_id, "corp_kb.company_common")
        self.assertEqual(result.fallback_route_ids, [])
        self.assertIn("dropped_undeclared_fallback", result.sanitization_actions)

    def test_evidence_policy_bypass_keys_are_rejected(self):
        route = _route({})
        result = validate_selector_output(
            {
                "selected_route_id": "corp_kb.company_common",
                "tool_args": {"query": "контакты"},
                "evidence_policy": {"mode": "none"},
            },
            [route],
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.error_code, "unsafe_selector_output")


if __name__ == "__main__":
    unittest.main()
