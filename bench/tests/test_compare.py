import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class BenchCompareTests(unittest.TestCase):
    def test_compare_marks_missing_artifact_and_algorithmic_only_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dataset = root / "dataset.jsonl"
            legacy = root / "legacy.jsonl"
            algorithmic = root / "algorithmic.jsonl"
            json_out = root / "compare.json"

            dataset.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": "case-ok",
                                "question": "q",
                                "golden": {"checks": [{"type": "contains_any", "value": ["18.3"]}]},
                                "validation": {
                                    "mode": "algorithmic",
                                    "artifact_selector": {"tool": "corp_db_search", "kind": "lamp_exact"},
                                    "checks": [{"type": "number_eq", "path": "results[0].weight_kg", "value": 18.3, "tolerance": 0.2}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "id": "case-missing",
                                "question": "q2",
                                "golden": {"checks": [{"type": "contains_any", "value": ["ok"]}]},
                                "validation": {
                                    "mode": "algorithmic",
                                    "artifact_selector": {"tool": "corp_db_search", "kind": "lamp_exact"},
                                    "checks": [{"type": "number_eq", "path": "results[0].weight_kg", "value": 5.6, "tolerance": 0.2}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            legacy.write_text(
                "\n".join(
                    [
                        json.dumps({"case_id": "case-ok", "status": "ok", "answer": "Вес 18.3 кг", "meta": {}}),
                        json.dumps({"case_id": "case-missing", "status": "ok", "answer": "ok", "meta": {}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            algorithmic.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "case_id": "case-ok",
                                "status": "ok",
                                "answer": "",
                                "meta": {
                                    "bench_artifacts": [
                                        {
                                            "tool": "corp_db_search",
                                            "kind": "lamp_exact",
                                            "payload": {"results": [{"weight_kg": 18.3}]},
                                        }
                                    ]
                                },
                            }
                        ),
                        json.dumps({"case_id": "case-missing", "status": "ok", "answer": "", "meta": {}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            subprocess.run(
                [
                    "python3",
                    "bench/bench_compare.py",
                    "--dataset",
                    str(dataset),
                    "--legacy-results",
                    str(legacy),
                    "--algorithmic-results",
                    str(algorithmic),
                    "--json-out",
                    str(json_out),
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[2],
            )

            payload = json.loads(json_out.read_text(encoding="utf-8"))
            by_case = {row["case_id"]: row for row in payload["cases"]}
            self.assertEqual(by_case["case-ok"]["comparison_status"], "same_pass")
            self.assertEqual(by_case["case-missing"]["comparison_status"], "missing_artifact")


if __name__ == "__main__":
    unittest.main()
