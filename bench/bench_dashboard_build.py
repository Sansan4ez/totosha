#!/usr/bin/env python3
"""
Build static JSON artifacts for the bench dashboard (no backend).

Reads:
  - golden dataset JSONL (bench/golden/v1.jsonl)
  - results JSONL runs (bench/results/*.jsonl)

Writes (gitignored by default):
  - bench/reports/index.json            (run list)
  - bench/reports/<run_id>.json         (per-run full data)
  - bench/reports/latest.json           (copy of latest run)

Usage:
  python3 bench/bench_dashboard_build.py
  python3 bench/bench_dashboard_build.py --results-glob 'bench/results/*.jsonl'
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import statistics
from pathlib import Path
from typing import Any, Optional

try:
    from .bench_lib import BENCH_DIR, estimate_cost_usd, evaluate_case_result, get_validation, load_pricing, percentile, read_jsonl, repo_rel, resolve_repo_path
except ImportError:  # pragma: no cover - CLI script fallback
    from bench_lib import BENCH_DIR, estimate_cost_usd, evaluate_case_result, get_validation, load_pricing, percentile, read_jsonl, repo_rel, resolve_repo_path


DEFAULT_DATASET = BENCH_DIR / "golden" / "v1.jsonl"
DEFAULT_RESULTS_GLOB = str(BENCH_DIR / "results" / "*.jsonl")
DEFAULT_OUT_DIR = BENCH_DIR / "reports"
DEFAULT_INDEX = DEFAULT_OUT_DIR / "index.json"
DEFAULT_LATEST = DEFAULT_OUT_DIR / "latest.json"
DEFAULT_PRICING = BENCH_DIR / "pricing.json"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _parse_started_at(v: Any) -> Optional[dt.datetime]:
    if not v:
        return None
    s = str(v)
    try:
        if s.endswith("Z"):
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def _get_usage(meta: Any) -> Optional[dict[str, int]]:
    if not isinstance(meta, dict):
        return None
    usage = meta.get("llm_usage")
    if not isinstance(usage, dict):
        return None
    return {
        "prompt_tokens": _to_int(usage.get("prompt_tokens")),
        "completion_tokens": _to_int(usage.get("completion_tokens")),
        "total_tokens": _to_int(usage.get("total_tokens")),
    }


def _norm_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for t in tags:
        if isinstance(t, str) and t:
            out.append(t)
    return out


def build_run_report(dataset: list[dict[str, Any]], dataset_path: Path, results_path: Path, pricing: dict[str, Any]) -> dict[str, Any]:
    results_rows = read_jsonl(results_path)
    by_case: dict[str, dict[str, Any]] = {}
    for row in results_rows:
        case_id = str(row.get("case_id") or "")
        if case_id:
            by_case[case_id] = row  # keep last occurrence

    first = results_rows[0] if results_rows else {}
    run_id = str(first.get("run_id") or results_path.stem)
    started_at = str(first.get("started_at") or "")

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
    validation_mode_totals: dict[str, int] = {}
    validation_mode_pass: dict[str, int] = {}

    cases_out: list[dict[str, Any]] = []

    for case in dataset:
        case_id = str(case.get("id") or "")
        if not case_id:
            continue

        tags = _norm_tags(case.get("tags"))
        validation = get_validation(case)
        validation_mode = str(validation.get("mode") or "legacy_text")
        validation_mode_totals[validation_mode] = validation_mode_totals.get(validation_mode, 0) + 1
        for t in tags:
            tag_totals[t] = tag_totals.get(t, 0) + 1

        question = str(case.get("question") or "")
        golden = case.get("golden") if isinstance(case.get("golden"), dict) else {}
        golden_answer = str(golden.get("answer") or "")
        routing = case.get("routing") if isinstance(case.get("routing"), dict) else {}
        evidence = case.get("evidence") if isinstance(case.get("evidence"), list) else []

        row = by_case.get(case_id)
        if row is None:
            missing_count += 1
            failures.append({"case_id": case_id, "reason": "missing_result"})
            cases_out.append(
                {
                    "case_id": case_id,
                    "tags": tags,
                    "question": question,
                    "golden": {"answer": golden_answer, "checks": golden.get("checks"), "routing": routing, "evidence": evidence, "validation": validation},
                    "result": None,
                    "scoring": {"passed": False, "errors": ["missing_result"], "missing": True},
                }
            )
            continue

        status = str(row.get("status") or "ok")
        answer = str(row.get("answer") or "")
        request_id = str(row.get("request_id") or "")

        dur = _to_float(row.get("duration_ms"))
        if isinstance(dur, float):
            durations.append(dur)

        meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
        usage = _get_usage(meta)
        if usage:
            tokens_prompt += usage["prompt_tokens"]
            tokens_completion += usage["completion_tokens"]
            tokens_total += usage["total_tokens"]

        cost = estimate_cost_usd(meta, pricing)
        if cost is None:
            cost = row.get("estimated_cost_usd")
        if isinstance(cost, (int, float)):
            cost_total += float(cost)
            cost_seen += 1

        passed = False
        errors: list[str] = []
        if status != "ok":
            non_ok_count += 1
            fail_count += 1
            errors = [f"status={status}"]
            failures.append({"case_id": case_id, "request_id": request_id, "reason": errors[0]})
        else:
            evaluation = evaluate_case_result(case, row)
            passed = bool(evaluation["passed"])
            errors = list(evaluation["errors"])
            if passed:
                pass_count += 1
                validation_mode_pass[validation_mode] = validation_mode_pass.get(validation_mode, 0) + 1
                for t in tags:
                    tag_pass[t] = tag_pass.get(t, 0) + 1
            else:
                fail_count += 1
                failures.append({"case_id": case_id, "request_id": request_id, "reason": "; ".join(errors[:5])})

        cases_out.append(
            {
                "case_id": case_id,
                "tags": tags,
                "question": question,
                "golden": {"answer": golden_answer, "checks": golden.get("checks"), "routing": routing, "evidence": evidence, "validation": validation},
                "result": {
                    "status": status,
                    "request_id": request_id,
                    "started_at": str(row.get("started_at") or ""),
                    "http_status": row.get("http_status"),
                    "duration_ms": row.get("duration_ms"),
                    "answer": answer,
                    "meta": meta,
                    "primary_artifact": row.get("primary_artifact"),
                    "bench_artifacts": row.get("bench_artifacts"),
                    "execution_mode": row.get("execution_mode"),
                    "validation_mode": row.get("validation_mode"),
                    "estimated_cost_usd": None if cost is None else round(float(cost), 8),
                },
                "scoring": {"passed": bool(passed), "errors": errors, "missing": False},
            }
        )

    total = len([c for c in dataset if isinstance(c, dict) and c.get("id")])
    scored = total - missing_count
    pass_rate = (pass_count / scored) if scored else 0.0

    summary = {
        "dataset": repo_rel(dataset_path),
        "results": repo_rel(results_path),
        "run_id": run_id,
        "started_at": started_at,
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
        "validation_modes": {
            mode: {
                "pass": validation_mode_pass.get(mode, 0),
                "total": validation_mode_totals.get(mode, 0),
                "pass_rate": round(validation_mode_pass.get(mode, 0) / validation_mode_totals[mode], 4) if validation_mode_totals.get(mode) else 0.0,
            }
            for mode in sorted(validation_mode_totals.keys())
        },
    }

    return {
        "version": 1,
        "generated_at": utc_now_iso(),
        "summary": summary,
        "failures": failures,
        "cases": cases_out,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build JSON artifacts for the bench dashboard.")
    p.add_argument("--dataset", default=repo_rel(DEFAULT_DATASET), help="Golden dataset JSONL")
    p.add_argument("--pricing", default=repo_rel(DEFAULT_PRICING), help="Pricing JSON for cost recomputation")
    p.add_argument("--results-glob", default=repo_rel(Path(DEFAULT_RESULTS_GLOB)), help="Glob for results JSONL runs")
    p.add_argument("--out-dir", default=repo_rel(DEFAULT_OUT_DIR), help="Output dir for reports JSON")
    p.add_argument("--index", default=repo_rel(DEFAULT_INDEX), help="Index JSON path (run list)")
    p.add_argument("--latest", default=repo_rel(DEFAULT_LATEST), help="Latest run JSON path")
    p.add_argument("--max-runs", type=int, default=200, help="Max runs to include in the index")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    dataset_path = resolve_repo_path(args.dataset)
    pricing_path = resolve_repo_path(args.pricing)
    out_dir = resolve_repo_path(args.out_dir)
    index_path = resolve_repo_path(args.index)
    latest_path = resolve_repo_path(args.latest)
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset = read_jsonl(dataset_path)
    pricing = load_pricing(pricing_path)

    result_files = [Path(p) for p in glob.glob(str(resolve_repo_path(args.results_glob)))]
    result_files = [p for p in result_files if p.is_file()]
    result_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if args.max_runs and args.max_runs > 0:
        result_files = result_files[: args.max_runs]

    runs_index: list[dict[str, Any]] = []
    latest_report: Optional[dict[str, Any]] = None
    latest_time: Optional[dt.datetime] = None

    for results_path in result_files:
        report = build_run_report(dataset, dataset_path, results_path, pricing)
        run_id = str((report.get("summary") or {}).get("run_id") or results_path.stem)
        started_at = str((report.get("summary") or {}).get("started_at") or "")

        report_path = out_dir / f"{run_id}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        t = _parse_started_at(started_at) or dt.datetime.fromtimestamp(results_path.stat().st_mtime, tz=dt.timezone.utc)
        if latest_time is None or t > latest_time:
            latest_time = t
            latest_report = report

        s = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        runs_index.append(
            {
                "run_id": run_id,
                "started_at": started_at,
                "results_path": repo_rel(results_path),
                "report_path": repo_rel(report_path),
                "pass_rate": s.get("pass_rate"),
                "pass": s.get("pass"),
                "fail": s.get("fail"),
                "non_ok": s.get("non_ok"),
                "missing_results": s.get("missing_results"),
                "duration_ms_p50": s.get("duration_ms_p50"),
                "duration_ms_p95": s.get("duration_ms_p95"),
                "tokens_total": s.get("tokens_total"),
                "estimated_cost_usd_total": s.get("estimated_cost_usd_total"),
            }
        )

    idx = {
        "version": 1,
        "generated_at": utc_now_iso(),
        "dataset": repo_rel(dataset_path),
        "results_glob": args.results_glob,
        "runs": sorted(
            runs_index,
            key=lambda r: _parse_started_at(r.get("started_at")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            reverse=True,
        ),
    }

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if latest_report is not None:
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(json.dumps(latest_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {repo_rel(index_path)} runs={len(runs_index)} out_dir={repo_rel(out_dir)}")


if __name__ == "__main__":
    main()
