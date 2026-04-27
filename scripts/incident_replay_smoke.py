#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "bench" / "golden" / "incident-pfit7.jsonl"
DEFAULT_CORE_URL = "http://127.0.0.1:4000"
DEFAULT_TOOLS_API_URL = "http://127.0.0.1:8100"
DEFAULT_SMOKE_USER_ID = 5202705269
REQUIRED_DOCTOR_CHECKS = (
    "corp_db_rfc026_schema_objects",
    "corp_db_rfc026_curated_seed",
    "corp_db_rfc026_parent_links",
)


@dataclass(frozen=True)
class ChatReplayExpectation:
    slug: str
    message: str
    expected_route_id: str
    expected_route_kind: str
    expected_tool: str


CHAT_REPLAYS = (
    ChatReplayExpectation(
        slug="series_list",
        message="Какие у вас есть серии светильников?",
        expected_route_id="corp_kb.company_common",
        expected_route_kind="corp_table",
        expected_tool="corp_db_search",
    ),
    ChatReplayExpectation(
        slug="series_descriptions",
        message="В общей базе есть описание всех серий",
        expected_route_id="corp_kb.company_common",
        expected_route_kind="corp_table",
        expected_tool="corp_db_search",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run focused post-incident replay smoke for totosha-pfit.7.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Incident replay dataset JSONL")
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL, help="Core base URL")
    parser.add_argument("--tools-api-url", default=DEFAULT_TOOLS_API_URL, help="Tools API base URL")
    parser.add_argument("--timeout-s", type=float, default=90.0, help="Timeout for HTTP and bench calls")
    parser.add_argument("--user-id", type=int, default=0, help="user_id for /api/chat route checks")
    parser.add_argument("--chat-id", type=int, default=0, help="chat_id for /api/chat route checks")
    parser.add_argument("--docker-exec", action="store_true", help="Pass --docker-exec to bench/bench_run.py")
    parser.add_argument("--skip-doctor", action="store_true", help="Skip RFC-026 doctor checks")
    parser.add_argument("--skip-chat-route-checks", action="store_true", help="Skip /api/chat route replay checks")
    parser.add_argument("--json", action="store_true", help="Print JSON summary only")
    return parser.parse_args()


def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float,
) -> tuple[int, dict[str, Any]]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            text = response.read().decode("utf-8")
            return int(getattr(response, "status", 200)), json.loads(text or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"error": raw[:500]}
        return int(exc.code), payload


def resolve_chat_identity(core_url: str, timeout_s: float, requested_user_id: int, requested_chat_id: int) -> tuple[int, int]:
    if requested_user_id > 0 and requested_chat_id > 0:
        return requested_user_id, requested_chat_id

    env_admin = int(os.getenv("ADMIN_USER_ID", "0") or 0)
    if requested_user_id > 0:
        user_id = requested_user_id
    elif env_admin > 0:
        user_id = env_admin
    else:
        user_id = 0

    if requested_chat_id > 0:
        chat_id = requested_chat_id
    elif env_admin > 0:
        chat_id = env_admin
    else:
        chat_id = 0

    if user_id > 0 and chat_id > 0:
        return user_id, chat_id

    try:
        status, payload = http_json(
            f"{core_url.rstrip('/')}/api/admin/access",
            headers={"X-Request-Id": f"incident-smoke/{uuid.uuid4().hex}/access"},
            timeout_s=timeout_s,
        )
        admin_id = int(payload.get("admin_id") or 0) if status == 200 else 0
    except Exception:
        admin_id = 0

    if admin_id > 0:
        return requested_user_id or admin_id, requested_chat_id or admin_id
    return requested_user_id or DEFAULT_SMOKE_USER_ID, requested_chat_id or DEFAULT_SMOKE_USER_ID


