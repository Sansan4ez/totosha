"""Contract tests for corp_db kind-specific selector argument filtering."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import patch

CORE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE_DIR))

from documents import routing
from documents.corp_db_contract import allowed_fields_for_kind
from documents.route_schema import selector_arg_keys_for_kind


def _load_corp_db_module():
    """Load the runtime sanitizer without requiring aiohttp or observability."""
    module_path = CORE_DIR / "tools" / "corp_db.py"
    stubs = {
        "aiohttp": types.ModuleType("aiohttp"),
        "observability": types.SimpleNamespace(
            REQUEST_ID=ContextVar("request_id", default="-"),
            get_correlation_context=lambda: {},
            inject_trace_context=lambda headers=None, request_id=None: dict(headers or {}),
            observe_retrieval_constraint_evidence=lambda *args, **kwargs: None,
            observe_route_selector_sanitization=lambda *args, **kwargs: None,
            update_correlation_context=lambda *args, **kwargs: {},
        ),
        "opentelemetry": types.SimpleNamespace(trace=types.SimpleNamespace(get_tracer=lambda *args: None)),
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    spec = importlib.util.spec_from_file_location("corp_db_arg_contract_module", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules.update(stubs)
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


_CORP_DB = _load_corp_db_module()
_sanitize_corp_db_args = _CORP_DB._sanitize_corp_db_args


class CorpDbArgContractTests(unittest.TestCase):
    def test_hermetic_loader_exposes_sanitizer(self):
        self.assertTrue(callable(_CORP_DB._sanitize_corp_db_args))

    def test_manifest_covers_every_selector_schema_property(self):
        routes = routing.load_static_route_cards()
        for route in routes:
            template = dict(route.get("executor_args_template") or {})
            kind = str(template.get("kind") or "")
            allowed = allowed_fields_for_kind(kind, template)
            with self.subTest(kind=kind, route=route.get("route_id")):
                self.assertTrue(allowed, f"missing manifest contract for {kind}")
                properties = set((route.get("argument_schema") or {}).get("properties") or {})
                self.assertLessEqual(properties, allowed, f"{route.get('route_id')}: {properties - allowed}")

    def test_kind_specific_constant_controls_runtime_filtering(self):
        filtered = _sanitize_corp_db_args(
            {
                "kind": "application_recommendation",
                "application_key": "warehouse",
                "bogus": 1,
            }
        )
        self.assertEqual(
            filtered,
            {"kind": "application_recommendation", "application_key": "warehouse"},
        )

        unfiltered = _sanitize_corp_db_args(
            {
                "kind": "hybrid_search",
                "bogus": 1,
                "limit_categories": 3,
                "limit_lamps": 4,
                "limit_portfolio": 5,
            }
        )
        self.assertEqual(unfiltered, {"kind": "hybrid_search", "bogus": 1})

        with patch.object(
            _CORP_DB,
            "KIND_SPECIFIC_ARG_KINDS",
            _CORP_DB.KIND_SPECIFIC_ARG_KINDS | {"hybrid_search"},
        ):
            newly_filtered = _sanitize_corp_db_args(
                {"kind": "hybrid_search", "query": "warehouse", "bogus": 1}
            )
        self.assertEqual(newly_filtered, {"kind": "hybrid_search", "query": "warehouse"})

    def test_selector_keys_are_read_from_schema_files(self):
        selector_arg_keys_for_kind.cache_clear()
        keys = selector_arg_keys_for_kind("application_recommendation")
        self.assertIn("application_key", keys)
        self.assertIn("context_profile", keys)
        self.assertNotIn("kind", keys)


if __name__ == "__main__":
    unittest.main()
