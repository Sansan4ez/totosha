import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


@dataclass
class _ToolContext:
    cwd: str
    session_id: str = ""
    user_id: int = 0
    chat_id: int = 0
    chat_type: str = "private"
    source: str = "bot"
    is_admin: bool = False


@dataclass
class _ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    metadata: dict | None = None


_MODULE_PATH = Path(__file__).resolve().parents[1] / "agent.py"
_SPEC = importlib.util.spec_from_file_location("core_agent_guardrail_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(ClientTimeout=lambda **kwargs: None, ClientSession=None, ClientError=RuntimeError),
    "config": types.SimpleNamespace(
        CONFIG=types.SimpleNamespace(
            proxy_url="http://proxy:3200",
            workspace="/tmp",
            max_context_messages=12,
            max_history=12,
            max_tool_output=4000,
            max_blocked_commands=3,
        ),
        get_model=lambda: "gpt-5.4",
        get_temperature=lambda: 0.7,
        get_max_iterations=lambda: 6,
    ),
    "logger": types.SimpleNamespace(
        agent_logger=_DummyLogger(),
        log_agent_step=lambda *args, **kwargs: None,
    ),
    "observability": types.SimpleNamespace(
        REQUEST_ID=ContextVar("request_id", default="-"),
        inject_trace_context=lambda *args, **kwargs: {},
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
        filter_tools_for_session=lambda tools, *args, **kwargs: tools,
    ),
    "models": types.SimpleNamespace(ToolContext=_ToolContext, ToolResult=_ToolResult),
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


class RoutingGuardrailTests(unittest.TestCase):
    def test_company_fact_helpers_classify_subtypes_and_queries(self):
        self.assertEqual(_MODULE._company_fact_intent_type("Подскажи контакты компании."), "contacts")
        self.assertEqual(_MODULE._company_fact_intent_type("Расскажи о компании"), "about_company")
        self.assertEqual(_MODULE._company_fact_intent_type("Какой официальный сайт компании?"), "website")
        self.assertIn("lad@ladled.ru", _MODULE._expand_company_fact_query("Подскажи контакты компании.").lower())
        self.assertIn("общая информация", _MODULE._expand_company_fact_query("Расскажи о компании").lower())
        rewritten = _MODULE._rewrite_company_fact_search_args(
            {"power_w_min": 0, "voltage_kind": "AC", "explosion_protected": False, "limit": 5},
            "Подскажи контакты компании.",
        )
        self.assertEqual(rewritten["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(rewritten["source_files"], ["common_information_about_company.md"])
        self.assertEqual(rewritten["topic_facets"], ["contacts"])
        self.assertNotIn("power_w_min", rewritten)
        self.assertNotIn("voltage_kind", rewritten)
        self.assertNotIn("explosion_protected", rewritten)
        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp))},
            clear=False,
        ):
            voice_selection = _MODULE.select_route(
                _MODULE._routing_query_text(
                    "[От: @bench (42)]\n[Голосовое сообщение, распознанный текст:]\nЧто такое Luxnet?"
                )
            )
        self.assertEqual(voice_selection["selected"]["route_id"], "corp_kb.luxnet")
        weak_about_payload = {
            "status": "success",
            "results": [
                {
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "Дополнительные испытания в независимых аккредитованных лабораториях",
                    "preview": "В рамках реализации долгосрочных проектов по разработке и поставке светотехнического оборудования...",
                }
            ],
        }
        self.assertFalse(_MODULE._company_fact_payload_is_relevant(weak_about_payload, "Расскажи о компании"))
        ranked_about_payload = {
            "status": "success",
            "results": [
                {
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "Наш профиль",
                    "preview": "Наш профиль — промышленное освещение и работа в тяжёлых условиях эксплуатации.",
                },
                {
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "О компании",
                    "preview": "Компания ЛАДзавод светотехники занимается разработкой и производством промышленного светотехнического оборудования.",
                },
            ],
        }
        preferred = _MODULE._preferred_company_fact_texts(ranked_about_payload, "about_company")
        self.assertTrue(preferred)
        self.assertIn("Компания ЛАДзавод светотехники занимается", preferred[0])

    def test_generic_certification_and_quality_questions_are_company_common_facets(self):
        cert_query = "какие есть сертификаты?"
        quality_query = "Какие используются комплектующие?"

        self.assertFalse(_MODULE._is_document_lookup_intent(cert_query))
        self.assertEqual(_MODULE._company_fact_intent_type(cert_query), "certification")
        self.assertEqual(_MODULE._company_common_topic_facets(cert_query), ["certification"])
        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp))},
            clear=False,
        ):
            cert_selection = _MODULE.select_route(cert_query)
        cert_route = cert_selection["selected"]
        self.assertEqual(cert_route["route_id"], "corp_kb.company_common")

        self.assertFalse(_MODULE._is_document_lookup_intent(quality_query))
        self.assertEqual(_MODULE._company_fact_intent_type(quality_query), "quality")
        self.assertEqual(_MODULE._company_common_topic_facets(quality_query), ["quality"])
        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp))},
            clear=False,
        ):
            quality_selection = _MODULE.select_route(quality_query)
        quality_route = quality_selection["selected"]
        self.assertEqual(quality_route["route_id"], "corp_kb.company_common")

    def test_broad_series_question_uses_series_description_leaf_route(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какие у вас есть серии светильников?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Доступные серии освещения",
                        "preview": "Серии: LAD LED R500, LAD LED R700, LAD LED LINE, NL Nova и NL VEGA.",
                        "metadata": {"source_file": "common_information_about_company.md"},
                    }
                ],
            },
            corp_db_args={"kind": "hybrid_search", "query": "какие серии светильников есть"},
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "query": "какие серии светильников есть"}),
                self._final_response("Есть серии LAD LED R500, LAD LED R700, LAD LED LINE, NL Nova и NL VEGA."),
            ],
        )

        self.assertIn("LAD LED R500", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[1]["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(exec_mock.await_args_list[0].args[1]["topic_facets"], ["series"])
        self.assertEqual(meta["retrieval_route_id"], "corp_kb.company_common")
        self.assertEqual(meta["retrieval_route_family"], "corp_kb.company_common")
        self.assertEqual(meta["retrieval_business_family_id"], "company_info")
        self.assertEqual(meta["retrieval_leaf_route_id"], "series_description")
        self.assertEqual(meta["retrieval_route_stage"], "stage2_specialized")
        self.assertEqual(meta["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")

    def test_portfolio_project_queries_use_portfolio_fallback_args(self):
        self.assertTrue(_MODULE._is_portfolio_lookup_intent("Расскажи про терминально-логистический центр Белый Раст"))
        self.assertFalse(_MODULE._is_portfolio_lookup_intent("Подбери освещение для спортивного объекта"))

        name, args, route_hint = _MODULE._portfolio_lookup_fallback_call(
            "Расскажи про терминально-логистический центр Белый Раст"
        )
        self.assertEqual(name, "corp_db_search")
        self.assertEqual(route_hint["route_id"], "corp_db.portfolio_lookup")
        self.assertEqual(args["kind"], "hybrid_search")
        self.assertEqual(args["profile"], "entity_resolver")
        self.assertEqual(args["entity_types"], ["portfolio", "sphere"])

        _, rzd_args, rzd_route_hint = _MODULE._portfolio_lookup_fallback_call("Какие объекты были реализованы для РЖД?")
        self.assertEqual(rzd_route_hint["route_id"], "corp_db.portfolio_by_sphere")
        self.assertEqual(rzd_args["kind"], "portfolio_by_sphere")
        self.assertEqual(rzd_args["sphere"], "РЖД")

        _, industrial_args, industrial_route_hint = _MODULE._portfolio_lookup_fallback_call(
            "Какие реализованные объекты есть для промышленных объектов?"
        )
        self.assertEqual(industrial_route_hint["route_id"], "corp_db.portfolio_by_sphere")
        self.assertEqual(industrial_args["kind"], "portfolio_by_sphere")
        self.assertIn("промышленных объектов", industrial_args["sphere"].lower())

        fallback = _MODULE._build_deterministic_fallback_call(
            "Расскажи про Белый Раст",
            {
                "route_id": "corp_kb.company_common",
                "tool_name": "corp_db_search",
                "tool_args": {"kind": "hybrid_search", "knowledge_route_id": "corp_kb.company_common"},
            },
            {"intent": "company_fact", "knowledge_route_id": "corp_kb.company_common"},
        )
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback[1]["profile"], "entity_resolver")

    def test_portfolio_entity_resolver_is_intermediate_evidence(self):
        tool_result = _ToolResult(
            True,
            output=json.dumps(
                {
                    "status": "success",
                    "results": [{"entity_type": "portfolio", "title": "Освещение терминала"}],
                },
                ensure_ascii=False,
            ),
            metadata={},
        )
        status = _MODULE._route_evidence_status(
            "corp_db_search",
            {
                "kind": "hybrid_search",
                "profile": "entity_resolver",
                "entity_types": ["portfolio", "sphere"],
                "query": "какие объекты были реализованы для ржд",
            },
            tool_result,
            "какие объекты были реализованы для ржд",
            {},
        )
        self.assertEqual(status, "intermediate")

    def test_sphere_context_scopes_follow_up_and_clears_on_unrelated_query(self):
        session = types.SimpleNamespace(
            resolved_sphere_context={
                "sphere_id": 3,
                "sphere_name": "Складские помещения",
                "category_names": ["LAD LED R500", "LAD LED LINE-OZ"],
                "source_turn_id": 1,
                "confirmed": True,
            },
            turn_index=1,
        )
        scoped = _MODULE._prepare_selector_sphere_context(session, "Покажи модели из этой категории", 2)
        self.assertIsNotNone(scoped)
        self.assertEqual(scoped["sphere_name"], "Складские помещения")

        unrelated = _MODULE._prepare_selector_sphere_context(session, "Расскажи о компании", 3)
        self.assertIsNone(unrelated)
        self.assertIsNone(getattr(session, "resolved_sphere_context", None))

        session = types.SimpleNamespace(
            resolved_sphere_context={
                "sphere_id": 3,
                "sphere_name": "Складские помещения",
                "category_names": ["LAD LED R500", "LAD LED LINE-OZ"],
                "source_turn_id": 1,
                "confirmed": True,
            },
            turn_index=1,
        )
        sku_query = _MODULE._prepare_selector_sphere_context(session, "Найди SKU NL VEGA", 2)
        self.assertIsNone(sku_query)
        self.assertIsNone(getattr(session, "resolved_sphere_context", None))

    def test_resolved_sphere_context_captures_sphere_id(self):
        tool_result = _ToolResult(
            True,
            output=json.dumps(
                {
                    "status": "success",
                    "kind": "portfolio_by_sphere",
                    "results": [{"sphere_id": 5, "sphere_name": "РЖД", "name": "Освещение инфраструктуры РЖД"}],
                },
                ensure_ascii=False,
            ),
            metadata={},
        )
        context = _MODULE._resolved_sphere_context_from_tool(
            tool_name="corp_db_search",
            tool_args={"kind": "portfolio_by_sphere", "sphere": "РЖД"},
            tool_result=tool_result,
            route_hint={"route_id": "corp_db.portfolio_by_sphere"},
            turn_id=4,
        )
        self.assertIsNotNone(context)
        self.assertEqual(context["sphere_id"], 5)
        self.assertEqual(context["sphere_name"], "РЖД")

    def test_portfolio_entity_payload_renders_projects(self):
        output = json.dumps(
            {
                "status": "success",
                "results": [
                    {
                        "entity_type": "portfolio",
                        "title": "Высокомощные светильники для ТЛЦ Белый Раст",
                        "metadata": {"sphere_name": "логистический центр", "url": "https://example.test/project"},
                    }
                ],
            },
            ensure_ascii=False,
        )
        rendered = _MODULE._render_deterministic_tool_output(
            "corp_db_search",
            {"kind": "hybrid_search", "profile": "entity_resolver", "entity_types": ["portfolio", "sphere"]},
            output,
            "Белый Раст",
        )
        self.assertIn("Белый Раст", rendered)
        self.assertIn("https://example.test/project", rendered)

    def test_llm_route_selector_validates_route_and_tool_args(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_route_id": "corp_kb.company_common",
                                "confidence": "high",
                                "reason": "company certification question",
                                "tool_args": {
                                    "query": "сертификаты декларации CE EAC",
                                    "topic_facets": ["certification"],
                                },
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }

        async def fake_call_llm(messages, tool_definitions, model_override="", purpose="agent_loop"):
            self.assertEqual(tool_definitions, [])
            self.assertIn("corp_kb.company_common", messages[-1]["content"])
            self.assertEqual(purpose, "route_selector")
            return selector_response

        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp))},
            clear=False,
        ), patch.object(_MODULE, "call_llm", AsyncMock(side_effect=fake_call_llm)):
            route_selection, route_hint, secondary = asyncio.run(
                _MODULE._select_route_with_llm("какие есть сертификаты?")
            )

        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")
        self.assertEqual(route_hint["tool_args"]["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(route_hint["tool_args"]["topic_facets"], ["certification"])
        self.assertEqual(route_hint["selector_status"], "valid")
        self.assertIn("query", route_hint["validated_arg_keys"])
        self.assertIn("topic_facets", route_hint["validated_arg_keys"])
        self.assertGreater(route_hint["selector_latency_ms"], 0)
        self.assertEqual(route_selection["selector"]["status"], "valid")
        self.assertEqual(route_selection["selector"]["confidence"], "high")
        self.assertEqual(route_selection["selector"]["repair_status"], "not_needed")
        self.assertIn("query", route_selection["selector"]["validated_arg_keys"])
        self.assertIn("catalog_version", route_selection)
        self.assertIn("schema_version", route_selection)
        self.assertEqual(route_selection["selected_family_id"], "company_info")
        self.assertIn("company_info", route_selection["selector"]["candidate_family_ids"])
        self.assertIn("corp_kb.company_common", route_selection["candidate_route_ids"])
        self.assertTrue(secondary)

    def test_application_route_selector_schema_stays_within_bounded_args(self):
        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp))},
            clear=False,
        ):
            payload = _MODULE.build_route_selector_payload("Что порекомендуешь для РЖД?")

        route = next(
            item for item in _MODULE.selector_payload_leaf_routes(payload) if item["route_id"] == "corp_db.application_recommendation"
        )
        properties = route["argument_schema"]["properties"]

        self.assertEqual(
            set(properties),
            {"query", "limit_categories", "limit_lamps", "limit_portfolio"},
        )
        self.assertEqual(route["argument_schema"]["required"], ["query"])

    def test_document_subtype_selector_payload_stays_inside_documents_family(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                selection = _MODULE.select_route("Покажи паспорт на NL Nova")
                payload = _MODULE.build_route_selector_payload("Покажи паспорт на NL Nova", limit=8)

        route = next(
            item for item in _MODULE.selector_payload_leaf_routes(payload) if item["route_id"] == "corp_db.passport_by_lamp_name"
        )
        self.assertEqual(selection["selected"]["route_id"], "corp_db.passport_by_lamp_name")
        self.assertEqual(selection["selected_family_id"], "documents")
        self.assertEqual(payload["candidate_route_ids"][0], "corp_db.passport_by_lamp_name")
        self.assertEqual(route["locked_args"]["document_type"], "passport")
        self.assertNotIn("document_type", route["argument_schema"]["properties"])
        self.assertEqual(
            route["fallback_policy"]["same_family_route_ids"],
            ["corp_db.documents_by_lamp_name"],
        )
        self.assertEqual(route["fallback_policy"]["cross_family_route_ids"], [])

    def test_code_lookup_selector_payload_stays_inside_codes_family(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                selection = _MODULE.select_route("Какой ETM-код у NL Nova?")
                payload = _MODULE.build_route_selector_payload("Какой ETM-код у NL Nova?", limit=8)

        route = next(
            item for item in _MODULE.selector_payload_leaf_routes(payload) if item["route_id"] == "corp_db.sku_codes_lookup"
        )
        self.assertEqual(selection["selected"]["route_id"], "corp_db.sku_codes_lookup")
        self.assertEqual(selection["selected_family_id"], "codes_and_sku")
        self.assertEqual(payload["candidate_route_ids"][0], "corp_db.sku_codes_lookup")
        self.assertEqual(
            route["argument_schema"]["properties"]["lookup_direction"]["enum"],
            ["by_name", "by_code"],
        )
        self.assertEqual(
            route["argument_schema"]["properties"]["code_system"]["enum"],
            ["etm", "oracl", "sku", "article", "catalog_identifier", "mixed"],
        )
        self.assertEqual(
            route["fallback_policy"]["same_family_route_ids"],
            ["corp_db.sku_lookup"],
        )
        self.assertEqual(
            route["fallback_policy"]["cross_family_route_ids"],
            ["corp_db.catalog_lookup"],
        )

    def test_llm_route_selector_repairs_invalid_selector_args_once(self):
        invalid_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_route_id": "corp_kb.company_common",
                                "tool_args": {"query": "сертификаты", "undeclared": "drop me"},
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        repaired_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_route_id": "corp_kb.company_common",
                                "confidence": "medium",
                                "reason": "repaired args",
                                "tool_args": {
                                    "query": "сертификаты декларации",
                                    "topic_facets": ["certification"],
                                },
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": "selector-test-model",
        }

        with tempfile.TemporaryDirectory() as docs_tmp, patch.dict(
            os.environ,
            {"CORP_DOCS_ROOT": str(Path(docs_tmp))},
            clear=False,
        ), patch.object(_MODULE, "call_llm", AsyncMock(side_effect=[invalid_response, repaired_response])):
            route_selection, route_hint, _secondary = asyncio.run(
                _MODULE._select_route_with_llm("какие есть сертификаты?")
            )

        self.assertEqual(route_hint["route_id"], "corp_kb.company_common")
        self.assertEqual(route_hint["tool_args"]["topic_facets"], ["certification"])
        self.assertEqual(route_selection["selector"]["repair_status"], "succeeded")
        self.assertTrue(route_selection["selector"]["repair_attempted"])
        self.assertEqual(route_selection["selector"]["validation_error_code"], "invalid_tool_args")
        self.assertIn("undeclared", route_selection["selector"]["validation_error"])
        self.assertEqual(route_selection["selector"]["model"], "selector-test-model")

    def test_route_selector_llm_outage_returns_temporary_unavailable(self):
        response, exec_mock, meta = self._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [{"heading": "Сертификация", "preview": "Сертификаты и декларации соответствия."}],
            },
            llm_responses_override=[{"error": "selector upstream unavailable"}],
            route_selector_enabled=True,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 0)
        self.assertEqual(meta["route_selector_status"], "unavailable")
        self.assertEqual(meta["retrieval_evidence_status"], "error")
        self.assertEqual(meta["retrieval_close_reason"], "route_selector_unavailable")
        self.assertIn("selector upstream unavailable", meta["route_selector_validation_error"])

    def test_selector_disabled_runtime_fails_closed_without_tool_execution(self):
        response, exec_mock, meta = self._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [{"heading": "Сертификация", "preview": "Сертификаты и декларации соответствия."}],
            },
            route_selector_enabled=False,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 0)
        self.assertEqual(meta["route_selector_status"], "disabled")
        self.assertEqual(meta["retrieval_evidence_status"], "error")
        self.assertEqual(meta["retrieval_close_reason"], "route_selector_disabled")
        self.assertIn("runtime fail-closed", meta["route_selector_validation_error"])

    def test_route_selector_messages_use_compact_payload_under_context_budget(self):
        with tempfile.TemporaryDirectory() as repo_tmp, tempfile.TemporaryDirectory() as docs_tmp:
            with patch.dict(
                os.environ,
                {"DOC_REPO_ROOT": repo_tmp, "CORP_DOCS_ROOT": docs_tmp},
                clear=False,
            ):
                payload = _MODULE.build_route_selector_payload("Какие у вас есть серии светильников?")
                messages = _MODULE._build_route_selector_messages(payload)

        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("corp_kb.series_description", messages[1]["content"])
        self.assertIn("selected_family_id", messages[0]["content"])
        self.assertIn("company_info", messages[1]["content"])
        self.assertIn("corp_kb.company_common", messages[1]["content"])
        self.assertNotIn("\"candidate_route_ids\"", messages[1]["content"])
        self.assertNotIn("executor_args_template", messages[1]["content"])
        self.assertNotIn("execution_argument_schema", messages[1]["content"])
        self.assertNotIn("evidence_policy", messages[1]["content"])
        self.assertLess(sum(len(message.get("content") or "") for message in messages), 40000)

    def test_selector_executes_scoped_route_and_finalizes_without_extra_tools(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_route_id": "corp_kb.company_common",
                                "confidence": "high",
                                "reason": "company quality question",
                                "tool_args": {
                                    "query": "качество комплектующих CREE LED",
                                    "topic_facets": ["quality"],
                                },
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        finalizer_response = self._final_response("Используются проверенные комплектующие, включая CREE LED.")
        response, exec_mock, meta = self._run_flow(
            user_message="Какие используются комплектующие?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Качество комплектующих",
                        "preview": "Используются проверенные комплектующие, включая CREE LED.",
                    }
                ],
            },
            llm_responses_override=[selector_response, finalizer_response],
            route_selector_enabled=True,
        )

        self.assertIn("CREE LED", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        args = exec_mock.await_args_list[0].args[1]
        self.assertEqual(args["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(args["topic_facets"], ["quality"])
        self.assertEqual(meta["retrieval_phase"], "closed")
        self.assertEqual(meta["retrieval_evidence_status"], "sufficient")
        self.assertEqual(meta["retrieval_close_reason"], "route_selector_payload_sufficient")
        self.assertEqual(meta["route_selector_status"], "valid")
        self.assertEqual(meta["route_selector_confidence"], "high")
        self.assertIn("company quality question", meta["route_selector_reason"])
        self.assertGreater(meta["route_selector_latency_ms"], 0)
        self.assertIn("query", meta["retrieval_validated_arg_keys"])
        self.assertIn("topic_facets", meta["retrieval_validated_arg_keys"])
        self.assertEqual(meta["retrieval_validation_status"], "ok")
        self.assertTrue(meta["routing_catalog_version"])
        self.assertGreaterEqual(meta["routing_schema_version"], 1)

    def test_selector_finalizer_llm_outage_returns_temporary_unavailable(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_route_id": "corp_kb.company_common",
                                "confidence": "high",
                                "reason": "company certification question",
                                "tool_args": {
                                    "query": "сертификаты декларации",
                                    "topic_facets": ["certification"],
                                },
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        response, exec_mock, meta = self._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "heading": "Сертификация",
                        "preview": "Сертификаты и декларации соответствия.",
                    }
                ],
            },
            llm_responses_override=[selector_response, {"error": "finalizer upstream unavailable"}],
            route_selector_enabled=True,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["retrieval_evidence_status"], "sufficient")
        self.assertEqual(meta["retrieval_close_reason"], "finalizer_unavailable")
        self.assertEqual(meta["finalizer_mode"], "unavailable")

    def test_route_selector_documents_fallback_stays_inside_documents_family(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_family_id": "documents",
                                "selected_route_id": "corp_db.passport_by_lamp_name",
                                "confidence": "high",
                                "reason": "passport request by lamp",
                                "tool_args": {"name": "NL Nova"},
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        response, exec_mock, meta = self._run_flow(
            user_message="Покажи паспорт на NL Nova",
            corp_db_payloads=[
                {"status": "empty", "kind": "lamp_exact", "results": []},
                {
                    "status": "success",
                    "kind": "lamp_exact",
                    "results": [{"name": "NL Nova", "document_title": "Паспорт NL Nova"}],
                },
            ],
            corp_db_payload={"status": "empty", "kind": "lamp_exact", "results": []},
            llm_responses_override=[
                selector_response,
                self._final_response("Нашёл документы для NL Nova, включая паспорт."),
            ],
            route_selector_enabled=True,
        )

        self.assertIn("NL Nova", response)
        self.assertEqual(exec_mock.await_count, 2)
        first_args = exec_mock.await_args_list[0].args[1]
        second_args = exec_mock.await_args_list[1].args[1]
        self.assertEqual(first_args["kind"], "lamp_exact")
        self.assertEqual(first_args["document_type"], "passport")
        self.assertEqual(second_args["kind"], "lamp_exact")
        self.assertEqual(second_args["name"], "NL Nova")
        self.assertNotIn("document_type", second_args)
        self.assertEqual(meta["retrieval_business_family_id"], "documents")
        self.assertEqual(meta["retrieval_route_stage"], "stage1_general")
        self.assertEqual(meta["retrieval_validation_status"], "ok")
        self.assertEqual(meta["retrieval_fallback_route_count"], 1)
        self.assertEqual(meta["retrieval_family_local_fallback_count"], 1)
        self.assertEqual(meta["retrieval_cross_family_fallback_count"], 0)
        self.assertEqual(meta["retrieval_attempted_fallback_count"], 1)
        self.assertEqual(meta["retrieval_used_fallback_route_id"], "corp_db.documents_by_lamp_name")
        self.assertEqual(meta["retrieval_used_fallback_scope"], "family_local")
        self.assertTrue(meta["retrieval_used_fallback_local"])
        self.assertEqual(meta["retrieval_close_reason"], "family_local_fallback_sufficient")

    def test_route_selector_codes_fallback_stays_inside_codes_family(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_family_id": "codes_and_sku",
                                "selected_route_id": "corp_db.sku_codes_lookup",
                                "confidence": "high",
                                "reason": "code lookup by lamp name",
                                "tool_args": {
                                    "name": "NL Nova",
                                    "lookup_direction": "by_name",
                                    "code_system": "etm",
                                },
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        response, exec_mock, meta = self._run_flow(
            user_message="Какой ETM-код у NL Nova?",
            corp_db_payloads=[
                {"status": "empty", "kind": "lamp_exact", "results": []},
                {
                    "status": "success",
                    "kind": "sku_by_code",
                    "results": [{"name": "NL Nova", "etm": "12345"}],
                },
            ],
            corp_db_payload={"status": "empty", "kind": "lamp_exact", "results": []},
            llm_responses_override=[
                selector_response,
                self._final_response("ETM-код для NL Nova: 12345."),
            ],
            route_selector_enabled=True,
        )

        self.assertIn("12345", response)
        self.assertEqual(exec_mock.await_count, 2)
        first_args = exec_mock.await_args_list[0].args[1]
        second_args = exec_mock.await_args_list[1].args[1]
        self.assertEqual(first_args["kind"], "lamp_exact")
        self.assertEqual(second_args["kind"], "sku_by_code")
        self.assertEqual(second_args["name"], "NL Nova")
        self.assertEqual(second_args["lookup_direction"], "by_name")
        self.assertEqual(second_args["code_system"], "etm")
        self.assertEqual(meta["retrieval_business_family_id"], "codes_and_sku")
        self.assertEqual(meta["retrieval_route_stage"], "stage1_general")
        self.assertEqual(meta["retrieval_validation_status"], "ok")
        self.assertEqual(meta["retrieval_fallback_route_count"], 2)
        self.assertEqual(meta["retrieval_family_local_fallback_count"], 1)
        self.assertEqual(meta["retrieval_cross_family_fallback_count"], 1)
        self.assertEqual(meta["retrieval_attempted_fallback_count"], 1)
        self.assertEqual(meta["retrieval_used_fallback_route_id"], "corp_db.sku_lookup")
        self.assertEqual(meta["retrieval_used_fallback_scope"], "family_local")
        self.assertTrue(meta["retrieval_used_fallback_local"])
        self.assertEqual(meta["retrieval_close_reason"], "family_local_fallback_sufficient")

    def test_route_selector_empty_sphere_category_lookup_stays_out_of_portfolio(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_family_id": "sphere_category_mapping",
                                "selected_route_id": "corp_db.sphere_curated_categories",
                                "confidence": "high",
                                "reason": "sphere to category mapping",
                                "tool_args": {"sphere": "Складские помещения"},
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        response, exec_mock, meta = self._run_flow(
            user_message="Какие категории подходят для складских помещений?",
            corp_db_payload={"status": "empty", "kind": "sphere_curated_categories", "results": []},
            llm_responses_override=[selector_response],
            route_selector_enabled=True,
        )

        self.assertIn("категори", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[1]["kind"], "sphere_curated_categories")
        self.assertEqual(meta["retrieval_business_family_id"], "sphere_category_mapping")
        self.assertEqual(meta["retrieval_route_stage"], "stage1_general")
        self.assertEqual(meta["retrieval_validation_status"], "ok")
        self.assertEqual(meta["retrieval_fallback_route_count"], 0)
        self.assertEqual(meta["retrieval_close_reason"], "family_local_fallback_exhausted")
        self.assertEqual(meta["retrieval_used_fallback_route_id"], "")

    def test_route_selector_empty_portfolio_lookup_does_not_drift_into_catalog(self):
        selector_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_family_id": "portfolio",
                                "selected_route_id": "corp_db.portfolio_by_sphere",
                                "confidence": "high",
                                "reason": "portfolio projects by sphere",
                                "tool_args": {"sphere": "РЖД"},
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        response, exec_mock, meta = self._run_flow(
            user_message="Какие объекты были реализованы для РЖД?",
            corp_db_payload={"status": "empty", "kind": "portfolio_by_sphere", "results": []},
            llm_responses_override=[selector_response],
            route_selector_enabled=True,
        )

        self.assertIn("уточните", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[1]["kind"], "portfolio_by_sphere")
        self.assertEqual(meta["retrieval_business_family_id"], "portfolio")
        self.assertEqual(meta["retrieval_route_stage"], "stage1_general")
        self.assertEqual(meta["retrieval_validation_status"], "ok")
        self.assertEqual(meta["retrieval_fallback_route_count"], 0)
        self.assertEqual(meta["retrieval_family_local_fallback_count"], 0)
        self.assertEqual(meta["retrieval_cross_family_fallback_count"], 0)
        self.assertEqual(meta["retrieval_close_reason"], "")
        self.assertEqual(meta["retrieval_used_fallback_route_id"], "")

    def test_wrong_document_doc_search_output_is_weak(self):
        payload = {
            "status": "success",
            "results": [
                {
                    "relative_path": "part_440.1325800.2023.doc",
                    "document_title": "СП 440.1325800.2023 Освещение спортивных сооружений",
                    "preview": "Нормы освещенности для спортивных объектов.",
                }
            ],
        }
        result = _ToolResult(True, output=json.dumps(payload, ensure_ascii=False))
        args = {"query": "пожарный сертификат line", "preferred_document_ids": ["doc_fire_line"]}
        state = {"document_id": "doc_fire_line"}

        self.assertEqual(_MODULE._doc_domain_evidence_status(result, args=args, state=state), "weak")
        self.assertFalse(
            _MODULE._is_successful_document_lookup(
                "doc_search",
                args,
                json.dumps(payload, ensure_ascii=False),
                "Найди пожарный сертификат LINE и покажи фрагмент",
            )
        )

    def test_deterministic_fallback_prefers_route_hint_args_for_doc_routes(self):
        tool_name, args = _MODULE._build_deterministic_fallback_call(
            "Найди пожарный сертификат LINE и покажи фрагмент",
            {
                "route_id": "doc_search.doc_fire_line",
                "tool_name": "doc_search",
                "tool_args": {"preferred_document_ids": ["doc_fire_line"]},
            },
            {
                "intent": "document_lookup",
                "knowledge_route_id": "",
            },
        )

        self.assertEqual(tool_name, "doc_search")
        self.assertEqual(args["preferred_document_ids"], ["doc_fire_line"])
        self.assertEqual(args["query"], "Найди пожарный сертификат LINE и покажи фрагмент")
        self.assertEqual(args["top"], 5)

    def _tool_call_response(self, tool_name: str, args: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": f"{tool_name}-1",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(args, ensure_ascii=False),
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

    def _final_response(self, content: str) -> dict:
        return {
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": "stop",
                }
            ]
        }

    def _is_tool_call_response(self, response: dict) -> bool:
        choices = response.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        return bool(message.get("tool_calls"))

    def _looks_like_selector_response(self, response: dict) -> bool:
        try:
            choices = response.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            if message.get("tool_calls"):
                return False
            content = str(message.get("content") or "")
            payload = json.loads(content)
        except Exception:
            return False
        return isinstance(payload, dict) and bool(payload.get("selected_route_id") or payload.get("selected_family_id"))

    def _selection_for_planned_tool(self, user_message: str, tool_name: str, planned_args: dict) -> dict:
        selection = _MODULE.select_route(user_message)
        try:
            candidate_routes = _MODULE.selector_payload_leaf_routes(_MODULE.build_route_selector_payload(user_message))
            catalog_routes = list((_MODULE.load_routing_index().get("routes") or []))
        except Exception:
            return selection
        matched_route = None
        for route in [*candidate_routes, *catalog_routes]:
            if not isinstance(route, dict):
                continue
            executor = str(route.get("tool_name") or route.get("executor") or "")
            if executor != tool_name:
                continue
            route_args = dict(route.get("tool_args") or {})
            if tool_name == "corp_db_search":
                discriminator_keys = {
                    "knowledge_route_id",
                    "document_type",
                    "profile",
                }
                discriminating_kind = str(planned_args.get("kind") or "") not in {"", "hybrid_search"}
                has_discriminator = discriminating_kind or any(planned_args.get(key) not in (None, "") for key in discriminator_keys)
                if not has_discriminator:
                    continue
                for key in ("kind", "knowledge_route_id", "document_type", "profile"):
                    expected = planned_args.get(key)
                    actual = route_args.get(key)
                    if expected not in (None, "") and actual not in (None, "") and expected != actual:
                        break
                else:
                    matched_route = dict(route)
                    break
            elif tool_name == "doc_search":
                expected_docs = set(planned_args.get("preferred_document_ids") or [])
                actual_docs = set(route_args.get("preferred_document_ids") or [])
                if expected_docs and actual_docs and not expected_docs.intersection(actual_docs):
                    continue
                matched_route = dict(route)
                break
        if matched_route is not None and hasattr(_MODULE, "_compact_selector_route_card"):
            try:
                matched_route = _MODULE._compact_selector_route_card(matched_route)
            except Exception:
                matched_route = dict(matched_route)
        if matched_route is None:
            return selection
        selection = dict(selection)
        selection["selected"] = matched_route
        selection["selected_family_id"] = str(matched_route.get("family_id") or selection.get("selected_family_id") or "")
        selection["selected_leaf_route_id"] = str(matched_route.get("leaf_route_id") or matched_route.get("route_id") or "")
        selection["selected_route_stage"] = str(matched_route.get("route_stage") or selection.get("selected_route_stage") or "")
        return selection

    def _selector_response(self, selection: dict, *, tool_args_override: dict | None = None) -> dict:
        selected = dict(selection.get("selected") or {})
        argument_schema = selected.get("argument_schema") if isinstance(selected.get("argument_schema"), dict) else {}
        allowed_keys = set((argument_schema.get("properties") or {}).keys()) if isinstance(argument_schema.get("properties"), dict) else set()
        selected_tool_args = dict(selected.get("tool_args") or {})
        merged_tool_args = dict(selected_tool_args)
        if isinstance(tool_args_override, dict):
            merged_tool_args.update(tool_args_override)
        selector_tool_args = {
            key: value
            for key, value in merged_tool_args.items()
            if not allowed_keys or key in allowed_keys
        }
        payload = {
            "selected_family_id": str(
                selection.get("selected_family_id")
                or selected.get("selected_family_id")
                or selected.get("family_id")
                or ""
            ),
            "selected_route_id": str(selected.get("route_id") or ""),
            "confidence": "high",
            "reason": "test selector default",
            "tool_args": selector_tool_args,
        }
        fallback_route_ids = list(selected.get("fallback_route_ids") or [])
        if fallback_route_ids:
            payload["fallback_route_ids"] = fallback_route_ids
        return {
            "choices": [
                {
                    "message": {"content": json.dumps(payload, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "model": "selector-test-model",
        }

    def _run_flow(
        self,
        *,
        user_message: str,
        corp_db_payload: dict,
        corp_db_args: dict | None = None,
        wiki_tool_name: str = "read_file",
        wiki_tool_args: dict | None = None,
        wiki_payload: dict | None = None,
        route_index: dict | None = None,
        corp_db_payloads: list[dict] | None = None,
        tool_call_sequence: list[tuple[str, dict]] | None = None,
        llm_responses_override: list[dict] | None = None,
        execution_mode: str = "runtime",
        skill_mentions: str = "",
        route_selector_enabled: bool = True,
    ) -> tuple[str, AsyncMock, dict]:
        meta: dict = {}
        remaining_corp_db_payloads = list(corp_db_payloads or [])
        tool_defs = [
            {
                "type": "function",
                "function": {
                    "name": "corp_db_search",
                    "description": "Corp DB",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": wiki_tool_name,
                    "description": "Doc path tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

        default_sequence = [
            (
                "corp_db_search",
                corp_db_args
                or {
                    "kind": "hybrid_search",
                    "profile": "kb_search",
                    "entity_types": ["company"],
                    "query": "сайт компании",
                },
            ),
            (
                wiki_tool_name,
                wiki_tool_args or {"path": "/data/corp_docs/live/doc_123.json"},
            ),
        ]
        llm_calls: list[list[dict]] = []

        async def fake_call_llm(messages, tool_definitions, model_override="", purpose="agent_loop"):
            llm_calls.append(messages)
            if str(purpose).startswith("route_selector"):
                if not selector_llm_responses:
                    raise AssertionError("unexpected extra route_selector call_llm invocation")
                return selector_llm_responses.pop(0)
            if purpose == "finalizer":
                for index, response in enumerate(llm_responses):
                    if not self._is_tool_call_response(response) and not self._looks_like_selector_response(response):
                        return llm_responses.pop(index)
                raise AssertionError("unexpected finalizer call_llm invocation without final response")
            if not llm_responses:
                raise AssertionError("unexpected extra call_llm invocation")
            return llm_responses.pop(0)

        async def fake_execute_tool(name, args, ctx, **kwargs):
            if name == "corp_db_search":
                payload_value = remaining_corp_db_payloads.pop(0) if remaining_corp_db_payloads else corp_db_payload
                metadata = {
                    "runtime_payload_format": "full_json",
                    "bench_payload_format": "compact_company_fact_v1"
                    if str(args.get("kind") or "") == "hybrid_search"
                    else "compact_bench_value_v1",
                    "bench_artifact": {
                        "tool": "corp_db_search",
                        "kind": str(args.get("kind") or payload_value.get("kind") or ""),
                        "payload": {"status": payload_value.get("status"), "results": payload_value.get("results", [])},
                    },
                }
                return _ToolResult(True, output=json.dumps(payload_value, ensure_ascii=False), metadata=metadata)
            if name == wiki_tool_name:
                if wiki_tool_name == "doc_search":
                    payload = wiki_payload or {
                        "status": "success",
                        "results": [{"relative_path": "common_information_about_company.md", "snippet": "wiki preview"}],
                    }
                    metadata = {
                        "runtime_payload_format": "full_json",
                        "bench_payload_format": "compact_doc_search_artifact_v1",
                        "bench_artifact": {"tool": "doc_search", "kind": "doc_search", "payload": payload},
                    }
                    return _ToolResult(True, output=json.dumps(payload, ensure_ascii=False), metadata=metadata)
                return _ToolResult(True, output="wiki preview", metadata={"runtime_payload_format": "full_text"})
            if name == "doc_search":
                payload = wiki_payload or {
                    "status": "success",
                    "results": [{"relative_path": "common_information_about_company.md", "snippet": "wiki preview"}],
                }
                metadata = {
                    "runtime_payload_format": "full_json",
                    "bench_payload_format": "compact_doc_search_artifact_v1",
                    "bench_artifact": {"tool": "doc_search", "kind": "doc_search", "payload": payload},
                }
                return _ToolResult(True, output=json.dumps(payload, ensure_ascii=False), metadata=metadata)
            raise AssertionError(f"unexpected tool call: {name}")

        exec_mock = AsyncMock(side_effect=fake_execute_tool)

        with tempfile.TemporaryDirectory() as tmpdir:
            if route_index is not None:
                route_dir = Path(tmpdir) / "corp_docs" / "manifests" / "routes"
                route_dir.mkdir(parents=True, exist_ok=True)
                (route_dir / "index.json").write_text(json.dumps(route_index, ensure_ascii=False), encoding="utf-8")
            default_llm_responses = [self._tool_call_response(name, args) for name, args in (tool_call_sequence or default_sequence)]
            if llm_responses_override is None:
                default_llm_responses.append(self._final_response("Официальный сайт: https://ladzavod.ru"))
            llm_responses = list(llm_responses_override or default_llm_responses)
            selector_llm_responses: list[dict] = []
            with patch.dict(
                os.environ,
                {
                    "CORP_DOCS_ROOT": str(Path(tmpdir) / "corp_docs"),
                    "ROUTE_SELECTOR_ENABLED": "true" if route_selector_enabled else "false",
                },
                clear=False,
            ), patch.object(
                _MODULE.CONFIG, "workspace", tmpdir
            ), patch.object(
                _MODULE.CONFIG, "max_context_messages", 12
            ), patch.object(
                _MODULE.CONFIG, "max_history", 12
            ), patch.object(
                _MODULE.CONFIG, "max_tool_output", 4000
            ), patch.object(
                _MODULE, "get_tool_definitions", AsyncMock(return_value=tool_defs)
            ), patch.object(
                _MODULE, "_check_userbot_available", AsyncMock(return_value=False)
            ), patch.object(
                _MODULE, "load_skill_mentions", AsyncMock(return_value=skill_mentions)
            ), patch.object(
                _MODULE, "get_google_email", return_value=None
            ), patch.object(
                _MODULE, "_get_admin_id", return_value=0
            ), patch.object(
                _MODULE, "call_llm", AsyncMock(side_effect=fake_call_llm)
            ), patch.object(
                _MODULE, "execute_tool", exec_mock
            ), patch.object(
                _MODULE, "run_meta_get", lambda: meta
            ):
                if route_selector_enabled:
                    if llm_responses and (self._looks_like_selector_response(llm_responses[0]) or "error" in llm_responses[0]):
                        while llm_responses and (self._looks_like_selector_response(llm_responses[0]) or "error" in llm_responses[0]):
                            selector_llm_responses.append(llm_responses.pop(0))
                    else:
                        planned_tool_name, planned_tool_args = (tool_call_sequence or default_sequence)[0]
                        selection = self._selection_for_planned_tool(user_message, planned_tool_name, planned_tool_args)
                        selector_llm_responses = [
                            self._selector_response(
                                selection,
                                tool_args_override=planned_tool_args if isinstance(planned_tool_args, dict) else None,
                            )
                        ]
                _MODULE.sessions.sessions.clear()
                response = asyncio.run(
                    _MODULE.run_agent(
                        user_id=42,
                        chat_id=42,
                        message=user_message,
                        username="bench",
                        chat_type="private",
                        source="bot",
                        execution_mode=execution_mode,
                    )
                )
        if llm_calls:
            meta["_first_system_prompt"] = llm_calls[0][0]["content"]

        return response, exec_mock, meta

    def test_guardrail_blocks_wiki_after_successful_company_fact_corp_db(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какой официальный сайт у компании ЛАДзавод светотехники?",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "https://ladzavod.ru"}]},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")
        self.assertEqual(meta["execution_mode"], "runtime")

    def test_empty_corp_db_allows_wiki_fallback(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какой официальный сайт у компании ЛАДзавод светотехники?",
            corp_db_payload={"status": "empty", "kind": "hybrid_search", "results": []},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "официальный сайт компании"},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertEqual(meta["routing_guardrail_hits"], 0)
        self.assertEqual(meta["retrieval_phase"], "open")
        self.assertEqual(meta["retrieval_evidence_status"], "empty")

    def test_generic_certification_query_uses_company_common_once(self):
        response, exec_mock, meta = self._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Сертификаты и декларации",
                        "preview": "Сертификаты и декларации подтверждают соответствие продукции требованиям.",
                        "metadata": {"source_file": "common_information_about_company.md"},
                    }
                ],
            },
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "сертификаты"},
            tool_call_sequence=[
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "сертификаты"}),
            ],
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "сертификаты"}),
                self._final_response("Есть сертификаты и декларации соответствия."),
            ],
        )

        self.assertIn("сертификаты", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        args = exec_mock.await_args_list[0].args[1]
        self.assertEqual(args["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(args["source_files"], ["common_information_about_company.md"])
        self.assertEqual(args["topic_facets"], ["certification"])
        self.assertEqual(meta["retrieval_route_id"], "corp_kb.company_common")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")
        self.assertEqual(meta["retrieval_evidence_status"], "sufficient")

    def test_generic_component_query_uses_company_common_once(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какие используются комплектующие?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Качество и комплектующие",
                        "preview": "Комплектующие проходят входной контроль качества и проверку надежности.",
                        "metadata": {"source_file": "common_information_about_company.md"},
                    }
                ],
            },
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "комплектующие"},
            tool_call_sequence=[
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "комплектующие"}),
            ],
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "комплектующие"}),
                self._final_response("Комплектующие проходят контроль качества."),
            ],
        )

        self.assertIn("комплектующие", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        args = exec_mock.await_args_list[0].args[1]
        self.assertEqual(args["knowledge_route_id"], "corp_kb.company_common")
        self.assertEqual(args["source_files"], ["common_information_about_company.md"])
        self.assertEqual(args["topic_facets"], ["quality"])
        self.assertEqual(meta["retrieval_route_id"], "corp_kb.company_common")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")
        self.assertEqual(meta["retrieval_evidence_status"], "sufficient")

    def test_explicit_wiki_request_keeps_wiki_available_after_corp_db_success(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Найди в wiki официальный сайт компании ЛАДзавод светотехники и покажи фрагмент.",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "https://ladzavod.ru"}]},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "официальный сайт компании"},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertTrue(meta["retrieval_explicit_wiki_request"])
        self.assertEqual(meta["routing_guardrail_hits"], 0)

    def test_guardrail_blocks_search_files_bypass_after_corp_db_success(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какой официальный сайт у компании ЛАДзавод светотехники?",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "https://ladzavod.ru"}]},
            wiki_tool_name="search_files",
            wiki_tool_args={"pattern": "/data/corp_docs/live/**/*.json"},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")

    def test_successful_application_recommendation_can_be_followed_by_doc_search(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подбери освещение для спортивного стадиона",
            corp_db_args={"kind": "application_recommendation", "query": "подбери освещение для спортивного стадиона"},
            corp_db_payload={
                "status": "success",
                "kind": "application_recommendation",
                "resolved_application": {
                    "status": "resolved",
                    "application_key": "sports_high_power",
                    "sphere_name": "Спортивное и освещение высокой мощности",
                },
                "recommended_lamps": [{"name": "LAD LED R500-9-30-6-650LZD"}],
                "follow_up_question": "Уточните высоту установки.",
                "results": [{"name": "LAD LED R500-9-30-6-650LZD"}],
            },
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "стадион"},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertEqual(meta["routing_guardrail_hits"], 0)

    def test_successful_doc_search_document_lookup_can_be_followed_by_corp_db(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Нужен пожарный сертификат LINE, дай прямую ссылку.",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "unexpected"}]},
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "пожарный сертификат line"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "пожарный сертификат line"},
            wiki_payload={
                "status": "success",
                "results": [
                    {
                        "relative_path": "certs/line-fire.pdf",
                        "document_title": "Пожарный сертификат LINE",
                        "preview": "Пожарный сертификат LINE: https://ladzavod.ru/certs/line-fire.pdf",
                    }
                ],
            },
            route_index={
                "generated_at": "2026-04-20T00:00:00Z",
                "route_count": 1,
                "routes": [
                    {
                        "route_id": "doc_search.doc_fire_line",
                        "route_kind": "doc_domain",
                        "route_family": "doc_search.doc_fire_line",
                        "source": "doc_search",
                        "title": "Пожарный сертификат LINE",
                        "keywords": ["пожарный", "сертификат", "line"],
                        "patterns": ["пожарный сертификат line"],
                        "tool_name": "doc_search",
                        "tool_args": {"preferred_document_ids": ["doc_fire_line", "certs/line-fire.pdf"]},
                    }
                ],
            },
            tool_call_sequence=[
                (
                    "doc_search",
                    {
                        "query": "пожарный сертификат line",
                        "preferred_document_ids": ["doc_fire_line", "certs/line-fire.pdf"],
                    },
                ),
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "пожарный сертификат line"}),
            ],
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "doc_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "corp_db_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertEqual(meta["routing_guardrail_hits"], 0)
        self.assertEqual(meta["retrieval_phase"], "closed")
        self.assertEqual(meta["retrieval_evidence_status"], "sufficient")
        self.assertEqual(meta["retrieval_close_reason"], "doc_search_payload_sufficient")

    def test_route_index_keeps_corp_db_as_hint_but_allows_doc_tool_first_for_company_fact(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какой официальный сайт у компании ЛАДзавод светотехники?",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "https://ladzavod.ru"}]},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "официальный сайт компании"},
            route_index={
                "generated_at": "2026-04-05T00:00:00Z",
                "route_count": 1,
                "routes": [
                    {
                        "route_id": "corp_db.company_profile",
                        "source": "corp_db",
                        "title": "Company profile",
                        "keywords": ["сайт", "контакты", "компания"],
                        "patterns": ["официальный сайт"],
                        "tool_name": "corp_db_search",
                        "tool_args": {"kind": "hybrid_search", "profile": "kb_search", "entity_types": ["company"]},
                    }
                ],
            },
            tool_call_sequence=[
                ("doc_search", {"query": "официальный сайт компании"}),
                (
                    "corp_db_search",
                    {"kind": "hybrid_search", "profile": "kb_search", "entity_types": ["company"], "query": "официальный сайт компании"},
                ),
            ],
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "doc_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "corp_db_search")
        self.assertEqual(meta["retrieval_route_source"], "corp_db")
        self.assertEqual(meta["retrieval_route_id"], "corp_kb.company_common")
        self.assertEqual(meta["retrieval_selected_route_kind"], "corp_table")
        self.assertIn("corp_kb.company_common", meta["retrieval_candidate_route_ids"])
        self.assertEqual(meta["routing_guardrail_hits"], 0)

    def test_route_index_blocks_skill_directory_browse_before_corp_db_for_company_fact(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Расскажи о компании",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Наш профиль",
                        "preview": "Наш профиль — промышленное освещение и работа в тяжёлых условиях эксплуатации.",
                    }
                ],
            },
            wiki_tool_name="list_directory",
            wiki_tool_args={"path": "/data/skills/corp-pg-db/"},
            route_index={
                "generated_at": "2026-04-08T00:00:00Z",
                "route_count": 1,
                "routes": [
                    {
                        "route_id": "corp_db.company_profile",
                        "source": "corp_db",
                        "title": "Company profile",
                        "keywords": ["компания", "контакты", "профиль"],
                        "patterns": ["расскажи о компании"],
                        "tool_name": "corp_db_search",
                        "tool_args": {"kind": "hybrid_search", "profile": "kb_search", "entity_types": ["company"]},
                    }
                ],
            },
            tool_call_sequence=[
                ("list_directory", {"path": "/data/skills/corp-pg-db/"}),
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "о компании"}),
            ],
            llm_responses_override=[
                self._tool_call_response("list_directory", {"path": "/data/skills/corp-pg-db/"}),
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "о компании"}),
                self._final_response("Наш профиль — промышленное освещение и работа в тяжёлых условиях эксплуатации."),
            ],
        )

        self.assertIn("промышленное освещение", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["retrieval_route_id"], "corp_kb.company_common")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")

    def test_runtime_prompt_exposes_routing_shortlist(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подбери освещение для спортивного стадиона",
            corp_db_payload={
                "status": "success",
                "kind": "application_recommendation",
                "results": [{"name": "LAD LED R500"}],
            },
            corp_db_args={"kind": "application_recommendation", "query": "подбери освещение для спортивного стадиона"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "стадион"},
            route_index={
                "generated_at": "2026-04-17T00:00:00Z",
                "route_count": 2,
                "routes": [
                    {
                        "route_id": "corp_db.application_recommendation",
                        "route_kind": "corp_script",
                        "route_family": "corp_db.application_recommendation",
                        "source": "corp_db",
                        "title": "Application recommendation",
                        "keywords": ["стадион", "подбери"],
                        "patterns": ["подбери освещение"],
                        "tool_name": "corp_db_search",
                        "tool_args": {"kind": "application_recommendation"},
                    },
                    {
                        "route_id": "doc_search.sports_lighting_norms",
                        "route_kind": "doc_domain",
                        "route_family": "doc_search.sports_lighting_norms",
                        "source": "doc_search",
                        "title": "Sports lighting norms",
                        "keywords": ["спорт", "нормы", "освещенности"],
                        "patterns": ["нормы освещенности для спортивных объектов"],
                        "tool_name": "doc_search",
                        "tool_args": {"preferred_document_ids": ["sports_norms_doc"]},
                    },
                ],
            },
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "application_recommendation", "query": "подбери освещение для спортивного стадиона"}),
                self._final_response("Подобрал вариант для стадиона."),
            ],
        )

        self.assertIn("стадиона", response)
        system_prompt = meta["_first_system_prompt"]
        self.assertIn("Routing shortlist:", system_prompt)
        self.assertIn("corp_db.application_recommendation", system_prompt)
        self.assertIn("- secondary:", system_prompt)

    def test_skills_remain_visible_but_do_not_force_skill_first_behavior(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подскажи контакты компании.",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [{"value": "https://ladzavod.ru"}],
            },
            skill_mentions="## Available Skills\n\n| Skill | Description |\n|-------|-------------|\n| `corp-pg-db` | Corp skill |\n",
            wiki_tool_name="list_directory",
            wiki_tool_args={"path": "/data/skills/corp-pg-db/"},
            tool_call_sequence=[
                ("list_directory", {"path": "/data/skills/corp-pg-db/"}),
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"}),
            ],
            llm_responses_override=[
                self._tool_call_response("list_directory", {"path": "/data/skills/corp-pg-db/"}),
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"}),
                self._final_response("Контакты компании: https://ladzavod.ru"),
            ],
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertIn("## Available Skills", meta["_first_system_prompt"])
        self.assertIn("corp-pg-db", meta["_first_system_prompt"])

    def test_route_index_keeps_doc_search_as_hint_but_allows_corp_db_first_for_document_topic(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Найди пожарный сертификат line и покажи фрагмент",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "unexpected"}]},
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "пожарный сертификат line"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "пожарный сертификат line"},
            route_index={
                "generated_at": "2026-04-05T00:00:00Z",
                "route_count": 1,
                "routes": [
                    {
                        "route_id": "doc_search.doc_fire_line",
                        "source": "doc_search",
                        "title": "Пожарный сертификат LINE",
                        "keywords": ["пожарный", "сертификат", "line"],
                        "patterns": ["пожарный сертификат line"],
                        "tool_name": "doc_search",
                        "tool_args": {"preferred_document_ids": ["doc_fire_line"]},
                    }
                ],
            },
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertEqual(meta["retrieval_route_source"], "doc_search")
        self.assertEqual(meta["retrieval_route_id"], "doc_search.doc_fire_line")
        self.assertEqual(meta["retrieval_selected_route_kind"], "doc_domain")
        self.assertEqual(meta["document_id"], "doc_fire_line")
        self.assertIn("doc_search.doc_fire_line", meta["retrieval_candidate_route_ids"])
        self.assertEqual(meta["routing_guardrail_hits"], 0)

    def test_route_index_prefers_doc_search_for_sports_norms_document_domain_query(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какие нормы освещенности для спортивных объектов указаны в документе?",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "unexpected"}]},
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "нормы освещенности спортивных объектов"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "нормы освещенности спортивных объектов"},
            wiki_payload={
                "status": "success",
                "results": [
                    {
                        "relative_path": "part_440.1325800.2023.doc",
                        "snippet": "Нормы освещенности для спортивных объектов и спортивных залов приведены в документе.",
                    }
                ],
            },
            route_index={
                "generated_at": "2026-04-08T00:00:00Z",
                "route_count": 1,
                "routes": [
                    {
                        "route_id": "doc_search.sports_lighting_norms",
                        "route_kind": "doc_domain",
                        "route_family": "sports_lighting_norms",
                        "source": "doc_search",
                        "title": "Нормы освещенности спортивных объектов",
                        "keywords": ["спорт", "спортивных", "освещенности", "нормы"],
                        "patterns": ["нормы освещенности для спортивных объектов"],
                        "tool_name": "doc_search",
                        "tool_args": {"preferred_document_ids": ["part_440.1325800.2023.doc"]},
                    }
                ],
            },
            llm_responses_override=[
                self._tool_call_response("doc_search", {"query": "нормы освещенности спортивных объектов"}),
                self._final_response("В документе есть нормы освещенности для спортивных объектов и спортивных залов."),
            ],
        )

        self.assertIn("нормы освещенности", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "doc_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertEqual(meta["retrieval_selected_route_kind"], "doc_domain")
        self.assertEqual(meta["retrieval_route_id"], "doc_search.sports_lighting_norms")
        self.assertEqual(meta["retrieval_route_family"], "doc_search.sports_lighting_norms")
        self.assertEqual(meta["document_id"], "part_440.1325800.2023.doc")

    def test_guardrail_blocks_doc_browse_after_successful_doc_search_for_document_lookup(self):
        cases = [
            ("read_file", {"path": "/data/corp_docs/live/doc_123.json"}),
            ("search_text", {"path": "/data/corp_docs/live/doc_123.json", "query": "LINE"}),
            ("search_files", {"path": "/data/corp_docs/live", "pattern": "/data/corp_docs/live/**/*.json"}),
            ("run_command", {"command": "grep -R LINE /data/corp_docs/live"}),
        ]

        for tool_name, tool_args in cases:
            with self.subTest(tool_name=tool_name):
                response, exec_mock, meta = self._run_flow(
                    user_message="Найди в wiki пожарный сертификат LINE и дай ссылку.",
                    corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "unexpected"}]},
                    wiki_tool_name=tool_name,
                    wiki_tool_args=tool_args,
                    wiki_payload={
                        "status": "success",
                        "results": [
                            {
                                "relative_path": "certs/line-fire.pdf",
                                "document_title": "Пожарный сертификат LINE",
                                "preview": "Пожарный сертификат LINE: https://ladzavod.ru/certs/line-fire.pdf",
                            }
                        ],
                    },
                    route_index={
                        "generated_at": "2026-04-20T00:00:00Z",
                        "route_count": 1,
                        "routes": [
                            {
                                "route_id": "doc_search.doc_fire_line",
                                "route_kind": "doc_domain",
                                "route_family": "doc_search.doc_fire_line",
                                "source": "doc_search",
                                "title": "Пожарный сертификат LINE",
                                "keywords": ["пожарный", "сертификат", "line"],
                                "patterns": ["пожарный сертификат line"],
                                "tool_name": "doc_search",
                                "tool_args": {"preferred_document_ids": ["doc_fire_line", "certs/line-fire.pdf"]},
                            }
                        ],
                    },
                    tool_call_sequence=[
                        (
                            "doc_search",
                            {
                                "query": "пожарный сертификат line",
                                "preferred_document_ids": ["doc_fire_line", "certs/line-fire.pdf"],
                            },
                        ),
                        (tool_name, tool_args),
                    ],
                    llm_responses_override=[
                        self._tool_call_response(
                            "doc_search",
                            {
                                "query": "пожарный сертификат line",
                                "preferred_document_ids": ["doc_fire_line", "certs/line-fire.pdf"],
                            },
                        ),
                        self._tool_call_response(tool_name, tool_args),
                        self._final_response("Нашёл пожарный сертификат LINE. Прямая ссылка: https://ladzavod.ru/certs/line-fire.pdf"),
                    ],
                )

                self.assertIn("line-fire.pdf", response)
                self.assertEqual(exec_mock.await_count, 1)
                self.assertEqual(exec_mock.await_args_list[0].args[0], "doc_search")
                self.assertEqual(meta["retrieval_selected_source"], "doc_search")
                self.assertEqual(meta["retrieval_phase"], "closed")
                self.assertEqual(meta["retrieval_evidence_status"], "sufficient")
                self.assertEqual(meta["retrieval_close_reason"], "doc_search_payload_sufficient")
                self.assertEqual(meta["routing_guardrail_hits"], 1)
                self.assertEqual(meta["routing_guardrail_last_blocked_tool"], tool_name)

    def test_empty_llm_completion_uses_deterministic_company_fact_fallback(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Контакты",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Контакты",
                        "preview": "Телефон +7 (351) 239-18-11, email lad@ladled.ru. Сайт https://ladzavod.ru",
                    }
                ],
            },
            llm_responses_override=[{"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}],
        )

        self.assertIn("239-18-11", response)
        self.assertIn("lad@ladled.ru", response)
        self.assertNotIn("…", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertIn("lad@ladled.ru", exec_mock.await_args_list[0].args[1]["query"].lower())
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")

    def test_company_fact_primary_query_rewrite_uses_llm_finalization_in_runtime_mode(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подскажи контакты компании.",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Контактная информация",
                        "preview": "Телефон +7 (351) 239-18-11, email lad@ladled.ru. Сайт https://ladzavod.ru",
                    }
                ],
            },
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"},
            llm_responses_override=[
                self._tool_call_response(
                    "corp_db_search",
                    {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"},
                ),
                self._final_response("Телефон: +7 (351) 239-18-11\nEmail: lad@ladled.ru\nСайт: https://ladzavod.ru"),
            ],
        )

        self.assertIn("239-18-11", response)
        self.assertIn("lad@ladled.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertIn("lad@ladled.ru", exec_mock.await_args_list[0].args[1]["query"].lower())
        self.assertTrue(meta["company_fact_payload_relevant"])
        self.assertEqual(meta["company_fact_intent_type"], "contacts")
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")
        self.assertEqual(meta["company_fact_runtime_payload_format"], "full_json")
        self.assertEqual(meta["company_fact_bench_payload_format"], "compact_company_fact_v1")
        self.assertEqual(meta["execution_mode"], "runtime")

    def test_company_fact_primary_query_rewrite_allows_deterministic_primary_in_benchmark_mode(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подскажи контакты компании.",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "Контактная информация",
                        "preview": "Телефон +7 (351) 239-18-11, email lad@ladled.ru. Сайт https://ladzavod.ru",
                    }
                ],
            },
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"},
            llm_responses_override=[
                self._tool_call_response(
                    "corp_db_search",
                    {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"},
                ),
            ],
            execution_mode="benchmark",
        )

        self.assertIn("239-18-11", response)
        self.assertIn("lad@ladled.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertTrue(meta["company_fact_payload_relevant"])
        self.assertEqual(meta["company_fact_finalizer_mode"], "deterministic_primary")
        self.assertEqual(meta["execution_mode"], "benchmark")

    def test_weak_company_fact_payload_does_not_block_doc_search_fallback(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подскажи контакты компании.",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "О компании",
                        "preview": "ЛАДзавод светотехники производит промышленное светотехническое оборудование.",
                    }
                ],
            },
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "контакты компании"},
            wiki_payload={
                "status": "success",
                "results": [
                    {
                        "relative_path": "common_information_about_company.md",
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "preview": "Телефон: +7 (351) 239-18-11. Электронная почта: lad@ladled.ru.",
                    }
                ],
            },
            tool_call_sequence=[
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"}),
                ("doc_search", {"query": "контакты компании"}),
            ],
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertFalse(meta["company_fact_payload_relevant"])
        self.assertEqual(meta["routing_guardrail_hits"], 0)
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertEqual(meta["retrieval_phase"], "open")
        self.assertEqual(meta["retrieval_evidence_status"], "weak")

    def test_authoritative_kb_empty_allows_secondary_route_before_loop_block(self):
        response, exec_mock, meta = self._run_flow(
            user_message="[От: @bench (42)]\n[Голосовое сообщение, распознанный текст:]\nЧто такое Luxnet?",
            corp_db_payload={"status": "empty", "kind": "hybrid_search", "results": []},
            corp_db_payloads=[
                {"status": "empty", "kind": "hybrid_search", "results": []},
                {
                    "status": "success",
                    "kind": "hybrid_search",
                    "results": [
                        {
                            "document_title": "О Luxnet",
                            "heading": "Что такое Luxnet",
                            "preview": "Luxnet — это система управления освещением.",
                            "metadata": {"source_file": "about_Luxnet.md"},
                        }
                    ],
                },
            ],
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "luxnet"},
            tool_call_sequence=[
                ("corp_db_search", {"kind": "hybrid_search", "query": "luxnet"}),
                ("doc_search", {"query": "luxnet"}),
                ("corp_db_search", {"kind": "hybrid_search", "query": "что такое luxnet"}),
            ],
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "query": "luxnet"}),
                self._tool_call_response("doc_search", {"query": "luxnet"}),
                self._tool_call_response("corp_db_search", {"kind": "hybrid_search", "query": "что такое luxnet"}),
                self._final_response("Luxnet — это система управления освещением."),
            ],
        )

        self.assertIn("Luxnet", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertEqual(exec_mock.await_args_list[0].args[1]["knowledge_route_id"], "corp_kb.luxnet")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertEqual(meta["retrieval_route_family"], "corp_kb.luxnet")
        self.assertEqual(meta["knowledge_route_id"], "corp_kb.luxnet")
        self.assertEqual(meta["retrieval_retry_count"], 0)
        self.assertEqual(meta["retrieval_phase"], "open")
        self.assertEqual(meta["retrieval_close_reason"], "")

    def test_about_company_uses_llm_finalization_with_full_runtime_payload_in_runtime_mode(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Расскажи о компании",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "heading": "О компании",
                        "preview": "Компания ЛАДзавод светотехники занимается разработкой и производством промышленного светотехнического оборудования.",
                    }
                ],
            },
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "о компании"},
            llm_responses_override=[
                self._tool_call_response(
                    "corp_db_search",
                    {"kind": "hybrid_search", "profile": "kb_search", "query": "о компании"},
                ),
                self._final_response(
                    "Компания ЛАДзавод светотехники занимается разработкой и производством промышленного "
                    "светотехнического оборудования для промышленных объектов и тяжёлых условий эксплуатации."
                ),
            ],
        )

        self.assertIn("разработкой и производством", response)
        self.assertNotIn("…", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["company_fact_intent_type"], "about_company")
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")
        self.assertEqual(meta["company_fact_runtime_payload_format"], "full_json")

    def test_exact_duplicate_retrieval_attempt_is_blocked(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подскажи контакты компании.",
            corp_db_payload={"status": "empty", "kind": "hybrid_search", "results": []},
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"},
            tool_call_sequence=[
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"}),
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании"}),
            ],
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertEqual(meta["retrieval_phase"], "open")

    def test_render_generic_kb_payload_keeps_series_chunk_text(self):
        payload = {
            "status": "success",
            "kind": "hybrid_search",
            "results": [
                {
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "Доступные серии освещения",
                    "content": (
                        "- Серия LAD LED R500 - Эффективный светодиодный светильник.\n"
                        "- Серия LAD LED R700 - Светодиодные светильники для наружного освещения.\n"
                        "- Серия LAD LED LINE - Линейные светодиодные светильники для промышленного, складского, "
                        "торгового и общего освещения."
                    ),
                }
            ],
        }

        rendered = _MODULE._render_generic_kb_payload(payload)

        self.assertIn("LAD LED LINE", rendered)
        self.assertIn("линейные светодиодные светильники", rendered.lower())

    def test_application_recommendation_runtime_answer_does_not_leak_compact_preview(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подбери освещение для спортивного стадиона",
            corp_db_payload={
                "status": "success",
                "kind": "application_recommendation",
                "resolved_application": {
                    "application_key": "sports_high_power",
                    "sphere_name": "Спортивное и освещение высокой мощности",
                },
                "recommended_lamps": [
                    {
                        "name": "LAD LED R500-9-30-6-650LZD",
                        "url": "https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd",
                        "recommendation_reason": "высокая мощность для стадионного освещения",
                    }
                ],
                "follow_up_question": "Уточните высоту установки.",
            },
            corp_db_args={"kind": "application_recommendation", "query": "стадион"},
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "application_recommendation", "query": "стадион"}),
                self._final_response(
                    "Для спортивного стадиона подойдёт серия LAD LED R500. "
                    "Рекомендую модель LAD LED R500-9-30-6-650LZD для мощного заливающего света. "
                    "Уточните высоту установки."
                ),
            ],
        )

        self.assertIn("LAD LED R500-9-30-6-650LZD", response)
        self.assertIn("Уточните высоту установки", response)
        self.assertNotIn("…", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")
        self.assertEqual(meta["application_recovery_outcome"], "")

    def test_application_replay_for_rzd_returns_healthy_recommendation(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Что порекомендуешь для РЖД?",
            corp_db_args={"kind": "application_recommendation", "query": "Что порекомендуешь для РЖД?"},
            corp_db_payload={
                "status": "success",
                "kind": "application_recommendation",
                "resolved_application": {
                    "application_key": "rzd",
                    "sphere_name": "РЖД",
                },
                "recommended_lamps": [
                    {
                        "name": "LAD LED LINE",
                        "url": "https://ladzavod.ru/catalog/line",
                        "recommendation_reason": "подходит для инфраструктуры РЖД",
                    }
                ],
                "follow_up_question": "Уточните высоту установки и требуемую степень защиты.",
                "results": [{"name": "LAD LED LINE"}],
            },
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "application_recommendation", "query": "Что порекомендуешь для РЖД?"}),
                self._final_response("Для РЖД подойдёт LAD LED LINE. Уточните высоту установки и требуемую степень защиты."),
            ],
        )

        self.assertIn("LAD LED LINE", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[1]["kind"], "application_recommendation")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")
        self.assertEqual(meta["application_recovery_outcome"], "")

    def test_application_replay_for_rzd_stops_after_empty_without_hybrid_fallback(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Что порекомендуешь для РЖД?",
            corp_db_args={"kind": "application_recommendation", "query": "Что порекомендуешь для РЖД?"},
            corp_db_payload={
                "status": "empty",
                "kind": "application_recommendation",
                "results": [],
            },
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "application_recommendation", "query": "Что порекомендуешь для РЖД?"}),
                self._tool_call_response(
                    "corp_db_search",
                    {
                        "kind": "hybrid_search",
                        "query": "Что порекомендуешь для РЖД?",
                        "limit_categories": 0,
                        "limit_lamps": 0,
                        "limit_portfolio": 0,
                    },
                ),
            ],
        )

        self.assertIn("уточните", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[1]["kind"], "application_recommendation")
        self.assertEqual(meta["application_recovery_outcome"], "bounded_application_fallback")
        self.assertEqual(meta["retrieval_close_reason"], "bounded_application_fallback")
        self.assertEqual(meta["retrieval_evidence_status"], "empty")

    def test_application_replay_for_rzd_records_primary_error_stop(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Что порекомендуешь для РЖД?",
            corp_db_args={"kind": "application_recommendation", "query": "Что порекомендуешь для РЖД?"},
            corp_db_payload={
                "status": "error",
                "kind": "application_recommendation",
                "message": "Корпоративная база временно недоступна",
                "results": [],
            },
            llm_responses_override=[
                self._tool_call_response("corp_db_search", {"kind": "application_recommendation", "query": "Что порекомендуешь для РЖД?"}),
                self._tool_call_response(
                    "corp_db_search",
                    {
                        "kind": "hybrid_search",
                        "query": "Что порекомендуешь для РЖД?",
                        "limit_categories": 0,
                        "limit_lamps": 0,
                        "limit_portfolio": 0,
                    },
                ),
            ],
        )

        self.assertIn("повторите запрос позже", response.lower())
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["application_recovery_outcome"], "stopped_after_primary_error")
        self.assertEqual(meta["retrieval_close_reason"], "stopped_after_primary_error")
        self.assertEqual(meta["retrieval_evidence_status"], "error")

    def test_document_lookup_runtime_answer_does_not_leak_compact_preview(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Нужен пожарный сертификат LINE, дай прямую ссылку.",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "unexpected"}]},
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "пожарный сертификат line"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "пожарный сертификат line"},
            wiki_payload={
                "status": "success",
                "results": [
                    {
                        "relative_path": "certs/line-fire.pdf",
                        "document_title": "Пожарный сертификат LINE",
                        "preview": "Пожарный сертификат LINE: https://ladzavod.ru/certs/line-fire.pdf",
                    }
                ],
            },
            llm_responses_override=[
                self._tool_call_response("doc_search", {"query": "пожарный сертификат line"}),
                self._final_response(
                    "Нашёл пожарный сертификат LINE. "
                    "Прямая ссылка: https://ladzavod.ru/certs/line-fire.pdf"
                ),
            ],
        )

        self.assertIn("https://ladzavod.ru/certs/line-fire.pdf", response)
        self.assertNotIn("…", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")

    def test_empty_llm_completion_uses_doc_search_when_contact_kb_payload_has_no_contacts(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Контакты",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [
                    {
                        "document_title": "О компании",
                        "heading": "О компании",
                        "preview": "ЛАДзавод светотехники производит промышленное светотехническое оборудование.",
                    }
                ],
            },
            wiki_tool_name="doc_search",
            wiki_payload={
                "status": "success",
                "results": [
                    {
                        "relative_path": "common_information_about_company.md",
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "preview": "Электронная почта для общих вопросов: lad@ladled.ru. Телефон: +7 (351) 239-18-11.",
                    }
                ],
            },
            llm_responses_override=[{"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}],
        )

        self.assertIn("lad@ladled.ru", response)
        self.assertIn("239-18-11", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")

    def test_empty_llm_completion_uses_deterministic_application_fallback(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Подбери освещение для спортивного стадиона",
            corp_db_payload={
                "status": "success",
                "kind": "application_recommendation",
                "resolved_application": {
                    "application_key": "sports_high_power",
                    "sphere_name": "Спортивное и освещение высокой мощности",
                },
                "recommended_lamps": [
                    {
                        "name": "LAD LED R500-9-30-6-650LZD",
                        "url": "https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd",
                        "recommendation_reason": "высокая мощность для стадионного света",
                    }
                ],
                "portfolio_examples": [
                    {"name": "Освещение стадиона", "url": "https://ladzavod.ru/portfolio/stadium"}
                ],
                "follow_up_question": "Уточните высоту установки.",
            },
            llm_responses_override=[{"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}],
        )

        self.assertIn("Спортивное и освещение высокой мощности", response)
        self.assertIn("LAD LED R500-9-30-6-650LZD", response)
        self.assertIn("Уточните высоту установки", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(exec_mock.await_args_list[0].args[1]["kind"], "application_recommendation")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")


if __name__ == "__main__":
    unittest.main()
