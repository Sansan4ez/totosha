import unittest

from bench.bench_lib import routing_accuracy_summary


def test_argument_validity_excludes_missing_and_skipped():
    statuses = ["valid", "repaired", "failed", "skipped", "", "unexpected"]
    dataset = [{"id": str(i), "routing": {"route_id": "r"}} for i in range(len(statuses))]
    rows = {str(i): {"meta": {"route_argument_builder_status": status}} for i, status in enumerate(statuses)}
    route = routing_accuracy_summary(dataset, rows)["by_route"]["r"]
    assert route["argument_valid"] == 1
    assert route["argument_scored"] == 3
    assert route["argument_validity_rate"] == 0.3333
    for samples, expected in [(["valid", "failed"], 0.5), (["repaired"], 0.0)]:
        cases = [{"id": str(i), "routing": {"route_id": "r"}} for i in range(len(samples))]
        results = {str(i): {"meta": {"route_argument_builder_status": status}} for i, status in enumerate(samples)}
        assert routing_accuracy_summary(cases, results)["by_route"]["r"]["argument_validity_rate"] == expected
    assert routing_accuracy_summary(dataset, {})["by_route"]["r"]["argument_validity_rate"] is None



class RoutingAccuracySummaryTests(unittest.TestCase):
    def test_cases_without_expected_route_id_are_skipped(self):
        dataset = [{"id": "c1", "routing": {"intent": "company_fact"}}]
        summary = routing_accuracy_summary(dataset, by_case={})

        self.assertEqual(summary["scored_cases"], 0)
        self.assertEqual(summary["by_route"], {})
        self.assertEqual(summary["by_family"], {})
        self.assertEqual(summary["mismatches"], [])

    def test_matching_route_counts_as_correct(self):
        dataset = [{"id": "c1", "routing": {"route_id": "corp_kb.company_common", "family_id": "company_info"}}]
        by_case = {"c1": {"meta": {"retrieval_route_id": "corp_kb.company_common"}}}

        summary = routing_accuracy_summary(dataset, by_case)

        self.assertEqual(summary["scored_cases"], 1)
        self.assertEqual(summary["by_route"]["corp_kb.company_common"], {"correct": 1, "total": 1, "accuracy": 1.0, "argument_valid": 0, "argument_scored": 0, "argument_validity_rate": None})
        self.assertEqual(summary["by_family"]["company_info"], {"correct": 1, "total": 1, "accuracy": 1.0})
        self.assertEqual(summary["mismatches"], [])

    def test_mismatched_route_is_recorded_and_family_not_credited(self):
        dataset = [{"id": "c1", "routing": {"route_id": "corp_kb.series_description", "family_id": "company_info"}}]
        by_case = {"c1": {"meta": {"retrieval_route_id": "corp_db.catalog_lookup"}}}

        summary = routing_accuracy_summary(dataset, by_case)

        self.assertEqual(summary["by_route"]["corp_kb.series_description"], {"correct": 0, "total": 1, "accuracy": 0.0, "argument_valid": 0, "argument_scored": 0, "argument_validity_rate": None})
        self.assertEqual(summary["by_family"]["company_info"], {"correct": 0, "total": 1, "accuracy": 0.0})
        self.assertEqual(
            summary["mismatches"],
            [{"case_id": "c1", "expected_route_id": "corp_kb.series_description", "actual_route_id": "corp_db.catalog_lookup"}],
        )

    def test_missing_result_row_counts_as_mismatch_not_crash(self):
        dataset = [{"id": "c1", "routing": {"route_id": "corp_kb.company_common"}}]

        summary = routing_accuracy_summary(dataset, by_case={})

        self.assertEqual(summary["by_route"]["corp_kb.company_common"]["correct"], 0)
        self.assertEqual(summary["mismatches"][0]["actual_route_id"], "(missing)")

    def test_leaf_route_id_takes_priority_over_collapsed_knowledge_route_id(self):
        # retrieval_route_id is collapsed to the shared knowledge_route_id for corp_kb.* routes
        # (company_common and series_description both report "corp_kb.company_common" there);
        # retrieval_leaf_route_id carries the selector's actual leaf choice and must be preferred.
        dataset = [{"id": "c1", "routing": {"route_id": "corp_kb.series_description", "family_id": "company_info"}}]
        by_case = {
            "c1": {
                "meta": {
                    "retrieval_route_id": "corp_kb.company_common",
                    "retrieval_leaf_route_id": "corp_kb.series_description",
                }
            }
        }

        summary = routing_accuracy_summary(dataset, by_case)

        self.assertEqual(summary["by_route"]["corp_kb.series_description"], {"correct": 1, "total": 1, "accuracy": 1.0, "argument_valid": 0, "argument_scored": 0, "argument_validity_rate": None})
        self.assertEqual(summary["mismatches"], [])

    def test_aggregates_across_multiple_cases_for_the_same_route(self):
        dataset = [
            {"id": "c1", "routing": {"route_id": "corp_kb.company_common"}},
            {"id": "c2", "routing": {"route_id": "corp_kb.company_common"}},
        ]
        by_case = {
            "c1": {"meta": {"retrieval_route_id": "corp_kb.company_common"}},
            "c2": {"meta": {"retrieval_route_id": "corp_kb.series_description"}},
        }

        summary = routing_accuracy_summary(dataset, by_case)

        self.assertEqual(summary["by_route"]["corp_kb.company_common"], {"correct": 1, "total": 2, "accuracy": 0.5, "argument_valid": 0, "argument_scored": 0, "argument_validity_rate": None})


if __name__ == "__main__":
    unittest.main()
