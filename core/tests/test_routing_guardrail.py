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
    "run_meta": types.SimpleNamespace(run_meta_get=lambda: None, run_meta_update_llm=lambda **kwargs: None),
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

        llm_responses = [
            self._tool_call_response(
                "corp_db_search",
                corp_db_args
                or {
                    "kind": "hybrid_search",
                    "profile": "kb_search",
                    "entity_types": ["company"],
                    "query": "сайт компании",
                },
            ),
            self._tool_call_response(
                wiki_tool_name,
                wiki_tool_args or {"path": "/data/skills/corp-wiki-md-search/SKILL.md"},
            ),
            self._final_response("Официальный сайт: https://ladzavod.ru"),
        ]

        async def fake_execute_tool(name, args, ctx):
            if name == "corp_db_search":
                return _ToolResult(True, output=json.dumps(corp_db_payload, ensure_ascii=False))
            if name == wiki_tool_name:
                return _ToolResult(True, output="wiki preview")
            raise AssertionError(f"unexpected tool call: {name}")

        exec_mock = AsyncMock(side_effect=fake_execute_tool)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
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


if __name__ == "__main__":
    unittest.main()
