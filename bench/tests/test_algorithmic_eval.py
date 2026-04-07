import unittest

from bench.bench_lib import (
    evaluate_case_result,
    get_execution,
    get_validation,
    resolve_path_values,
    select_artifact,
)


class BenchAlgorithmicEvalTests(unittest.TestCase):
    def test_get_execution_and_validation_are_backward_compatible(self):
        case = {
            "id": "legacy-case",
            "golden": {"checks": [{"type": "contains_any", "value": ["ok"]}]},
        }

        self.assertEqual(get_execution(case)["mode"], "agent_chat")
        self.assertEqual(get_validation(case)["mode"], "legacy_text")

    def test_resolve_path_values_supports_indexes_and_wildcards(self):
        payload = {
            "results": [
                {"name": "A", "url": "https://a"},
                {"name": "B", "url": "https://b"},
            ],
            "resolved_application": {"application_key": "warehouse"},
        }

        values, error = resolve_path_values(payload, "results[*].url")
        self.assertIsNone(error)
        self.assertEqual(values, ["https://a", "https://b"])

        values, error = resolve_path_values(payload, "resolved_application.application_key")
        self.assertIsNone(error)
        self.assertEqual(values, ["warehouse"])

    def test_select_artifact_uses_primary_or_selector(self):
        row = {
            "meta": {
                "primary_artifact": {"tool": "corp_db_search", "kind": "lamp_exact", "payload": {"status": "success"}},
                "bench_artifacts": [
                    {"tool": "corp_db_search", "kind": "lamp_exact", "payload": {"status": "success"}},
                    {"tool": "doc_search", "kind": "doc_search", "payload": {"status": "success"}},
                ],
            }
        }

        artifact, payload, error = select_artifact(row, {"tool": "doc_search", "kind": "doc_search"})
        self.assertIsNone(error)
        self.assertEqual(artifact["tool"], "doc_search")
        self.assertEqual(payload["status"], "success")

    def test_select_artifact_can_combine_all_matching_artifacts(self):
        row = {
            "meta": {
                "bench_artifacts": [
                    {
                        "tool": "doc_search",
                        "kind": "doc_search",
                        "payload": {"status": "success", "query": "q1", "results": [{"preview": "R500 cert"}]},
                    },
                    {
                        "tool": "doc_search",
                        "kind": "doc_search",
                        "payload": {"status": "success", "query": "q2", "results": [{"preview": "R700 cert"}]},
                    },
                ],
            }
        }

        artifact, payload, error = select_artifact(row, {"tool": "doc_search", "kind": "doc_search", "all_matches": True})
        self.assertIsNone(error)
        self.assertEqual(artifact["combined_artifacts"], 2)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["queries"], ["q1", "q2"])

    def test_evaluate_case_result_runs_algorithmic_checks(self):
        case = {
            "id": "app-case",
            "validation": {
                "mode": "algorithmic",
                "artifact_selector": {"tool": "corp_db_search", "kind": "application_recommendation"},
                "checks": [
                    {"type": "equals", "path": "resolved_application.application_key", "value": "sports_high_power"},
                    {"type": "len_gte", "path": "recommended_lamps", "value": 2},
                    {"type": "all_prefix", "path": "recommended_lamps[*].url", "value": "https://ladzavod.ru/catalog/"},
                ],
            },
            "routing": {"selected_source": "corp_db"},
        }
        row = {
            "status": "ok",
            "meta": {
                "retrieval_selected_source": "corp_db",
                "bench_artifacts": [
                    {
                        "tool": "corp_db_search",
                        "kind": "application_recommendation",
                        "payload": {
                            "resolved_application": {"application_key": "sports_high_power"},
                            "recommended_lamps": [
                                {"url": "https://ladzavod.ru/catalog/r500"},
                                {"url": "https://ladzavod.ru/catalog/r700"},
                            ],
                        },
                    }
                ],
            },
        }

        evaluation = evaluate_case_result(case, row)
        self.assertTrue(evaluation["passed"])
        self.assertEqual(evaluation["errors"], [])


if __name__ == "__main__":
    unittest.main()
