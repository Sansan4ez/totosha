import unittest

from bench.bench_lib import routing_accuracy_summary


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
        self.assertEqual(summary["by_route"]["corp_kb.company_common"], {"correct": 1, "total": 1, "accuracy": 1.0})
        self.assertEqual(summary["by_family"]["company_info"], {"correct": 1, "total": 1, "accuracy": 1.0})
        self.assertEqual(summary["mismatches"], [])

    def test_mismatched_route_is_recorded_and_family_not_credited(self):
        dataset = [{"id": "c1", "routing": {"route_id": "corp_kb.series_description", "family_id": "company_info"}}]
        by_case = {"c1": {"meta": {"retrieval_route_id": "corp_db.catalog_lookup"}}}

        summary = routing_accuracy_summary(dataset, by_case)

        self.assertEqual(summary["by_route"]["corp_kb.series_description"], {"correct": 0, "total": 1, "accuracy": 0.0})
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

        self.assertEqual(summary["by_route"]["corp_kb.company_common"], {"correct": 1, "total": 2, "accuracy": 0.5})


if __name__ == "__main__":
    unittest.main()
