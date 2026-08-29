#!/usr/bin/env python3
"""Operator benchmark for canonical-series corp-db lamp_filters latency.

The normal entry point runs on the Docker host. It executes the timed HTTP loop
inside the tools-api container, so requests use the same internal network path as
direct tool calls and Docker process startup is excluded from every sample.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CASES = (
    ("r500_2ex", "LAD LED R500 2Ex", 11540),
    ("r320_ex", "LAD LED R320 Ex", 11540),
)
MIN_WARMUPS = 5
MIN_MEASURED = 30
ABSOLUTE_P95_LIMIT_MS = 500.0
RELATIVE_P95_LIMIT = 1.20


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def aggregate_samples(samples: list[dict[str, Any]], *, warmups: int) -> dict[str, Any]:
    durations = [float(item["duration_ms"]) for item in samples]
    http_successes = sum(bool(item.get("http_success")) for item in samples)
    application_successes = sum(bool(item.get("application_success")) for item in samples)
    return {
        "warmup_count": warmups,
        "sample_count": len(samples),
        "http_success_count": http_successes,
        "http_error_count": len(samples) - http_successes,
        "http_success_rate": round(http_successes / len(samples), 6) if samples else 0.0,
        "application_success_count": application_successes,
        "application_error_count": len(samples) - application_successes,
        "median_ms": round(statistics.median(durations), 3),
        "p95_ms": round(percentile_nearest_rank(durations, 0.95), 3),
        "max_ms": round(max(durations), 3),
    }


def evaluate_artifacts(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    baseline_cases = {case["case_id"]: case for case in baseline.get("cases", [])}
    current_cases = {case["case_id"]: case for case in current.get("cases", [])}
    checks: list[dict[str, Any]] = []
    passed = True

    for case_id in sorted(set(baseline_cases) | set(current_cases)):
        base = baseline_cases.get(case_id)
        cur = current_cases.get(case_id)
        if base is None or cur is None:
            checks.append({"case_id": case_id, "passed": False, "reason": "case_missing"})
            passed = False
            continue
        base_p95 = float(base["metrics"]["p95_ms"])
        current_p95 = float(cur["metrics"]["p95_ms"])
        sample_ok = (
            int(base["metrics"].get("warmup_count", 0)) >= MIN_WARMUPS
            and int(cur["metrics"].get("warmup_count", 0)) >= MIN_WARMUPS
            and int(base["metrics"].get("sample_count", 0)) >= MIN_MEASURED
            and int(cur["metrics"].get("sample_count", 0)) >= MIN_MEASURED
        )
        success_ok = (
            float(base["metrics"].get("http_success_rate", 0.0)) == 1.0
            and float(cur["metrics"].get("http_success_rate", 0.0)) == 1.0
            and int(base["metrics"].get("application_error_count", 1)) == 0
            and int(cur["metrics"].get("application_error_count", 1)) == 0
        )
        absolute_ok = current_p95 < ABSOLUTE_P95_LIMIT_MS
        relative_limit_ms = base_p95 * RELATIVE_P95_LIMIT
        relative_ok = current_p95 <= relative_limit_ms
        case_passed = sample_ok and success_ok and absolute_ok and relative_ok
        passed = passed and case_passed
        checks.append(
            {
                "case_id": case_id,
                "baseline_metrics": base["metrics"],
                "current_metrics": cur["metrics"],
                "baseline_p95_ms": base_p95,
                "current_p95_ms": current_p95,
                "relative_limit_ms": round(relative_limit_ms, 3),
                "sample_size_ok": sample_ok,
                "success_rate_ok": success_ok,
                "absolute_p95_ok": absolute_ok,
                "relative_p95_ok": relative_ok,
                "passed": case_passed,
            }
        )

    return {
        "passed": passed and len(checks) == len(DEFAULT_CASES),
        "thresholds": {
            "absolute_p95_lt_ms": ABSOLUTE_P95_LIMIT_MS,
            "relative_p95_lte_baseline_multiplier": RELATIVE_P95_LIMIT,
            "minimum_warmups_per_case": MIN_WARMUPS,
            "minimum_measured_per_case": MIN_MEASURED,
        },
        "checks": checks,
    }


def _http_worker(url: str, warmups: int, measured: int, timeout: float) -> int:
    case_results = []
    for case_id, series, flux_lm_min in DEFAULT_CASES:
        payload = json.dumps(
            {
                "kind": "lamp_filters",
                "series": series,
                "flux_lm_min": flux_lm_min,
                "limit": 20,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        def request_once() -> dict[str, Any]:
            request = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            started = time.perf_counter()
            http_status = 0
            application_status = "transport_error"
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    http_status = response.status
                    body = json.load(response)
                    application_status = str(body.get("status", "missing"))
            except urllib.error.HTTPError as exc:
                http_status = exc.code
                application_status = "http_error"
            except Exception:
                application_status = "transport_error"
            duration_ms = (time.perf_counter() - started) * 1000.0
            return {
                "duration_ms": duration_ms,
                "http_success": 200 <= http_status < 300,
                "application_success": application_status in {"success", "empty"},
            }

        for _ in range(warmups):
            request_once()
        samples = [request_once() for _ in range(measured)]
        case_results.append(
            {
                "case_id": case_id,
                "request": {
                    "kind": "lamp_filters",
                    "series": series,
                    "flux_lm_min": flux_lm_min,
                    "limit": 20,
                },
                "metrics": aggregate_samples(samples, warmups=warmups),
            }
        )
    json.dump({"cases": case_results}, sys.stdout, ensure_ascii=False)
    return 0


def _run(command: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.strip()


def _docker_json(container: str, args: list[str], *, input_text: str | None = None) -> Any:
    output = _run(["docker", "exec", "-i", container, *args], input_text=input_text)
    return json.loads(output)


def _container_health(container: str, url: str) -> dict[str, Any]:
    program = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen(%r))))" % url
    return _docker_json(container, ["python", "-c", program])


def _container_metadata(container: str) -> dict[str, Any]:
    raw = _run(
        [
            "docker",
            "inspect",
            container,
            "--format",
            '{{json .Config.Image}}|{{json .Image}}|{{json .Created}}',
        ]
    )
    image_name, image_id, created = (json.loads(part) for part in raw.split("|"))
    return {"container": container, "image": image_name, "image_id": image_id, "created_at": created}


def _psql_json(db_container: str, sql: str) -> Any:
    output = _run(
        [
            "docker",
            "exec",
            "-i",
            "-u",
            "postgres",
            db_container,
            "psql",
            "-XAt",
            "-d",
            os.getenv("CORP_DB_NAME", "corp_pg_db"),
            "-c",
            sql,
        ]
    )
    return json.loads(output)


def _summarize_plan(payload: Any) -> dict[str, Any]:
    root_document = payload[0]
    root = root_document["Plan"]
    node_types: set[str] = set()
    relations: set[str] = set()
    indexes: set[str] = set()

    def visit(node: dict[str, Any]) -> None:
        if node.get("Node Type"):
            node_types.add(str(node["Node Type"]))
        if node.get("Relation Name"):
            relations.add(str(node["Relation Name"]))
        if node.get("Index Name"):
            indexes.add(str(node["Index Name"]))
        for child in node.get("Plans", []):
            visit(child)

    visit(root)
    return {
        "planning_time_ms": round(float(root_document.get("Planning Time", 0.0)), 3),
        "execution_time_ms": round(float(root_document.get("Execution Time", 0.0)), 3),
        "root_node_type": root.get("Node Type"),
        "root_actual_rows": root.get("Actual Rows"),
        "root_total_cost": root.get("Total Cost"),
        "shared_hit_blocks": root.get("Shared Hit Blocks", 0),
        "shared_read_blocks": root.get("Shared Read Blocks", 0),
        "temp_read_blocks": root.get("Temp Read Blocks", 0),
        "temp_written_blocks": root.get("Temp Written Blocks", 0),
        "node_types": sorted(node_types),
        "relations": sorted(relations),
        "indexes": sorted(indexes),
    }


def _explain(db_container: str, series: str, flux_lm_min: int) -> dict[str, Any]:
    escaped_series = series.replace("'", "''")
    sql = f"""
    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
    SELECT l.*
    FROM corp.v_catalog_lamps_agent l
    WHERE TRUE
      AND l.series_name = '{escaped_series}'
      AND l.luminous_flux_lm >= {int(flux_lm_min)}
    ORDER BY l.name
    LIMIT 20 OFFSET 0;
    """
    return _summarize_plan(_psql_json(db_container, sql))


def _dataset_info(db_container: str) -> dict[str, Any]:
    sql = """
    SELECT json_build_object(
      'catalog_lamps', (SELECT count(*) FROM corp.catalog_lamps),
      'categories', (SELECT count(*) FROM corp.categories),
      'catalog_series_families', (SELECT count(*) FROM corp.catalog_series_families),
      'search_docs', (SELECT count(*) FROM corp.corp_search_docs),
      'database_size_bytes', pg_database_size(current_database()),
      'postgres_version', current_setting('server_version')
    );
    """
    return _psql_json(db_container, sql)


def _git_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"])


def _run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.warmups < MIN_WARMUPS or args.measured < MIN_MEASURED:
        raise SystemExit(f"run requires at least {MIN_WARMUPS} warmups and {MIN_MEASURED} measured requests")

    source = Path(__file__).read_text(encoding="utf-8")
    worker_args = [
        "docker",
        "exec",
        "-i",
        args.tools_container,
        "python",
        "-",
        "--worker",
        "--url",
        args.url,
        "--warmups",
        str(args.warmups),
        "--measured",
        str(args.measured),
        "--timeout",
        str(args.timeout),
    ]
    benchmark = json.loads(_run(worker_args, input_text=source))
    health_url = args.url.rsplit("/corp-db/search", 1)[0] + "/health"
    health = _container_health(args.tools_container, health_url)
    cases = benchmark["cases"]
    for case in cases:
        case["explain_summary"] = _explain(
            args.db_container,
            str(case["request"]["series"]),
            int(case["request"]["flux_lm_min"]),
        )

    timestamp_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    git_sha = _git_sha()
    artifact = {
        "artifact_version": 1,
        "benchmark": "canonical-series-lamp-filters",
        "label": args.label,
        "timestamp_utc": timestamp_utc,
        "git_sha": git_sha,
        "evidence_build": {"git_sha": git_sha, "build_time": timestamp_utc},
        "schema_git_sha": args.schema_git_sha or _git_sha(),
        "production_like_path": "direct HTTP inside tools-api container to /corp-db/search",
        "command": (
            f"python3 scripts/corp_db_lamp_filters_latency.py run --label {args.label} "
            f"--output {args.output} --warmups {args.warmups} --measured {args.measured}"
        ),
        "stack": {
            "tools_api": health,
            "tools_api_container": _container_metadata(args.tools_container),
            "corp_db_container": _container_metadata(args.db_container),
        },
        "dataset": _dataset_info(args.db_container),
        "sampling": {"warmups_per_case": args.warmups, "measured_per_case": args.measured},
        "cases": cases,
        "privacy": {
            "contains_user_text": False,
            "contains_user_id": False,
            "contains_secrets": False,
            "raw_samples_retained": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def _markdown_report(baseline_path: str, current_path: str, result: dict[str, Any]) -> str:
    status = "PASS" if result["passed"] else "FAIL"
    lines = [
        "Canonical-series lamp_filters latency evidence",
        "===============================================",
        "",
        f"**Result: {status}**",
        "",
        f"- Baseline: `{baseline_path}`",
        f"- Current: `{current_path}`",
        f"- Budget: current p95 `< {ABSOLUTE_P95_LIMIT_MS:.0f} ms` and `<= baseline * {RELATIVE_P95_LIMIT:.2f}`",
        f"- Minimum sampling: {MIN_WARMUPS} warmups + {MIN_MEASURED} measured requests per case",
        "",
        "| Case | Run | HTTP success | Samples | Median | p95 | Max | Budget result |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for check in result["checks"]:
        if "baseline_p95_ms" not in check:
            lines.append(f"| {check['case_id']} | missing | n/a | n/a | n/a | n/a | n/a | FAIL |")
            continue
        for run_name, metrics in (
            ("baseline", check["baseline_metrics"]),
            ("current", check["current_metrics"]),
        ):
            budget = "reference" if run_name == "baseline" else (
                f"{'PASS' if check['passed'] else 'FAIL'} "
                f"(<{ABSOLUTE_P95_LIMIT_MS:.0f} ms; <= {check['relative_limit_ms']:.3f} ms)"
            )
            lines.append(
                f"| {check['case_id']} | {run_name} | {float(metrics['http_success_rate']) * 100:.1f}% | "
                f"{int(metrics['sample_count'])} | {float(metrics['median_ms']):.3f} ms | "
                f"{float(metrics['p95_ms']):.3f} ms | {float(metrics['max_ms']):.3f} ms | {budget} |"
            )
    lines.extend(
        [
            "",
            "The JSON artifacts contain aggregate latency, HTTP/application errors, dataset size,",
            "build/container metadata, and bounded EXPLAIN summaries. Raw samples, user text, user_id,",
            "DSNs, authorization headers, and secrets are intentionally not retained.",
            "",
        ]
    )
    return "\n".join(lines)


def _compare(args: argparse.Namespace) -> dict[str, Any]:
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    result = evaluate_artifacts(baseline, current)
    report = _markdown_report(args.baseline, args.current, result)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    print(report)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--url", default="http://127.0.0.1:8100/corp-db/search")
    parser.add_argument("--warmups", type=int, default=MIN_WARMUPS)
    parser.add_argument("--measured", type=int, default=MIN_MEASURED)
    parser.add_argument("--timeout", type=float, default=10.0)
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="capture one aggregate latency and EXPLAIN artifact")
    run_parser.add_argument("--label", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--schema-git-sha")
    run_parser.add_argument("--tools-container", default="tools-api")
    run_parser.add_argument("--db-container", default="corp-db")
    run_parser.add_argument("--url", default="http://127.0.0.1:8100/corp-db/search")
    run_parser.add_argument("--warmups", type=int, default=MIN_WARMUPS)
    run_parser.add_argument("--measured", type=int, default=MIN_MEASURED)
    run_parser.add_argument("--timeout", type=float, default=10.0)

    compare_parser = subparsers.add_parser("compare", help="enforce absolute and relative p95 budgets")
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--current", required=True)
    compare_parser.add_argument("--output")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.worker:
        return _http_worker(args.url, args.warmups, args.measured, args.timeout)
    if args.command == "run":
        artifact = _run_benchmark(args)
        print(json.dumps({"output": args.output, "cases": artifact["cases"]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compare":
        return 0 if _compare(args)["passed"] else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
