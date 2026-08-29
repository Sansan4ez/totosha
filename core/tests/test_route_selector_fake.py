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

    def add_event(self, *args, **kwargs):
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
        observe_route_selector_prompt_size=lambda *args, **kwargs: None,
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


def _choice(
    route_id: str,
    *,
    family_id: str = "",
    fallback_route_ids: list[str] | None = None,
    confidence: str = "",
    reason: str | None = None,
) -> dict:
    payload: dict = {"selected_route_id": route_id}
    if family_id:
        payload["selected_family_id"] = family_id
    if fallback_route_ids:
        payload["fallback_route_ids"] = fallback_route_ids
    if confidence:
        payload["confidence"] = confidence
    if reason is not None:
        payload["reason"] = reason
    return _llm_response(json.dumps(payload, ensure_ascii=False))


def _arguments(tool_args: dict) -> dict:
    return _llm_response(json.dumps(tool_args, ensure_ascii=False))


class RouteSelectorFakeTests(unittest.TestCase):
    def _run(self, query: str, fake: ScriptedRouteSelectorLLM):
        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp)), "DOC_REPO_ROOT": str(Path(docs_tmp))},
            clear=False,
        ):
            return asyncio.run(_MODULE._select_route_with_llm(query, llm_caller=fake))

    def test_2026_07_06_incident_replay_now_succeeds_with_the_fallback_honored(self):
        # Replays the 2026-07-06 selector choice (trace 7852fc7fe6909eec06529a124817e571) in the
        # RFC-029 two-call shape. Workstream 2 of RFC-028 fixed the catalog gap directly
        # (corp_kb.company_common and corp_kb.series_description now declare each other as
        # fallbacks), so this fallback is honored outright, with zero sanitization needed.
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common", fallback_route_ids=["corp_kb.series_description"]),
                _arguments({"query": "светильники в реестре минпромторга"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("светильники в реестре минпромторга", fake)

        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")
        self.assertEqual([purpose for _, purpose in fake.calls], ["route_selector", "route_argument_builder"])
        self.assertEqual(route_selection["selector"]["sanitization_actions"], [])
        self.assertEqual(route_hint["selector_fallback_route_ids"], ["corp_kb.series_description"])
        self.assertEqual(route_selection["selector"]["argument_builder_status"], "valid")

    def test_call_a_payload_has_no_keywords_patterns_or_argument_schema(self):
        # RFC-029 workstream 1 regression lock: the classification card is keyword-free and
        # schema-free for every route, so topical signal can't overpower argument shape and
        # Call A can't invent argument values.
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common"),
                _arguments({"query": "сертификаты"}),
            ]
        )

        self._run("какие есть сертификаты?", fake)

        call_a_messages, purpose = fake.calls[0]
        self.assertEqual(purpose, "route_selector")
        call_a_text = "\n".join(str(message.get("content") or "") for message in call_a_messages)
        self.assertNotIn('"keywords"', call_a_text)
        self.assertNotIn('"patterns"', call_a_text)
        self.assertNotIn('"argument_schema"', call_a_text)
        self.assertNotIn('"argument_hints"', call_a_text)
        self.assertIn('"when_to_use"', call_a_text)

        call_b_messages, purpose_b = fake.calls[1]
        self.assertEqual(purpose_b, "route_argument_builder")
        call_b_text = "\n".join(str(message.get("content") or "") for message in call_b_messages)
        # Call B sees only the selected route's schema, not any other route's card.
        self.assertIn('"argument_schema"', call_b_text)
        self.assertIn("corp_kb.company_common", call_b_text)
        self.assertNotIn("corp_db.catalog_lookup", call_b_text)
        self.assertNotIn('"keywords"', call_b_text)

    def test_unknown_tool_arg_sanitized_without_repair_round_trip(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common"),
                _arguments({"query": "сертификаты", "unexpected_field": "drop me"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 2)
        self.assertNotIn("unexpected_field", route_hint["tool_args"])
        self.assertIn("dropped_unknown_tool_arg", route_selection["selector"]["sanitization_actions"])

    def test_family_mismatch_sanitized_by_deriving_from_route(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common", family_id="portfolio"),
                _arguments({"query": "контакты"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("контакты компании", fake)

        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(route_selection["selected_family_id"], "company_info")
        self.assertIn("derived_family_from_route", route_selection["selector"]["sanitization_actions"])

    def test_material_violation_repairs_once_then_succeeds(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response("not valid json"),
                _choice(
                    "corp_kb.company_common",
                    confidence="high",
                    reason="repaired certification route",
                ),
                _arguments({"query": "сертификаты"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(
            [purpose for _, purpose in fake.calls],
            ["route_selector", "route_selector_repair", "route_argument_builder"],
        )
        self.assertEqual(route_selection["selector"]["repair_status"], "succeeded")
        self.assertEqual(route_selection["selector"]["confidence"], "high")
        self.assertEqual(route_selection["selector"]["reason"], "repaired certification route")
        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")

    def test_repair_metadata_replaces_rejected_choice_metadata(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _llm_response(json.dumps({"confidence": "low", "reason": "rejected route"})),
                _choice("corp_kb.company_common", confidence="high", reason="repaired route"),
                _arguments({"query": "сертификаты"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(route_selection["selector"]["validation_error_code"], "missing_required")
        self.assertEqual(route_selection["selector"]["confidence"], "high")
        self.assertEqual(route_selection["selector"]["reason"], "repaired route")
        self.assertEqual(route_hint["selection_reason"], "llm_selector: repaired route")
        self.assertNotIn("rejected route", route_hint["selection_reason"])

    def test_valid_choice_metadata_is_preserved_without_repair(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common", confidence="medium", reason="direct route"),
                _arguments({"query": "сертификаты"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(route_selection["selector"]["repair_status"], "not_needed")
        self.assertEqual(route_selection["selector"]["confidence"], "medium")
        self.assertEqual(route_selection["selector"]["reason"], "direct route")
        self.assertEqual(route_hint["selection_reason"], "llm_selector: direct route")

    def test_missing_reason_uses_plain_llm_selector_reason(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common", confidence="medium"),
                _arguments({"query": "сертификаты"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(route_selection["selector"]["reason"], "")
        self.assertEqual(route_hint["selection_reason"], "llm_selector")

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

    def test_argument_builder_violation_repairs_locally_without_rerunning_call_a(self):
        # RFC-029: a Call B schema violation is Call-B-local repair-or-fail-closed; the route
        # choice from Call A is never re-selected because of it.
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common"),
                _llm_response("not a json object"),
                _arguments({"query": "сертификаты"}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("какие есть сертификаты?", fake)

        self.assertEqual(
            [purpose for _, purpose in fake.calls],
            ["route_selector", "route_argument_builder", "route_argument_builder_repair"],
        )
        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")
        self.assertEqual(route_selection["selector"]["argument_builder_status"], "repaired")
        self.assertEqual(route_selection["selector"]["argument_builder_repair_status"], "succeeded")
        self.assertEqual(route_hint["tool_args"]["query"], "сертификаты")

    def test_argument_builder_fails_closed_after_one_repair_attempt(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_kb.company_common"),
                _llm_response("not a json object"),
                _llm_response("still not a json object"),
            ]
        )

        with self.assertRaises(RuntimeError) as ctx:
            self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 3)
        self.assertIn("route argument builder output rejected", str(ctx.exception))

    def test_2026_08_27_incident_matrix_uses_route_card_contracts(self):
        cases = (
            (
                "2ex световой поток не менее 11540 Лм",
                "corp_db.lamp_filters",
                {"flux_lm_min": 11540, "series": "LAD LED R500 2Ex"},
            ),
            (
                "2 ex световой поток не менее 11540 Лм",
                "corp_db.lamp_filters",
                {"flux_lm_min": 11540, "series": "LAD LED R500 2Ex"},
            ),
            (
                "LAD LED R500 2Ex, поток от 11540 лм",
                "corp_db.lamp_filters",
                {"flux_lm_min": 11540, "series": "LAD LED R500 2Ex"},
            ),
            (
                "LAD LED R320 Ex, поток от 11540 лм",
                "corp_db.lamp_filters",
                {"flux_lm_min": 11540, "series": "LAD LED R320 Ex"},
            ),
            (
                "взрывозащищенный светильник, поток от 11540 лм",
                "corp_db.lamp_filters",
                {"flux_lm_min": 11540, "explosion_protected": True},
            ),
            (
                "LAD LED R320-2-10G-230AC-50K Ex",
                "corp_db.catalog_lookup",
                {"name": "LAD LED R320-2-10G-230AC-50K Ex"},
            ),
        )
        for query, expected_route_id, expected_args in cases:
            with self.subTest(query=query):
                fake = ScriptedRouteSelectorLLM(
                    [
                        _choice(expected_route_id),
                        _arguments(expected_args),
                    ]
                )

                route_selection, route_hint, _secondary = self._run(query, fake)

                self.assertEqual(len(fake.calls), 2)
                self.assertEqual(route_hint["route_id"], expected_route_id)
                if expected_route_id == "corp_db.catalog_lookup":
                    expected_execution_args = {**expected_args, "kind": "lamp_exact"}
                else:
                    expected_execution_args = {**expected_args, "kind": "lamp_filters", "fuzzy": True}
                self.assertEqual(route_hint["tool_args"], expected_execution_args)
                self.assertEqual(route_selection["selector"]["argument_builder_status"], "valid")

    def test_lamp_filter_explicit_alias_conflict_repairs_locally(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_db.lamp_filters"),
                _arguments({"series": "LAD LED R320 Ex", "flux_lm_min": 11540}),
                _arguments({"series": "LAD LED R500 2Ex", "flux_lm_min": 11540}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("2Ex, поток от 11540 лм", fake)

        self.assertEqual(
            [purpose for _, purpose in fake.calls],
            ["route_selector", "route_argument_builder", "route_argument_builder_repair"],
        )
        self.assertEqual(route_hint["tool_args"]["series"], "LAD LED R500 2Ex")
        self.assertEqual(route_selection["selector"]["validation_error_code"], "series_alias_conflict")
        self.assertEqual(route_selection["selector"]["argument_builder_status"], "repaired")
        repair_text = "\n".join(str(message.get("content") or "") for message in fake.calls[2][0])
        self.assertIn("LAD LED R500 2Ex", repair_text)

    def test_lamp_filter_alias_conflict_fails_closed_when_repair_stays_wrong(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_db.lamp_filters"),
                _arguments({"series": "LAD LED R320 Ex"}),
                _arguments({"series": "LAD LED R320 Ex"}),
            ]
        )

        with self.assertRaises(RuntimeError) as ctx:
            self._run("нужны модели 2Ex", fake)

        self.assertEqual(len(fake.calls), 3)
        self.assertIn("series_alias_conflict", str(ctx.exception))

    def test_lamp_filter_bare_ex_does_not_become_specific_series(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_db.lamp_filters"),
                _arguments({"flux_lm_min": 11540}),
            ]
        )

        _route_selection, route_hint, _secondary = self._run("Ex, поток от 11540 лм", fake)

        self.assertNotIn("series", route_hint["tool_args"])
        self.assertEqual(route_hint["tool_args"]["flux_lm_min"], 11540)

    def test_lamp_filter_bare_ex_rejects_invented_specific_series(self):
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_db.lamp_filters"),
                _arguments({"series": "LAD LED R500 2Ex"}),
                _arguments({"explosion_protected": True}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("нужен светильник Ex", fake)

        self.assertNotIn("series", route_hint["tool_args"])
        self.assertEqual(route_selection["selector"]["argument_builder_status"], "repaired")

    def test_document_route_accepts_bounded_names_array(self):
        # RFC-029 workstream 3: certificate lookups carry names: array<string> (1..5 items).
        for names in (
            ["NL Nova"],
            ["NL Nova", "LAD LED R500", "LAD LED R320"],
            ["NL Nova", "LAD LED R500", "LAD LED R320", "LAD LED R700", "NL VEGA"],
        ):
            with self.subTest(names=names):
                fake = ScriptedRouteSelectorLLM(
                    [
                        _choice("corp_db.certificate_by_lamp_name"),
                        _arguments({"names": names}),
                    ]
                )
                _route_selection, route_hint, _secondary = self._run(
                    "нужны сертификаты на " + ", ".join(names), fake
                )
                self.assertEqual(route_hint["route_id"], "corp_db.certificate_by_lamp_name")
                self.assertEqual(route_hint["tool_args"]["names"], names)
                self.assertEqual(route_hint["tool_args"]["document_type"], "certificate")

    def test_document_route_rejects_more_than_five_names(self):
        too_many = [f"MODEL-{index}" for index in range(6)]
        fake = ScriptedRouteSelectorLLM(
            [
                _choice("corp_db.certificate_by_lamp_name"),
                _arguments({"names": too_many}),
                _arguments({"names": too_many[:5]}),
            ]
        )

        route_selection, route_hint, _secondary = self._run("сертификаты на шесть моделей", fake)

        # maxItems violation is repairable Call-B-locally; the repaired output is accepted.
        self.assertEqual(route_selection["selector"]["argument_builder_status"], "repaired")
        self.assertEqual(route_hint["tool_args"]["names"], too_many[:5])

    def test_selector_llm_unavailable_raises_for_caller_to_fail_closed(self):
        fake = ScriptedRouteSelectorLLM([{"error": "upstream unavailable"}])

        with self.assertRaises(RuntimeError):
            self._run("какие есть сертификаты?", fake)

        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
