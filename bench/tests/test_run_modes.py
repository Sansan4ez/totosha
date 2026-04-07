import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench import bench_run


class BenchRunModesTests(unittest.TestCase):
    def test_direct_tool_mode_writes_artifact_aware_result_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.jsonl"
            out_path = Path(tmpdir) / "results.jsonl"
            dataset_path.write_text(
                json.dumps(
                    {
                        "id": "case-1",
                        "question": "weight?",
                        "execution": {
                            "mode": "direct_tool",
                            "tool": "corp_db_search",
                            "args": {"kind": "lamp_exact", "name": "LAD LED R500-9-30-6-650LZD"},
                        },
                        "validation": {
                            "mode": "algorithmic",
                            "artifact_selector": {"tool": "corp_db_search", "kind": "lamp_exact"},
                            "checks": [{"type": "number_eq", "path": "results[0].weight_kg", "value": 18.3, "tolerance": 0.2}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            args = argparse.Namespace(
                dataset=str(dataset_path),
                out=str(out_path),
                pricing="bench/pricing.json",
                core_url="http://127.0.0.1:4000",
                tools_api_url="http://127.0.0.1:8100",
                user_id=1,
                chat_id=1,
                limit=0,
                sleep_ms=0,
                timeout_s=30.0,
                docker_exec=False,
            )

            payload = {"status": "success", "kind": "lamp_exact", "results": [{"weight_kg": 18.3}]}
            with patch.object(bench_run, "parse_args", return_value=args), patch.object(
                bench_run, "http_post_json", return_value=(200, payload, {})
            ):
                bench_run.main()

            rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["execution_mode"], "direct_tool")
            self.assertEqual(row["validation_mode"], "algorithmic")
            self.assertEqual(row["estimated_cost_usd"], 0.0)
            self.assertEqual(row["primary_artifact"]["payload"]["results"][0]["weight_kg"], 18.3)
            self.assertEqual(row["meta"]["retrieval_selected_source"], "corp_db")
            self.assertEqual(row["meta"]["retrieval_intent"], "catalog_lookup")

    def test_direct_tool_mode_supports_doc_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.jsonl"
            out_path = Path(tmpdir) / "results.jsonl"
            dataset_path.write_text(
                json.dumps(
                    {
                        "id": "case-doc",
                        "question": "сертификат?",
                        "execution": {
                            "mode": "direct_tool",
                            "tool": "doc_search",
                            "args": {"query": "сертификат line", "top": 3, "include_legacy": True},
                        },
                        "validation": {
                            "mode": "algorithmic",
                            "artifact_selector": {"tool": "doc_search", "kind": "doc_search"},
                            "checks": [{"type": "contains_any", "path": "results[*].preview", "value": ["сертификат"]}],
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            args = argparse.Namespace(
                dataset=str(dataset_path),
                out=str(out_path),
                pricing="bench/pricing.json",
                core_url="http://127.0.0.1:4000",
                tools_api_url="http://127.0.0.1:8100",
                user_id=1,
                chat_id=1,
                limit=0,
                sleep_ms=0,
                timeout_s=30.0,
                docker_exec=False,
            )

            payload = {
                "status": "success",
                "results": [{"relative_path": "company.md", "snippet": "сертификат line", "preview": "сертификат line"}],
            }
            with patch.object(bench_run, "parse_args", return_value=args), patch.object(
                bench_run, "http_post_json", return_value=(200, payload, {})
            ):
                bench_run.main()

            row = json.loads(out_path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["execution_mode"], "direct_tool")
            self.assertEqual(row["primary_artifact"]["tool"], "doc_search")
            self.assertEqual(row["meta"]["retrieval_selected_source"], "doc_search")
            self.assertEqual(row["meta"]["retrieval_intent"], "document_lookup")


if __name__ == "__main__":
    unittest.main()
