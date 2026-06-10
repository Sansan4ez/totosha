import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_meta import (
    BENCH_ARTIFACTS_MAX_COUNT,
    run_meta_append_artifact,
    run_meta_reset,
    run_meta_set,
)
from tool_output_policy import EXECUTION_MODE_BENCHMARK, EXECUTION_MODE_RUNTIME


class BenchArtifactRunMetaTests(unittest.TestCase):
    def test_append_artifact_sets_primary_and_enforces_count_limit(self):
        meta = {
            "execution_mode": EXECUTION_MODE_BENCHMARK,
            "bench_artifacts": [],
            "primary_artifact": None,
            "bench_artifacts_total_bytes": 0,
            "bench_artifacts_dropped": 0,
        }
        token = run_meta_set(meta)
        try:
            for index in range(BENCH_ARTIFACTS_MAX_COUNT + 1):
                run_meta_append_artifact({"tool": "corp_db_search", "payload": {"index": index}})
        finally:
            run_meta_reset(token)

        self.assertEqual(len(meta["bench_artifacts"]), BENCH_ARTIFACTS_MAX_COUNT)
        self.assertEqual(meta["primary_artifact"]["payload"]["index"], 0)
        self.assertEqual(meta["bench_artifacts_dropped"], 1)

    def test_append_artifact_enforces_total_size_limit(self):
        meta = {
            "execution_mode": EXECUTION_MODE_BENCHMARK,
            "bench_artifacts": [],
            "primary_artifact": None,
            "bench_artifacts_total_bytes": 0,
            "bench_artifacts_dropped": 0,
        }
        token = run_meta_set(meta)
        try:
            ok = run_meta_append_artifact({"tool": "doc_search", "payload": {"preview": "x" * (128 * 1024)}})
        finally:
            run_meta_reset(token)

        self.assertFalse(ok)
        self.assertEqual(meta["bench_artifacts"], [])
        self.assertEqual(meta["bench_artifacts_dropped"], 1)

    def test_append_artifact_is_disabled_in_runtime_mode(self):
        meta = {
            "execution_mode": EXECUTION_MODE_RUNTIME,
            "bench_artifacts": [],
            "primary_artifact": None,
            "bench_artifacts_total_bytes": 0,
            "bench_artifacts_dropped": 0,
        }
        token = run_meta_set(meta)
        try:
            ok = run_meta_append_artifact({"tool": "corp_db_search", "payload": {"index": 1}})
        finally:
            run_meta_reset(token)

        self.assertFalse(ok)
        self.assertEqual(meta["bench_artifacts"], [])
        self.assertIsNone(meta["primary_artifact"])
        self.assertEqual(meta["bench_artifacts_total_bytes"], 0)
        self.assertEqual(meta["bench_artifacts_dropped"], 0)


if __name__ == "__main__":
    unittest.main()
