import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "corp_db_lamp_filters_latency.py"
SPEC = importlib.util.spec_from_file_location("corp_db_lamp_filters_latency", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def artifact(p95_by_case, *, warmups=5, measured=30, success_rate=1.0):
    return {
        "cases": [
            {
                "case_id": case_id,
                "metrics": {
                    "warmup_count": warmups,
                    "sample_count": measured,
                    "http_success_rate": success_rate,
                    "application_error_count": 0 if success_rate == 1.0 else 1,
                    "p95_ms": p95,
                },
            }
            for case_id, p95 in p95_by_case.items()
        ]
    }


class LampFiltersLatencyTest(unittest.TestCase):
    def test_nearest_rank_p95_uses_measured_tail(self):
        samples = [float(value) for value in range(1, 31)]
        self.assertEqual(MODULE.percentile_nearest_rank(samples, 0.95), 29.0)

    def test_compare_passes_both_canonical_cases_within_budgets(self):
        baseline = artifact({"r500_2ex": 100.0, "r320_ex": 80.0})
        current = artifact({"r500_2ex": 119.9, "r320_ex": 90.0})
        result = MODULE.evaluate_artifacts(baseline, current)
        self.assertTrue(result["passed"])
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_compare_fails_relative_or_absolute_budget(self):
        baseline = artifact({"r500_2ex": 100.0, "r320_ex": 450.0})
        current = artifact({"r500_2ex": 121.0, "r320_ex": 501.0})
        result = MODULE.evaluate_artifacts(baseline, current)
        self.assertFalse(result["passed"])
        checks = {check["case_id"]: check for check in result["checks"]}
        self.assertFalse(checks["r500_2ex"]["relative_p95_ok"])
        self.assertFalse(checks["r320_ex"]["absolute_p95_ok"])

    def test_compare_rejects_insufficient_samples_or_errors(self):
        baseline = artifact({"r500_2ex": 100.0, "r320_ex": 80.0})
        current = artifact(
            {"r500_2ex": 90.0, "r320_ex": 70.0},
            warmups=4,
            measured=29,
            success_rate=29 / 30,
        )
        result = MODULE.evaluate_artifacts(baseline, current)
        self.assertFalse(result["passed"])
        self.assertTrue(all(not check["sample_size_ok"] for check in result["checks"]))
        self.assertTrue(all(not check["success_rate_ok"] for check in result["checks"]))


if __name__ == "__main__":
    unittest.main()
