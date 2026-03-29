#!/usr/bin/env python3
"""
Bench evaluator: scores results JSONL against golden dataset checks.

Usage:
  python3 scripts/bench_eval.py --results bench/results/<run_id>.jsonl
  python3 scripts/bench_eval.py --results bench/results/<run_id>.jsonl --report bench/reports/<run_id>.md
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Optional

from bench_lib import estimate_cost_usd, eval_checks, load_pricing, percentile, read_jsonl

DEFAULT_DATASET = "bench/golden/v1.jsonl"
DEFAULT_PRICING = "bench/pricing.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate bench results against golden dataset.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Golden dataset JSONL")
    parser.add_argument("--pricing", default=DEFAULT_PRICING, help="Pricing JSON for cost recomputation")
    parser.add_argument("--results", required=True, help="Results JSONL from scripts/bench_run.py")
    parser.add_argument("--report", default="", help="Optional markdown report path")
    parser.add_argument("--json-out", default="", help="Optional JSON summary path")
    parser.add_argument("--show-fails", type=int, default=20, help="How many failed cases to print")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    pricing_path = Path(args.pricing)
    results_path = Path(args.results)
    report_path = Path(args.report) if args.report else None
    json_out_path = Path(args.json_out) if args.json_out else None

    dataset = read_jsonl(dataset_path)
    results = read_jsonl(results_path)
    pricing = load_pricing(pricing_path)

    by_case: dict[str, dict[str, Any]] = {}
    for row in results:
        case_id = str(row.get("case_id") or "")
        if case_id:
            by_case[case_id] = row  # keep last occurrence

    pass_count = 0
    fail_count = 0
    missing_count = 0
    non_ok_count = 0
    failures: list[dict[str, Any]] = []

    durations: list[float] = []
    tokens_total = 0
    tokens_prompt = 0
    tokens_completion = 0
    cost_total = 0.0
    cost_seen = 0

    tag_totals: dict[str, int] = {}
    tag_pass: dict[str, int] = {}

    for case in dataset:
        case_id = str(case.get("id") or "")
        tags = case.get("tags") if isinstance(case.get("tags"), list) else []
        for t in tags:
            if isinstance(t, str) and t:
                tag_totals[t] = tag_totals.get(t, 0) + 1

        row = by_case.get(case_id)
        if row is None:
            missing_count += 1
            failures.append({"case_id": case_id, "reason": "missing_result"})
            continue

        status = str(row.get("status") or "ok")
        answer = str(row.get("answer") or "")
        request_id = str(row.get("request_id") or "")

        dur = row.get("duration_ms")
        if isinstance(dur, (int, float)):
            durations.append(float(dur))

        meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
        if meta and isinstance(meta.get("llm_usage"), dict):
            usage = meta["llm_usage"]
            tokens_prompt += int(usage.get("prompt_tokens", 0) or 0)
            tokens_completion += int(usage.get("completion_tokens", 0) or 0)
            tokens_total += int(usage.get("total_tokens", 0) or 0)

        cost = estimate_cost_usd(meta, pricing)
        if cost is None:
            cost = row.get("estimated_cost_usd")
        if isinstance(cost, (int, float)):
            cost_total += float(cost)
            cost_seen += 1

        if status != "ok":
            non_ok_count += 1
            fail_count += 1
            failures.append({"case_id": case_id, "request_id": request_id, "reason": f"status={status}"})
            continue

        golden = case.get("golden") if isinstance(case.get("golden"), dict) else {}
        checks = golden.get("checks") if isinstance(golden.get("checks"), list) else []

        ok, errors = eval_checks(answer, checks)
        if ok:
            pass_count += 1
            for t in tags:
                if isinstance(t, str) and t:
                    tag_pass[t] = tag_pass.get(t, 0) + 1
        else:
            fail_count += 1
            failures.append({"case_id": case_id, "request_id": request_id, "reason": "; ".join(errors[:5])})

    total = len(dataset)
    scored = total - missing_count
    pass_rate = (pass_count / scored) if scored else 0.0

    summary = {
        "dataset": str(dataset_path),
        "results": str(results_path),
        "total_cases": total,
        "results_found": scored,
        "missing_results": missing_count,
        "pass": pass_count,
        "fail": fail_count,
        "non_ok": non_ok_count,
        "pass_rate": round(pass_rate, 4),
        "duration_ms_avg": round(statistics.mean(durations), 3) if durations else None,
        "duration_ms_p50": round(percentile(durations, 50) or 0.0, 3) if durations else None,
        "duration_ms_p95": round(percentile(durations, 95) or 0.0, 3) if durations else None,
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "tokens_total": tokens_total,
        "estimated_cost_usd_total": round(cost_total, 8) if cost_seen else None,
        "estimated_cost_usd_seen": cost_seen,
        "tags": {
            t: {
                "pass": tag_pass.get(t, 0),
                "total": tag_totals.get(t, 0),
                "pass_rate": round(tag_pass.get(t, 0) / tag_totals[t], 4) if tag_totals.get(t) else 0.0,
            }
            for t in sorted(tag_totals.keys())
        },
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        print("\nFAILURES:")
        for item in failures[: max(0, int(args.show_fails))]:
            rid = item.get("request_id") or ""
            print(f"- {item.get('case_id')}: {item.get('reason')}" + (f" (request_id={rid})" if rid else ""))

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append(f"# Bench report\n")
        lines.append(f"- Dataset: `{dataset_path}`")
        lines.append(f"- Results: `{results_path}`")
        lines.append(f"- Pass rate: **{summary['pass_rate']}** ({pass_count}/{scored})")
        if summary["duration_ms_avg"] is not None:
            lines.append(f"- Latency avg/p50/p95 (ms): {summary['duration_ms_avg']} / {summary['duration_ms_p50']} / {summary['duration_ms_p95']}")
        if summary["tokens_total"]:
            lines.append(f"- Tokens total (prompt/completion/total): {tokens_prompt} / {tokens_completion} / {tokens_total}")
        if summary["estimated_cost_usd_total"] is not None:
            lines.append(f"- Estimated cost total (USD): {summary['estimated_cost_usd_total']}")
        lines.append("")
        lines.append("## Tags")
        for t in sorted(tag_totals.keys()):
            s = summary["tags"][t]
            lines.append(f"- `{t}`: {s['pass']}/{s['total']} (pass_rate={s['pass_rate']})")
        lines.append("")
        if failures:
            lines.append("## Failures")
            for item in failures:
                rid = item.get("request_id") or ""
                lines.append(f"- `{item.get('case_id')}`: {item.get('reason')}" + (f" (`request_id={rid}`)" if rid else ""))
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if json_out_path:
        json_out_path.parent.mkdir(parents=True, exist_ok=True)
        json_out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