def validate_doctor_results(results: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for check_name in REQUIRED_DOCTOR_CHECKS:
        payload = results.get(check_name)
        if payload is None:
            errors.append(f"doctor_missing:{check_name}")
            continue
        if not bool(payload.get("passed")):
            errors.append(f"doctor_failed:{check_name}:{payload.get('message') or 'unknown'}")
    return errors


def run_doctor_checks() -> list[str]:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from doctor import SecurityDoctor  # noqa: WPS433

    doctor = SecurityDoctor(REPO_ROOT)
    with contextlib.redirect_stdout(io.StringIO()):
        doctor.run_all_checks()
    results = {
        result.name: {
            "passed": result.passed,
            "message": result.message,
            "severity": result.severity,
        }
        for result in doctor.results
    }
    return validate_doctor_results(results)


def run_bench_dataset(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    dataset_path = Path(args.dataset).resolve()
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="incident-pfit7-") as tmpdir:
        results_path = Path(tmpdir) / "results.jsonl"
        summary_path = Path(tmpdir) / "summary.json"
        run_cmd = [
            sys.executable,
            str(REPO_ROOT / "bench" / "bench_run.py"),
            "--dataset",
            str(dataset_path),
            "--out",
            str(results_path),
            "--tools-api-url",
            args.tools_api_url,
            "--timeout-s",
            str(args.timeout_s),
            "--user-id",
            str(args.user_id or DEFAULT_SMOKE_USER_ID),
            "--chat-id",
            str(args.chat_id or DEFAULT_SMOKE_USER_ID),
        ]
        if args.docker_exec:
            run_cmd.append("--docker-exec")
        run_proc = subprocess.run(
            run_cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=max(30, int(args.timeout_s) * 4),
        )
        if run_proc.returncode != 0:
            errors.append(f"bench_run_failed:{run_proc.stderr.strip() or run_proc.stdout.strip()}")
            return {}, errors

        eval_cmd = [
            sys.executable,
            str(REPO_ROOT / "bench" / "bench_eval.py"),
            "--dataset",
            str(dataset_path),
            "--results",
            str(results_path),
            "--json-out",
            str(summary_path),
            "--show-fails",
            "10",
        ]
        eval_proc = subprocess.run(
            eval_cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=max(30, int(args.timeout_s) * 4),
        )
        if eval_proc.returncode != 0:
            errors.append(f"bench_eval_failed:{eval_proc.stderr.strip() or eval_proc.stdout.strip()}")
            return {}, errors

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if float(summary.get("pass_rate") or 0.0) < 1.0 or int(summary.get("fail") or 0) > 0 or int(summary.get("missing_results") or 0) > 0:
            errors.append(
                "bench_replay_failed:"
                f"pass={summary.get('pass')} fail={summary.get('fail')} missing={summary.get('missing_results')}"
            )
        return summary, errors


def validate_chat_replay_response(payload: dict[str, Any], expected: ChatReplayExpectation, request_id: str) -> list[str]:
    errors: list[str] = []
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if not meta:
        return [f"{expected.slug}:missing_meta"]
    if meta.get("status") != "ok":
        errors.append(f"{expected.slug}:meta_status={meta.get('status')}")
    if meta.get("request_id") != request_id:
        errors.append(f"{expected.slug}:request_id={meta.get('request_id')}")
    if meta.get("retrieval_route_id") != expected.expected_route_id:
        errors.append(f"{expected.slug}:route_id={meta.get('retrieval_route_id')}")
    if meta.get("retrieval_selected_route_kind") != expected.expected_route_kind:
        errors.append(f"{expected.slug}:route_kind={meta.get('retrieval_selected_route_kind')}")
    if meta.get("retrieval_selected_source") != "corp_db":
        errors.append(f"{expected.slug}:selected_source={meta.get('retrieval_selected_source')}")
    tools_used = meta.get("tools_used") if isinstance(meta.get("tools_used"), list) else []
    if expected.expected_tool not in tools_used:
        errors.append(f"{expected.slug}:tools_used={tools_used}")
    if not str(payload.get("answer") or "").strip():
        errors.append(f"{expected.slug}:empty_answer")
    return errors


def run_chat_route_checks(args: argparse.Namespace) -> list[str]:
    user_id, chat_id = resolve_chat_identity(args.core_url, args.timeout_s, args.user_id, args.chat_id)
    errors: list[str] = []
    for replay in CHAT_REPLAYS:
        request_id = f"incident-smoke/{replay.slug}/{uuid.uuid4().hex}"
        payload = {
            "user_id": user_id,
            "chat_id": chat_id,
            "message": replay.message,
            "username": "incident_smoke",
            "chat_type": "private",
            "source": "bot",
            "return_meta": True,
        }
        status, response = http_json(
            f"{args.core_url.rstrip('/')}/api/chat",
            method="POST",
            payload=payload,
            headers={"X-Request-Id": request_id},
            timeout_s=args.timeout_s,
        )
        if status != 200:
            errors.append(f"{replay.slug}:http_status={status}")
            continue
        errors.extend(validate_chat_replay_response(response, replay, request_id))
    return errors


def print_summary(summary: dict[str, Any], errors: list[str], *, json_only: bool) -> None:
    if json_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    print("incident replay smoke")
    print(f"- dataset: {summary.get('dataset')}")
    if "bench" in summary:
        bench = summary["bench"]
        print(
            "- bench: "
            f"pass={bench.get('pass')} fail={bench.get('fail')} missing={bench.get('missing_results')} pass_rate={bench.get('pass_rate')}"
        )
    print(f"- doctor_errors: {len(summary.get('doctor_errors', []))}")
    print(f"- chat_route_errors: {len(summary.get('chat_route_errors', []))}")
    if errors:
        print("- failures:")
        for item in errors:
            print(f"  - {item}")
    else:
        print("- status: ok")


def main() -> int:
    args = parse_args()
    all_errors: list[str] = []

    bench_summary, bench_errors = run_bench_dataset(args)
    all_errors.extend(bench_errors)

    doctor_errors: list[str] = []
    if not args.skip_doctor:
        doctor_errors = run_doctor_checks()
        all_errors.extend(doctor_errors)

    chat_errors: list[str] = []
    if not args.skip_chat_route_checks:
        chat_errors = run_chat_route_checks(args)
        all_errors.extend(chat_errors)

    summary = {
        "dataset": str(Path(args.dataset).resolve().relative_to(REPO_ROOT)),
        "bench": bench_summary,
        "doctor_errors": doctor_errors,
        "chat_route_errors": chat_errors,
        "passed": not all_errors,
    }
    print_summary(summary, all_errors, json_only=bool(args.json))
    return 0 if not all_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
