import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from admin_auth import AdminTokenNotFound
from incident_replay_smoke import (
    CHAT_REPLAYS,
    ChatReplayExpectation,
    _should_use_docker_exec,
    resolve_chat_identity,
    validate_chat_replay_response,
    validate_doctor_results,
)


class IncidentReplaySmokeTests(unittest.TestCase):
    def test_validate_doctor_results_accepts_all_required_checks(self):
        payload = {
            "corp_db_rfc026_schema_objects": {"passed": True, "message": "ok"},
            "corp_db_rfc026_curated_seed": {"passed": True, "message": "ok"},
            "corp_db_rfc026_parent_links": {"passed": True, "message": "ok"},
        }

        self.assertEqual(validate_doctor_results(payload), [])

    def test_validate_doctor_results_reports_failed_or_missing_checks(self):
        payload = {
            "corp_db_rfc026_schema_objects": {"passed": False, "message": "missing table"},
            "corp_db_rfc026_curated_seed": {"passed": True, "message": "ok"},
        }

        errors = validate_doctor_results(payload)

        self.assertIn("doctor_failed:corp_db_rfc026_schema_objects:missing table", errors)
        self.assertIn("doctor_missing:corp_db_rfc026_parent_links", errors)

    def test_should_use_docker_exec_when_tools_api_health_is_unreachable(self):
        class Args:
            docker_exec = False
            tools_api_url = "http://127.0.0.1:8100"
            timeout_s = 30.0

        with patch("incident_replay_smoke._http_endpoint_available", return_value=False):
            self.assertTrue(_should_use_docker_exec(Args()))

    def test_resolve_chat_identity_authenticates_admin_access(self):
        with patch("incident_replay_smoke.admin_headers", return_value={"X-Admin-Token": "secret"}), patch(
            "incident_replay_smoke.http_json", return_value=(200, {"admin_id": 42})
        ) as http_json:
            self.assertEqual(resolve_chat_identity("http://core:4000", 5.0, 0, 0), (42, 42))

        self.assertEqual(http_json.call_args.kwargs["headers"]["X-Admin-Token"], "secret")

    def test_resolve_chat_identity_reports_missing_admin_token(self):
        with patch(
            "incident_replay_smoke.admin_headers",
            side_effect=AdminTokenNotFound("admin token not found"),
        ):
            with self.assertRaisesRegex(AdminTokenNotFound, "admin token not found"):
                resolve_chat_identity("http://core:4000", 5.0, 0, 0)

    def test_chat_replay_matrix_contains_scenario_specific_route_contracts(self):
        self.assertEqual(
            [(case.message, case.expected_route_id, case.expected_tool_args) for case in CHAT_REPLAYS],
            [
                (
                    "2ex световой поток не менее 11540 Лм",
                    "corp_db.lamp_filters",
                    {"kind": "lamp_filters", "series": "LAD LED R500 2Ex", "flux_lm_min": 11540},
                ),
                (
                    "2 ex световой поток не менее 11540 Лм",
                    "corp_db.lamp_filters",
                    {"kind": "lamp_filters", "series": "LAD LED R500 2Ex", "flux_lm_min": 11540},
                ),
                (
                    "LAD LED R500 2Ex, поток от 11540 лм",
                    "corp_db.lamp_filters",
                    {"kind": "lamp_filters", "series": "LAD LED R500 2Ex", "flux_lm_min": 11540},
                ),
                (
                    "LAD LED R320 Ex, поток от 11540 лм",
                    "corp_db.lamp_filters",
                    {"kind": "lamp_filters", "series": "LAD LED R320 Ex", "flux_lm_min": 11540},
                ),
                (
                    "взрывозащищенный светильник, поток от 11540 лм",
                    "corp_db.lamp_filters",
                    {"kind": "lamp_filters", "explosion_protected": True, "flux_lm_min": 11540},
                ),
                (
                    "LAD LED R320-2-10G-230AC-50K Ex",
                    "corp_db.catalog_lookup",
                    {"kind": "lamp_exact", "name": "LAD LED R320-2-10G-230AC-50K Ex"},
                ),
            ],
        )

    def test_validate_chat_replay_response_accepts_exact_series_route(self):
        expected = ChatReplayExpectation(
            slug="compact_2ex",
            message="2ex световой поток не менее 11540 Лм",
            expected_route_id="corp_db.lamp_filters",
            expected_tool_args={"kind": "lamp_filters", "series": "LAD LED R500 2Ex", "flux_lm_min": 11540},
            forbidden_answer_tokens=("LAD LED R320",),
        )
        payload = {
            "response": "Подходят модели LAD LED R500-4-O-12-140L 2Ex.",
            "meta": {
                "status": "ok",
                "request_id": "req-1",
                "retrieval_route_id": "corp_db.lamp_filters",
                "retrieval_selected_route_kind": "corp_table",
                "retrieval_validation_status": "ok",
                "retrieval_selected_source": "corp_db",
                "retrieval_selected_tool_args": {
                    "kind": "lamp_filters",
                    "series": "LAD LED R500 2Ex",
                    "flux_lm_min": 11540,
                },
                "retrieval_used_fallback_route_id": "",
                "routing_guardrail_hits": 0,
                "tools_used": ["corp_db_search"],
            },
        }

        self.assertEqual(validate_chat_replay_response(payload, expected, "req-1"), [])

    def test_validate_chat_replay_response_rejects_wrong_series_fallback_and_answer(self):
        expected = ChatReplayExpectation(
            slug="compact_2ex",
            message="2ex световой поток не менее 11540 Лм",
            expected_route_id="corp_db.lamp_filters",
            expected_tool_args={"kind": "lamp_filters", "series": "LAD LED R500 2Ex", "flux_lm_min": 11540},
            forbidden_answer_tokens=("LAD LED R320",),
        )
        payload = {
            "answer": "Подойдёт LAD LED R320-2-10G-230AC-50K Ex.",
            "meta": {
                "status": "ok",
                "request_id": "req-2",
                "retrieval_route_id": "corp_db.catalog_lookup",
                "retrieval_selected_route_kind": "corp_table",
                "retrieval_validation_status": "error",
                "retrieval_selected_source": "corp_db",
                "retrieval_selected_tool_args": {"series": "LAD LED R320 Ex"},
                "retrieval_used_fallback_route_id": "corp_db.catalog_lookup",
                "routing_guardrail_hits": 1,
                "tools_used": ["corp_db_search"],
            },
        }

        errors = validate_chat_replay_response(payload, expected, "req-2")

        self.assertIn("compact_2ex:route_id=corp_db.catalog_lookup", errors)
        self.assertIn("compact_2ex:validation_status=error", errors)
        self.assertIn("compact_2ex:fallback=corp_db.catalog_lookup", errors)
        self.assertIn("compact_2ex:guardrail_hits=1", errors)
        self.assertIn("compact_2ex:tool_arg.kind=None", errors)
        self.assertIn("compact_2ex:tool_arg.series=LAD LED R320 Ex", errors)
        self.assertIn("compact_2ex:tool_arg.flux_lm_min=None", errors)
        self.assertIn("compact_2ex:forbidden_answer_token=LAD LED R320", errors)

    def test_validate_chat_replay_response_keeps_generic_ex_without_specific_series(self):
        expected = ChatReplayExpectation(
            slug="generic_ex",
            message="взрывозащищенный светильник, поток от 11540 лм",
            expected_route_id="corp_db.lamp_filters",
            expected_tool_args={"kind": "lamp_filters", "explosion_protected": True, "flux_lm_min": 11540},
        )
        payload = {
            "response": "Нашёл несколько взрывозащищённых светильников.",
            "meta": {
                "status": "ok",
                "request_id": "req-3",
                "retrieval_route_id": "corp_db.lamp_filters",
                "retrieval_selected_route_kind": "corp_table",
                "retrieval_validation_status": "ok",
                "retrieval_selected_source": "corp_db",
                "retrieval_selected_tool_args": {
                    "kind": "lamp_filters",
                    "explosion_protected": True,
                    "flux_lm_min": 11540,
                },
                "retrieval_used_fallback_route_id": "",
                "routing_guardrail_hits": 0,
                "tools_used": ["corp_db_search"],
            },
        }

        self.assertEqual(validate_chat_replay_response(payload, expected, "req-3"), [])

    def test_validate_chat_replay_response_accepts_exact_sku_catalog_result(self):
        expected = CHAT_REPLAYS[-1]
        payload = {
            "response": "LAD LED R320-2-10G-230AC-50K Ex относится к серии LAD LED R320 Ex.",
            "meta": {
                "status": "ok",
                "request_id": "req-4",
                "retrieval_route_id": "corp_db.catalog_lookup",
                "retrieval_selected_route_kind": "corp_table",
                "retrieval_validation_status": "ok",
                "retrieval_selected_source": "corp_db",
                "retrieval_selected_tool_args": {
                    "kind": "lamp_exact",
                    "name": "LAD LED R320-2-10G-230AC-50K Ex",
                },
                "retrieval_used_fallback_route_id": "",
                "routing_guardrail_hits": 0,
                "tools_used": ["corp_db_search"],
                "primary_artifact": {
                    "tool": "corp_db_search",
                    "payload": {
                        "results": [
                            {
                                "name": "LAD LED R320-2-10G-230AC-50K Ex",
                                "series_name": "LAD LED R320 Ex",
                                "explosion_protection_marking": "1Ex mb IIC T6 Gb X",
                            }
                        ]
                    },
                },
            },
        }

        self.assertEqual(validate_chat_replay_response(payload, expected, "req-4"), [])

    def test_validate_chat_replay_response_rejects_exact_sku_2ex_or_r500_result(self):
        expected = CHAT_REPLAYS[-1]
        payload = {
            "response": "Это LAD LED R500 2Ex.",
            "meta": {
                "status": "ok",
                "request_id": "req-5",
                "retrieval_route_id": "corp_db.catalog_lookup",
                "retrieval_selected_route_kind": "corp_table",
                "retrieval_validation_status": "ok",
                "retrieval_selected_source": "corp_db",
                "retrieval_selected_tool_args": {
                    "kind": "lamp_exact",
                    "name": "LAD LED R320-2-10G-230AC-50K Ex",
                },
                "retrieval_used_fallback_route_id": "",
                "routing_guardrail_hits": 0,
                "tools_used": ["corp_db_search"],
                "bench_artifacts": [
                    {
                        "tool": "corp_db_search",
                        "payload": {
                            "results": [
                                {
                                    "series_name": "LAD LED R500 2Ex",
                                    "explosion_protection_marking": "2Ex mb IIC T6 Gb X",
                                }
                            ]
                        },
                    }
                ],
            },
        }

        errors = validate_chat_replay_response(payload, expected, "req-5")

        self.assertIn("r320_module_two_counterexample:missing_answer_token=R320", errors)
        self.assertIn("r320_module_two_counterexample:forbidden_answer_token=R500", errors)
        self.assertIn("r320_module_two_counterexample:forbidden_answer_token=2Ex", errors)
        self.assertIn("r320_module_two_counterexample:result.series_name=LAD LED R500 2Ex", errors)
        self.assertIn(
            "r320_module_two_counterexample:result.explosion_protection_marking=2Ex mb IIC T6 Gb X",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
