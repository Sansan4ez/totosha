#!/usr/bin/env python3
"""
Compare legacy answer-based validation against algorithmic artifact validation.

Usage:
  python3 bench/bench_compare.py --results bench/results/run.jsonl
  python3 bench/bench_compare.py --legacy-results bench/results/legacy.jsonl --algorithmic-results bench/results/alg.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Optional

try:
    from .bench_lib import (
        BENCH_DIR,
        estimate_cost_usd,
        eval_checks,
        eval_routing,
        eval_algorithmic,
        get_text_checks,
        get_validation,
        load_pricing,
        percentile,
        read_jsonl,
        repo_rel,
        resolve_repo_path,
    )
except ImportError:  # pragma: no cover - CLI script fallback
    from bench_lib import (
        BENCH_DIR,
        estimate_cost_usd,
        eval_checks,
        eval_routing,
        eval_algorithmic,
        get_text_checks,
        get_validation,
        load_pricing,
        percentile,
        read_jsonl,
        repo_rel,
        resolve_repo_path,
    )

DEFAULT_DATASET = BENCH_DIR / "golden" / "v1.jsonl"
DEFAULT_PRICING = BENCH_DIR / "pricing.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare legacy and algorithmic validation verdicts.")
    parser.add_argument("--dataset", default=repo_rel(DEFAULT_DATASET), help="Golden dataset JSONL")
    parser.add_argument("--pricing", default=repo_rel(DEFAULT_PRICING), help="Pricing JSON for cost recomputation")
    parser.add_argument("--results", default="", help="Single results JSONL containing answer and artifacts")
    parser.add_argument("--legacy-results", default="", help="Optional legacy results JSONL")
    parser.add_argument("--algorithmic-results", default="", help="Optional algorithmic/direct-tool results JSONL")
    parser.add_argument("--report", default="", help="Optional markdown report path")
    parser.add_argument("--json-out", default="", help="Optional JSON summary path")
    parser.add_argument("--show-fails", type=int, default=20, help="How many divergence cases to print")
    return parser.parse_args()


def _load_by_case(path: Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(path)
    by_case: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        if case_id:
            by_case[case_id] = row
    return by_case


def _usage_tokens(meta: Optional[dict[str, Any]]) -> int:
    if not isinstance(meta, dict):
        return 0
    usage = meta.get("llm_usage")
    if not isinstance(usage, dict):
        return 0
    try:
        return int(usage.get("total_tokens", 0) or 0)
    except Exception:
        return 0


def _metrics(rows: list[dict[str, Any]], pricing: dict[str, Any]) -> dict[str, Any]:
    durations: list[float] = []
    tokens_total = 0
    cost_total = 0.0
    cost_seen = 0
    for row in rows:
        dur = row.get("duration_ms")
        if isinstance(dur, (int, float)):
            durations.append(float(dur))
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
        tokens_total += _usage_tokens(meta)
        cost = estimate_cost_usd(meta, pricing)
        if cost is None:
            cost = row.get("estimated_cost_usd")
        if isinstance(cost, (int, float)):
            cost_total += float(cost)
            cost_seen += 1
    return {
        "count": len(rows),
        "duration_ms_avg": round(statistics.mean(durations), 3) if durations else None,
        "duration_ms_p50": round(percentile(durations, 50) or 0.0, 3) if durations else None,
        "duration_ms_p95": round(percentile(durations, 95) or 0.0, 3) if durations else None,
        "tokens_total": tokens_total,
        "estimated_cost_usd_total": round(cost_total, 8) if cost_seen else None,
    }


def main() -> None:
    args = parse_args()
    dataset_path = resolve_repo_path(args.dataset)
    pricing_path = resolve_repo_path(args.pricing)
    pricing = load_pricing(pricing_path)

    if args.results:
        result_path = resolve_repo_path(args.results)
        legacy_by_case = _load_by_case(result_path)
        algorithmic_by_case = legacy_by_case
        legacy_rows = list(legacy_by_case.values())
        algorithmic_rows = legacy_rows
    else:
        if not args.legacy_results or not args.algorithmic_results:
            raise SystemExit("Provide --results or both --legacy-results and --algorithmic-results.")
        legacy_path = resolve_repo_path(args.legacy_results)
        algorithmic_path = resolve_repo_path(args.algorithmic_results)
        legacy_by_case = _load_by_case(legacy_path)
        algorithmic_by_case = _load_by_case(algorithmic_path)
        legacy_rows = list(legacy_by_case.values())
        algorithmic_rows = list(algorithmic_by_case.values())

    dataset = read_jsonl(dataset_path)
    comparison_rows: list[dict[str, Any]] = []
    status_totals: dict[str, int] = {}

    for case in dataset:
        case_id = str(case.get("id") or "")
        if not case_id:
            continue

        routing = case.get("routing") if isinstance(case.get("routing"), dict) else {}
        validation = get_validation(case)
        has_legacy = bool(get_text_checks(case))
        has_algorithmic = validation.get("mode") in {"algorithmic", "hybrid"} or bool(validation.get("artifact_selector"))

        legacy_row = legacy_by_case.get(case_id)
        algorithmic_row = algorithmic_by_case.get(case_id)
        if args.results and legacy_row is not None and str(legacy_row.get("execution_mode") or "") == "direct_tool":
            has_legacy = False

        legacy_pass: Optional[bool] = None
        legacy_errors: list[str] = []
        routing_pass: Optional[bool] = None
        algorithmic_pass: Optional[bool] = None
        algorithmic_errors: list[str] = []

        if has_legacy and legacy_row is not None and str(legacy_row.get("status") or "ok") == "ok":
            answer = str(legacy_row.get("answer") or "")
            meta = legacy_row.get("meta") if isinstance(legacy_row.get("meta"), dict) else None
            answer_ok, answer_errors = eval_checks(answer, get_text_checks(case))
            routing_ok, routing_errors = eval_routing(meta, routing)
            legacy_pass = answer_ok and routing_ok
            legacy_errors = answer_errors + routing_errors
            routing_pass = routing_ok
        elif has_legacy:
            legacy_errors = ["missing_legacy_result"] if legacy_row is None else [f"status={legacy_row.get('status')}"]

        if has_algorithmic and algorithmic_row is not None and str(algorithmic_row.get("status") or "ok") == "ok":
            meta = algorithmic_row.get("meta") if isinstance(algorithmic_row.get("meta"), dict) else None
            algorithmic_ok, algorithmic_eval_errors, _artifact, _payload = eval_algorithmic(algorithmic_row, validation)
            routing_ok, routing_errors = eval_routing(meta, routing)
            algorithmic_pass = algorithmic_ok and routing_ok
            algorithmic_errors = algorithmic_eval_errors + routing_errors
            if routing_pass is None:
                routing_pass = routing_ok
        elif has_algorithmic:
            algorithmic_errors = ["missing_algorithmic_result"] if algorithmic_row is None else [f"status={algorithmic_row.get('status')}"]

        if not has_legacy or not has_algorithmic:
            comparison_status = "not_comparable"
        elif any(error.startswith("missing_artifact") for error in algorithmic_errors):
            comparison_status = "missing_artifact"
        elif legacy_pass is True and algorithmic_pass is True:
            comparison_status = "same_pass"
        elif legacy_pass is False and algorithmic_pass is False:
            comparison_status = "same_fail"
        elif legacy_pass is True and algorithmic_pass is False:
            comparison_status = "legacy_only_pass"
        elif legacy_pass is False and algorithmic_pass is True:
            comparison_status = "algorithmic_only_pass"
        else:
            comparison_status = "not_comparable"

        status_totals[comparison_status] = status_totals.get(comparison_status, 0) + 1
        comparison_rows.append(
            {
                "case_id": case_id,
                "legacy_pass": legacy_pass,
                "algorithmic_pass": algorithmic_pass,
                "routing_pass": routing_pass,
                "comparison_status": comparison_status,
                "legacy_errors": legacy_errors,
                "algorithmic_errors": algorithmic_errors,
            }
        )

    summary = {
        "dataset": repo_rel(dataset_path),
        "comparison_status_totals": status_totals,
        "legacy_metrics": _metrics(legacy_rows, pricing),
        "algorithmic_metrics": _metrics(algorithmic_rows, pricing),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    divergences = [row for row in comparison_rows if row["comparison_status"] not in {"same_pass", "same_fail", "not_comparable"}]
    if divergences:
        print("\nDIVERGENCES:")
        for row in divergences[: max(0, int(args.show_fails))]:
            print(
                f"- {row['case_id']}: {row['comparison_status']}; "
                f"legacy={row['legacy_errors'][:2]} algorithmic={row['algorithmic_errors'][:2]}"
            )

    if args.report:
        report_path = resolve_repo_path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Bench comparison",
            "",
            f"- Dataset: `{repo_rel(dataset_path)}`",
            f"- Comparison statuses: `{json.dumps(status_totals, ensure_ascii=False)}`",
            f"- Legacy metrics: `{json.dumps(summary['legacy_metrics'], ensure_ascii=False)}`",
            f"- Algorithmic metrics: `{json.dumps(summary['algorithmic_metrics'], ensure_ascii=False)}`",
            "",
            "## Divergences",
        ]
        if divergences:
            for row in divergences:
                lines.append(
                    f"- `{row['case_id']}`: {row['comparison_status']} "
                    f"(legacy={row['legacy_errors'][:2]}, algorithmic={row['algorithmic_errors'][:2]})"
                )
        else:
            lines.append("- none")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.json_out:
        json_out_path = resolve_repo_path(args.json_out)
        json_out_path.parent.mkdir(parents=True, exist_ok=True)
        json_out_path.write_text(json.dumps({"summary": summary, "cases": comparison_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
