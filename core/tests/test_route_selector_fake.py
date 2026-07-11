"""RFC-028 workstream 3: scripted-fake coverage for the injectable route selector.

_select_route_with_llm's LLM call is an injectable dependency (RouteSelectorLLM). These tests
drive the full selector -> validate/sanitize pipeline through that seam with a scripted fake
instead of monkeypatching call_llm, covering: every sanitization action from workstream 1,
the material-violation repair-then-fail-closed path, selector unavailability, and a replay of
the 2026-07-06 production incident (trace 7852fc7fe6909eec06529a124817e571).
"""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _DummyLogger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _DummySpan:
    def set_attribute(self, *args, **kwargs):
        return None


class _DummyTrace:
    @staticmethod
    def get_current_span():
        return _DummySpan()


_MODULE_PATH = Path(__file__).resolve().parents[1] / "agent.py"
_SPEC = importlib.util.spec_from_file_location("core_agent_selector_fake_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(ClientTimeout=lambda **kwargs: None, ClientSession=None, ClientError=RuntimeError),
    "config": types.SimpleNamespace(
        CONFIG=types.SimpleNamespace(proxy_url="http://proxy:3200", workspace="/tmp"),
        get_model=lambda: "gpt-5.4",
        get_temperature=lambda: 0.7,
        get_max_iterations=lambda: 30,
    ),
    "logger": types.SimpleNamespace(
        agent_logger=_DummyLogger(),
        log_agent_step=lambda *args, **kwargs: None,
    ),
    "observability": types.SimpleNamespace(
        REQUEST_ID=ContextVar("request_id", default="-"),
        inject_trace_context=lambda headers=None, request_id=None: dict(headers or {}),
        observe_route_selector_sanitization=lambda *args, **kwargs: None,
        record_span_event=lambda *args, **kwargs: None,
        update_correlation_context=lambda *args, **kwargs: {},
    ),
    "run_meta": types.SimpleNamespace(
        run_meta_get=lambda: None,
        run_meta_update_llm=lambda **kwargs: None,
        run_meta_append_artifact=lambda *args, **kwargs: False,
    ),
    "tools": types.SimpleNamespace(
        execute_tool=lambda *args, **kwargs: None,
        filter_tools_for_session=lambda *args, **kwargs: [],
    ),
    "models": types.SimpleNamespace(ToolContext=object, ToolResult=object),
    "opentelemetry": types.SimpleNamespace(trace=_DummyTrace()),
}
_saved_modules = {name: sys.modules.get(name) for name in _stub_modules}
try:
    sys.modules.update(_stub_modules)
    _SPEC.loader.exec_module(_MODULE)
finally:
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def _llm_response(content: str, *, model: str = "selector-test-model") -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "model": model,
    }


class ScriptedRouteSelectorLLM:
    """A scripted fake for agent.RouteSelectorLLM: returns queued responses in call order and
    records (purpose, messages) for each call so tests can assert on the interaction shape."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[tuple[list[dict], str]] = []

    async def __call__(self, messages: list[dict], purpose: str) -> dict:
        self.calls.append((messages, purpose))
        if not self._responses:
            raise AssertionError(f"ScriptedRouteSelectorLLM exhausted but called again with purpose={purpose}")
        return self._responses.pop(0)


class RouteSelectorFakeTests(unittest.TestCase):
    def _run(self, query: str, fake: ScriptedRouteSelectorLLM):
        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ, {"CORP_DOCS_ROOT": str(Path(docs_tmp))}, clear=False
        ):
            return asyncio.run(_MODULE._select_route_with_llm(query, llm_caller=fake))

    def test_2026_07_06_incident_replay_now_succeeds_with_the_fallback_honored(self):
        # Replays the exact 2026-07-06 selector output (trace 7852fc7fe6909eec06529a124817e571).
        # Workstream 2 fixed the catalog gap directly (corp_kb.company_common and
        # corp_kb.series_description now declare each other as fallbacks), so this fallback is
        # no longer undeclared -- it's honored outright, with zero sanitization needed. Combined
        # with workstream 1 (which would have sanitized it away instead of failing closed even
        # without the catalog fix), this closes the incident from both directions.
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response(
                    json.dumps(
                        {
                            "selected_route_id": "corp_kb.company_common",
                            "tool_args": {"query": "светильники в реестре минпромторга"},
                            "fallback_route_ids": ["corp_kb.series_description"],
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        )

        route_selection, route_hint, _secondary = self._run("светильники в реестре минпромторга", fake)

        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(route_selection["selector"]["sanitization_actions"], [])
        self.assertEqual(route_hint["selector_fallback_route_ids"], ["corp_kb.series_description"])

    def test_unknown_tool_arg_sanitized_without_repair_round_trip(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response(
                    json.dumps(
                        {
                            "selected_route_id": "corp_kb.company_common",
                            "tool_args": {"query": "сертификаты", "unexpected_field": "drop me"},
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 1)
        self.assertNotIn("unexpected_field", route_hint["tool_args"])
        self.assertIn("dropped_unknown_tool_arg", route_selection["selector"]["sanitization_actions"])

    def test_family_mismatch_sanitized_by_deriving_from_route(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response(
                    json.dumps(
                        {
                            "selected_family_id": "portfolio",
                            "selected_route_id": "corp_kb.company_common",
                            "tool_args": {"query": "контакты"},
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        )

        route_selection, route_hint, _secondary = self._run("контакты компании", fake)

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(route_selection["selected_family_id"], "company_info")
        self.assertIn("derived_family_from_route", route_selection["selector"]["sanitization_actions"])

    def test_material_violation_repairs_once_then_succeeds(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response("not valid json"),
                _llm_response(
                    json.dumps(
                        {"selected_route_id": "corp_kb.company_common", "tool_args": {"query": "сертификаты"}},
                        ensure_ascii=False,
                    )
                ),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][1], "route_selector")
        self.assertEqual(fake.calls[1][1], "route_selector_repair")
        self.assertEqual(route_selection["selector"]["repair_status"], "succeeded")
        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")

    def test_material_violation_fails_closed_after_one_repair_attempt(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response("not valid json"),
                _llm_response("still not valid json"),
            ]
        )

        with self.assertRaises(RuntimeError) as ctx:
            self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 2)
        self.assertIn("invalid_json", str(ctx.exception))

    def test_selector_llm_unavailable_raises_for_caller_to_fail_closed(self):
        fake = ScriptedRouteSelectorLLM([{"error": "upstream unavailable"}])

        with self.assertRaises(RuntimeError):
            self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
