import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incident_replay_smoke import (
    ChatReplayExpectation,
    _should_use_docker_exec,
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

    def test_validate_chat_replay_response_accepts_expected_meta(self):
        expected = ChatReplayExpectation(
            slug="series_list",
            message="Какие у вас есть серии светильников?",
            expected_route_id="corp_kb.company_common",
            expected_route_kind="corp_table",
            expected_tool="corp_db_search",
            expected_business_family_id="company_info",
            expected_leaf_route_id="series_description",
            expected_route_stage="stage2_specialized",
        )
        payload = {
            "response": "Есть серии LAD LED R500 и LAD LED LINE.",
            "meta": {
                "status": "ok",
                "request_id": "req-1",
                "retrieval_route_id": "corp_kb.company_common",
                "retrieval_selected_route_kind": "corp_table",
                "retrieval_business_family_id": "company_info",
                "retrieval_leaf_route_id": "series_description",
                "retrieval_route_stage": "stage2_specialized",
                "retrieval_validation_status": "ok",
                "retrieval_selected_source": "corp_db",
                "tools_used": ["corp_db_search"],
            },
        }

        self.assertEqual(validate_chat_replay_response(payload, expected, "req-1"), [])

    def test_validate_chat_replay_response_reports_route_drift(self):
        expected = ChatReplayExpectation(
            slug="series_descriptions",
            message="В общей базе есть описание всех серий",
            expected_route_id="corp_kb.company_common",
            expected_route_kind="corp_table",
            expected_tool="corp_db_search",
            expected_business_family_id="company_info",
            expected_leaf_route_id="series_description",
            expected_route_stage="stage2_specialized",
        )
        payload = {
            "answer": "",
            "meta": {
                "status": "ok",
                "request_id": "req-2",
                "retrieval_route_id": "doc_search.document_lookup",
                "retrieval_selected_route_kind": "doc_domain",
                "retrieval_business_family_id": "document_lookup",
                "retrieval_leaf_route_id": "document_domain_lookup",
                "retrieval_route_stage": "stage1_general",
                "retrieval_validation_status": "error",
                "retrieval_selected_source": "doc_search",
                "tools_used": ["doc_search"],
            },
        }

        errors = validate_chat_replay_response(payload, expected, "req-2")

        self.assertIn("series_descriptions:route_id=doc_search.document_lookup", errors)
        self.assertIn("series_descriptions:route_kind=doc_domain", errors)
        self.assertIn("series_descriptions:business_family=document_lookup", errors)
        self.assertIn("series_descriptions:leaf_route_id=document_domain_lookup", errors)
        self.assertIn("series_descriptions:route_stage=stage1_general", errors)
        self.assertIn("series_descriptions:validation_status=error", errors)
        self.assertIn("series_descriptions:selected_source=doc_search", errors)
        self.assertIn("series_descriptions:tools_used=['doc_search']", errors)
        self.assertIn("series_descriptions:empty_answer", errors)


if __name__ == "__main__":
    unittest.main()
