import json
import unittest

import core.tests.test_routing_guardrail as guardrail

_MODULE = guardrail._MODULE


class Rfc027LlmOnlyTests(unittest.TestCase):
    def setUp(self):
        self.helper = guardrail.RoutingGuardrailTests()

    def _selector_response(self, *, family_id: str, route_id: str, tool_args: dict | None = None) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_family_id": family_id,
                                "selected_route_id": route_id,
                                "confidence": "high",
                                "reason": "test selector",
                                "tool_args": dict(tool_args or {}),
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ],
            "model": "selector-test-model",
        }

    def test_selector_outage_fails_closed(self):
        response, exec_mock, meta = self.helper._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": []},
            llm_responses_override=[{"error": "selector upstream unavailable"}],
            route_selector_enabled=True,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 0)
        self.assertEqual(meta["route_selector_status"], "unavailable")
        self.assertEqual(meta["retrieval_close_reason"], "route_selector_unavailable")

    def test_selector_disabled_fails_closed(self):
        response, exec_mock, meta = self.helper._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={"status": "success", "kind": "hybrid_search", "results": []},
            route_selector_enabled=False,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 0)
        self.assertEqual(meta["route_selector_status"], "disabled")
        self.assertEqual(meta["retrieval_close_reason"], "route_selector_disabled")

    def test_finalizer_outage_fails_closed(self):
        selector_response = self._selector_response(
            family_id="company_info",
            route_id="corp_kb.company_common",
            tool_args={"query": "сертификаты декларации", "topic_facets": ["certification"]},
        )
        response, exec_mock, meta = self.helper._run_flow(
            user_message="какие есть сертификаты?",
            corp_db_payload={
                "status": "success",
                "kind": "hybrid_search",
                "results": [{"heading": "Сертификация", "preview": "Сертификаты и декларации соответствия."}],
            },
            llm_responses_override=[selector_response, {"error": "finalizer upstream unavailable"}],
            route_selector_enabled=True,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["finalizer_mode"], "unavailable")
        self.assertEqual(meta["retrieval_close_reason"], "finalizer_unavailable")

    def test_successful_company_fact_runtime_and_benchmark_use_llm_finalization(self):
        selector_response = self._selector_response(
            family_id="company_info",
            route_id="corp_kb.company_common",
            tool_args={"query": "контакты компании", "topic_facets": ["contacts"]},
        )
        final_response = self.helper._final_response(
            "Телефон: +7 (351) 239-18-11\nEmail: lad@ladled.ru\nСайт: https://ladzavod.ru"
        )

        runtime_response, runtime_exec, runtime_meta = self.helper._run_flow(
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
            llm_responses_override=[selector_response, final_response],
            execution_mode="runtime",
            route_selector_enabled=True,
        )
        benchmark_response, benchmark_exec, benchmark_meta = self.helper._run_flow(
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
            llm_responses_override=[selector_response, final_response],
            execution_mode="benchmark",
            route_selector_enabled=True,
        )

        self.assertIn("239-18-11", runtime_response)
        self.assertIn("239-18-11", benchmark_response)
        self.assertEqual(runtime_exec.await_count, 1)
        self.assertEqual(benchmark_exec.await_count, 1)
        self.assertEqual(runtime_meta["finalizer_mode"], "llm")
        self.assertEqual(runtime_meta["company_fact_finalizer_mode"], "llm")
        self.assertEqual(benchmark_meta["finalizer_mode"], "llm")
        self.assertEqual(benchmark_meta["company_fact_finalizer_mode"], "llm")

    def test_successful_application_route_uses_llm_finalization(self):
        selector_response = self._selector_response(
            family_id="catalog",
            route_id="corp_db.application_recommendation",
            tool_args={"query": "стадион"},
        )
        response, exec_mock, meta = self.helper._run_flow(
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
                "results": [{"name": "LAD LED R500-9-30-6-650LZD"}],
            },
            llm_responses_override=[
                selector_response,
                self.helper._final_response(
                    "Для спортивного стадиона подойдёт LAD LED R500-9-30-6-650LZD. Уточните высоту установки."
                ),
            ],
            route_selector_enabled=True,
        )

        self.assertIn("LAD LED R500-9-30-6-650LZD", response)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(exec_mock.await_args_list[0].args[1]["kind"], "application_recommendation")
        self.assertEqual(meta["finalizer_mode"], "llm")
        self.assertEqual(meta["retrieval_close_reason"], "route_selector_payload_sufficient")

    def test_successful_document_and_portfolio_routes_use_llm_finalization(self):
        document_selector = self._selector_response(
            family_id="documents",
            route_id="corp_db.certificate_by_lamp_name",
            tool_args={"name": "NL Nova"},
        )
        document_response, document_exec, document_meta = self.helper._run_flow(
            user_message="Нужен сертификат NL Nova",
            corp_db_payload={
                "status": "success",
                "kind": "lamp_exact",
                "results": [
                    {
                        "name": "NL Nova",
                        "document_type": "certificate",
                        "url": "https://ladzavod.ru/certs/nl-nova.pdf",
                    }
                ],
            },
            llm_responses_override=[
                document_selector,
                self.helper._final_response("Сертификат NL Nova: https://ladzavod.ru/certs/nl-nova.pdf"),
            ],
            route_selector_enabled=True,
        )
        portfolio_selector = self._selector_response(
            family_id="portfolio",
            route_id="corp_db.portfolio_by_sphere",
            tool_args={"sphere": "РЖД"},
        )
        portfolio_response, portfolio_exec, portfolio_meta = self.helper._run_flow(
            user_message="Какие проекты есть для РЖД?",
            corp_db_payload={
                "status": "success",
                "kind": "portfolio_by_sphere",
                "results": [{"name": "Логистический центр РЖД", "url": "https://ladzavod.ru/portfolio/rzd"}],
            },
            llm_responses_override=[
                portfolio_selector,
                self.helper._final_response("Для РЖД есть проект Логистический центр РЖД: https://ladzavod.ru/portfolio/rzd"),
            ],
            route_selector_enabled=True,
        )

        self.assertIn("nl-nova.pdf", document_response)
        self.assertEqual(document_exec.await_count, 2)
        self.assertEqual(document_exec.await_args_list[1].args[1]["name"], "NL Nova")
        self.assertEqual(document_meta["finalizer_mode"], "llm")
        self.assertEqual(document_meta["retrieval_used_fallback_scope"], "family_local")
        self.assertIn("РЖД", portfolio_response)
        self.assertEqual(portfolio_exec.await_count, 1)
        self.assertEqual(portfolio_exec.await_args_list[0].args[1]["kind"], "portfolio_by_sphere")
        self.assertEqual(portfolio_meta["finalizer_mode"], "llm")

    def test_empty_completion_after_successful_retrieval_fails_closed(self):
        selector_response = self._selector_response(
            family_id="company_info",
            route_id="corp_kb.company_common",
            tool_args={"query": "контакты компании", "topic_facets": ["contacts"]},
        )
        response, exec_mock, meta = self.helper._run_flow(
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
            llm_responses_override=[selector_response, {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}],
            route_selector_enabled=True,
        )

        self.assertEqual(response, _MODULE.ROUTE_SELECTOR_UNAVAILABLE_MESSAGE)
        self.assertEqual(exec_mock.await_count, 1)
        self.assertEqual(meta["finalizer_mode"], "unavailable")
        self.assertEqual(meta["company_fact_finalizer_mode"], "unavailable")


if __name__ == "__main__":
    unittest.main()
