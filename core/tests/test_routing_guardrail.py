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
    "observability": types.SimpleNamespace(REQUEST_ID=ContextVar("request_id", default="-")),
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
        self.assertEqual(rewritten["entity_types"], ["company"])
        self.assertNotIn("power_w_min", rewritten)
        self.assertNotIn("voltage_kind", rewritten)
        self.assertNotIn("explosion_protected", rewritten)
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
        tool_call_sequence: list[tuple[str, dict]] | None = None,
        llm_responses_override: list[dict] | None = None,
    ) -> tuple[str, AsyncMock, dict]:
        meta: dict = {}
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
        llm_responses = llm_responses_override or [
            self._tool_call_response(name, args) for name, args in (tool_call_sequence or default_sequence)
        ]
        if llm_responses_override is None:
            llm_responses.append(self._final_response("Официальный сайт: https://ladzavod.ru"))

        async def fake_execute_tool(name, args, ctx):
            if name == "corp_db_search":
                metadata = {
                    "runtime_payload_format": "full_json",
                    "bench_payload_format": "compact_company_fact_v1"
                    if str(args.get("kind") or "") == "hybrid_search"
                    else "compact_bench_value_v1",
                    "bench_artifact": {
                        "tool": "corp_db_search",
                        "kind": str(args.get("kind") or corp_db_payload.get("kind") or ""),
                        "payload": {"status": corp_db_payload.get("status"), "results": corp_db_payload.get("results", [])},
                    },
                }
                return _ToolResult(True, output=json.dumps(corp_db_payload, ensure_ascii=False), metadata=metadata)
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
            with patch.dict(
                os.environ,
                {"CORP_DOCS_ROOT": str(Path(tmpdir) / "corp_docs")},
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
                _MODULE, "load_skill_mentions", AsyncMock(return_value="")
            ), patch.object(
                _MODULE, "get_google_email", return_value=None
            ), patch.object(
                _MODULE, "_get_admin_id", return_value=0
            ), patch.object(
                _MODULE, "call_llm", AsyncMock(side_effect=llm_responses)
            ), patch.object(
                _MODULE, "execute_tool", exec_mock
            ), patch.object(
                _MODULE, "run_meta_get", lambda: meta
            ):
                _MODULE.sessions.sessions.clear()
                response = asyncio.run(
                    _MODULE.run_agent(
                        user_id=42,
                        chat_id=42,
                        message=user_message,
                        username="bench",
                        chat_type="private",
                        source="bot",
                    )
                )

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
        self.assertTrue(meta["retrieval_wiki_after_corp_db_success"])
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertFalse(meta["company_fact_fast_path"])
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")

    def test_empty_corp_db_allows_wiki_fallback(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Какой официальный сайт у компании ЛАДзавод светотехники?",
            corp_db_payload={"status": "empty", "kind": "hybrid_search", "results": []},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[1].args[0], "read_file")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertFalse(meta["retrieval_wiki_after_corp_db_success"])
        self.assertEqual(meta["routing_guardrail_hits"], 0)

    def test_explicit_wiki_request_keeps_wiki_available_after_corp_db_success(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Найди в wiki официальный сайт компании ЛАДзавод светотехники и покажи фрагмент.",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "https://ladzavod.ru"}]},
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 2)
        self.assertEqual(exec_mock.await_args_list[1].args[0], "read_file")
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
        self.assertTrue(meta["retrieval_wiki_after_corp_db_success"])
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertFalse(meta["company_fact_fast_path"])
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")

    def test_guardrail_blocks_fallback_after_successful_application_recommendation(self):
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
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")
        self.assertEqual(meta["routing_guardrail_hits"], 1)

    def test_guardrail_blocks_corp_db_after_successful_doc_search_for_document_lookup(self):
        response, exec_mock, meta = self._run_flow(
            user_message="Нужен пожарный сертификат LINE, дай прямую ссылку.",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": [{"value": "unexpected"}]},
            corp_db_args={"kind": "hybrid_search", "profile": "kb_search", "query": "пожарный сертификат line"},
            wiki_tool_name="doc_search",
            wiki_tool_args={"query": "пожарный сертификат line"},
            tool_call_sequence=[
                ("doc_search", {"query": "пожарный сертификат line"}),
                ("corp_db_search", {"kind": "hybrid_search", "profile": "kb_search", "query": "пожарный сертификат line"}),
            ],
        )

        self.assertIn("ladzavod.ru", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "doc_search")
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")
        self.assertEqual(meta["routing_guardrail_hits"], 1)

    def test_route_index_blocks_doc_tool_before_corp_db_for_company_fact(self):
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
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "corp_db_search")
        self.assertEqual(meta["retrieval_route_source"], "corp_db")
        self.assertEqual(meta["retrieval_route_id"], "corp_db.company_profile")
        self.assertEqual(meta["routing_guardrail_hits"], 1)

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
        self.assertEqual(meta["retrieval_route_id"], "corp_db.company_profile")
        self.assertEqual(meta["routing_guardrail_hits"], 1)
        self.assertEqual(meta["retrieval_selected_source"], "corp_db")

    def test_route_index_blocks_corp_db_before_doc_search_for_document_topic(self):
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
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[0], "doc_search")
        self.assertEqual(meta["retrieval_route_source"], "doc_search")
        self.assertEqual(meta["retrieval_route_id"], "doc_search.doc_fire_line")
        self.assertEqual(meta["routing_guardrail_hits"], 1)

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

    def test_company_fact_primary_query_rewrite_keeps_normal_llm_finalization(self):
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
        self.assertFalse(meta["company_fact_fast_path"])
        self.assertTrue(meta["company_fact_payload_relevant"])
        self.assertFalse(meta["company_fact_rendered"])
        self.assertEqual(meta["company_fact_intent_type"], "contacts")
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")
        self.assertEqual(meta["company_fact_runtime_payload_format"], "full_json")
        self.assertEqual(meta["company_fact_bench_payload_format"], "compact_company_fact_v1")

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
        self.assertEqual(exec_mock.await_args_list[1].args[0], "doc_search")
        self.assertFalse(meta["company_fact_payload_relevant"])
        self.assertEqual(meta["company_fact_fallback_reason"], "weak_company_fact_payload")
        self.assertEqual(meta["routing_guardrail_hits"], 0)
        self.assertEqual(meta["retrieval_selected_source"], "doc_search")

    def test_about_company_uses_llm_finalization_with_full_runtime_payload(self):
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
        self.assertFalse(meta["company_fact_fast_path"])
        self.assertEqual(meta["company_fact_finalizer_mode"], "llm")
        self.assertEqual(meta["company_fact_runtime_payload_format"], "full_json")

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
