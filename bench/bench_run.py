#!/usr/bin/env python3
"""
Bench runner: sends golden dataset questions to Core agent and writes JSONL results.

Usage examples:
  python3 bench/bench_run.py --dataset bench/golden/v1.jsonl --out bench/results/run.jsonl
  python3 bench/bench_run.py --docker-exec --limit 5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

try:
    from .bench_lib import BENCH_DIR, estimate_cost_usd, get_execution, get_validation, load_pricing, repo_rel, resolve_repo_path
except ImportError:  # pragma: no cover - CLI script fallback
    from bench_lib import BENCH_DIR, estimate_cost_usd, get_execution, get_validation, load_pricing, repo_rel, resolve_repo_path


DEFAULT_CORE_URL = "http://127.0.0.1:4000"
DEFAULT_TOOLS_API_URL = "http://127.0.0.1:8100"
DEFAULT_DATASET = BENCH_DIR / "golden" / "v1.jsonl"
DEFAULT_PRICING = BENCH_DIR / "pricing.json"
DEFAULT_RESULTS_DIR = BENCH_DIR / "results"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ") + "_" + secrets.token_hex(3)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except Exception as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{idx}: {exc}") from exc
    return cases


def http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float) -> tuple[int, dict[str, Any], dict[str, str]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={**{"Content-Type": "application/json"}, **headers},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
            parsed = json.loads(body.decode("utf-8") or "{}")
            return int(getattr(resp, "status", 200)), parsed, dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            parsed = {"error": body.decode("utf-8", errors="replace")[:500]}
        return int(exc.code), parsed, dict(exc.headers.items()) if exc.headers else {}


def http_get_json(url: str, headers: dict[str, str], timeout_s: float) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read()
            parsed = json.loads(body.decode("utf-8") or "{}")
            return int(getattr(resp, "status", 200)), parsed
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            parsed = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            parsed = {"error": body.decode("utf-8", errors="replace")[:500]}
        return int(exc.code), parsed


def docker_exec_json_post(path: str, payload: dict[str, Any], request_id: str, timeout_s: float) -> tuple[int, dict[str, Any]]:
    """Call core API from inside core container using curl."""
    raw = json.dumps(payload, ensure_ascii=False)
    raw = raw.replace("'", "'\"'\"'")  # shell-safe single quotes
    cmd = (
        "curl -sS -X POST "
        f"http://localhost:4000{path} "
        "-H 'Content-Type: application/json' "
        f"-H 'X-Request-Id: {request_id}' "
        f"-d '{raw}'"
    )
    result = subprocess.run(
        ["docker", "exec", "core", "sh", "-lc", cmd],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    text = (result.stdout or "") + (result.stderr or "")
    try:
        return result.returncode, json.loads(text)
    except Exception:
        return result.returncode, {"error": text[:500]}


def docker_exec_json_post_url(url: str, payload: dict[str, Any], request_id: str, timeout_s: float, headers: Optional[dict[str, str]] = None) -> tuple[int, dict[str, Any]]:
    raw = json.dumps(payload, ensure_ascii=False)
    raw = raw.replace("'", "'\"'\"'")
    header_args = ["-H 'Content-Type: application/json'", f"-H 'X-Request-Id: {request_id}'"]
    for key, value in (headers or {}).items():
        header_args.append(f"-H '{key}: {value}'")
    cmd = " ".join(["curl -sS -X POST", url, *header_args, f"-d '{raw}'"])
    result = subprocess.run(
        ["docker", "exec", "core", "sh", "-lc", cmd],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    text = (result.stdout or "") + (result.stderr or "")
    try:
        return result.returncode, json.loads(text)
    except Exception:
        return result.returncode, {"error": text[:500]}


def docker_exec_json_get(path: str, request_id: str, timeout_s: float) -> tuple[int, dict[str, Any]]:
    cmd = (
        "curl -sS "
        f"http://localhost:4000{path} "
        f"-H 'X-Request-Id: {request_id}'"
    )
    result = subprocess.run(
        ["docker", "exec", "core", "sh", "-lc", cmd],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    text = (result.stdout or "") + (result.stderr or "")
    try:
        return result.returncode, json.loads(text)
    except Exception:
        return result.returncode, {"error": text[:500]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bench dataset against Core agent and write JSONL results.")
    parser.add_argument("--dataset", default=repo_rel(DEFAULT_DATASET), help="Path to golden dataset JSONL")
    parser.add_argument("--out", default="", help="Output JSONL path (default: bench/results/<run_id>.jsonl)")
    parser.add_argument("--pricing", default=repo_rel(DEFAULT_PRICING), help="Pricing JSON (default: bench/pricing.json)")
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL, help="Core URL when ports are exposed")
    parser.add_argument("--tools-api-url", default=DEFAULT_TOOLS_API_URL, help="Tools API URL for direct_tool mode")
    parser.add_argument("--user-id", type=int, default=None, help="user_id for /api/chat (default: auto)")
    parser.add_argument("--chat-id", type=int, default=None, help="chat_id for /api/chat (default: auto)")
    parser.add_argument("--limit", type=int, default=0, help="Only run first N cases")
    parser.add_argument("--sleep-ms", type=int, default=0, help="Sleep between cases")
    parser.add_argument("--timeout-s", type=float, default=180.0, help="Request timeout (seconds)")
    parser.add_argument("--docker-exec", action="store_true", help="Call core from inside container via docker exec")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    dataset_path = resolve_repo_path(args.dataset)
    pricing_path = resolve_repo_path(args.pricing)
    run_id = make_run_id()
    out_path = resolve_repo_path(args.out) if args.out else DEFAULT_RESULTS_DIR / f"{run_id}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pricing = load_pricing(pricing_path)
    cases = read_jsonl(dataset_path)
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    user_id = args.user_id
    chat_id = args.chat_id
    if user_id is None or chat_id is None:
        if args.docker_exec:
            _code, access = docker_exec_json_get(
                "/api/admin/access",
                request_id=f"bench/{run_id}/access",
                timeout_s=float(args.timeout_s),
            )
            if not (isinstance(access, dict) and "admin_id" in access):
                # Backward-compatible fallback if someone adds a public access endpoint later.
                _code, access = docker_exec_json_get(
                    "/access",
                    request_id=f"bench/{run_id}/access_legacy",
                    timeout_s=float(args.timeout_s),
                )
            admin_id_raw = access.get("admin_id") if isinstance(access, dict) else None
            try:
                admin_id = int(admin_id_raw)
            except Exception:
                admin_id = 0
            if admin_id > 0:
                user_id = admin_id if user_id is None else user_id
                chat_id = admin_id if chat_id is None else chat_id
        else:
            try:
                _status, access = http_get_json(
                    f"{args.core_url.rstrip('/')}/api/admin/access",
                    headers={"X-Request-Id": f"bench/{run_id}/access"},
                    timeout_s=float(args.timeout_s),
                )
                admin_id_raw = access.get("admin_id") if isinstance(access, dict) else None
                admin_id = int(admin_id_raw) if admin_id_raw is not None else 0
                if admin_id > 0:
                    user_id = admin_id if user_id is None else user_id
                    chat_id = admin_id if chat_id is None else chat_id
            except Exception:
                pass

            env_admin = int(os.getenv("ADMIN_USER_ID", "0") or 0)
            if env_admin > 0:
                user_id = env_admin if user_id is None else user_id
                chat_id = env_admin if chat_id is None else chat_id

    if user_id is None or chat_id is None:
        raise SystemExit("Provide --user-id/--chat-id or set ADMIN_USER_ID (or use --docker-exec for auto-detect).")

    print(
        " ".join(
            [
                f"run_id={run_id}",
                f"cases={len(cases)}",
                f"out={repo_rel(out_path)}",
                f"user_id={user_id}",
                f"chat_id={chat_id}",
                f"docker_exec={args.docker_exec}",
            ]
        )
    )

    with out_path.open("w", encoding="utf-8") as f:
        for case in cases:
            case_id = str(case.get("id") or "")
            question = str(case.get("question") or "")
            request_id = f"bench/{run_id}/{case_id}"
            execution = get_execution(case)
            validation = get_validation(case)
            execution_mode = str(execution.get("mode") or "agent_chat")

            started_at = utc_now_iso()
            wall_started = time.perf_counter()

            chat_payload = {
                "user_id": user_id,
                "chat_id": chat_id,
                "message": question,
                "username": "bench",
                "chat_type": "private",
                "source": "bot",
                "return_meta": True,
            }

            status = "ok"
            answer = ""
            meta = None
            http_status = None
            error = ""
            primary_artifact = None
            bench_artifacts = None

            try:
                if execution_mode in {"agent_chat", "agent_chat_shadow"}:
                    clear_payload = {"user_id": user_id, "chat_id": chat_id}
                    if args.docker_exec:
                        docker_exec_json_post("/api/clear", clear_payload, request_id=request_id, timeout_s=float(args.timeout_s))
                    else:
                        http_post_json(
                            f"{args.core_url.rstrip('/')}/api/clear",
                            clear_payload,
                            headers={"X-Request-Id": request_id},
                            timeout_s=float(args.timeout_s),
                        )

                    if args.docker_exec:
                        code, data = docker_exec_json_post("/api/chat", chat_payload, request_id=request_id, timeout_s=float(args.timeout_s))
                        http_status = 200 if code == 0 else 500
                    else:
                        http_status, data, _headers = http_post_json(
                            f"{args.core_url.rstrip('/')}/api/chat",
                            chat_payload,
                            headers={"X-Request-Id": request_id},
                            timeout_s=float(args.timeout_s),
                        )

                    if isinstance(data, dict) and data.get("access_denied"):
                        status = "access_denied"
                    elif isinstance(data, dict) and data.get("disabled"):
                        status = "disabled"

                    if isinstance(data, dict):
                        answer = str(data.get("response") or "")
                        meta_val = data.get("meta")
                        meta = meta_val if isinstance(meta_val, dict) else None
                    else:
                        status = "error"
                        error = "non_json_response"
                        answer = str(data)
                elif execution_mode == "direct_tool":
                    tool_name = str(execution.get("tool") or "")
                    tool_args = execution.get("args") if isinstance(execution.get("args"), dict) else {}
                    if tool_name != "corp_db_search":
                        status = "error"
                        error = f"unsupported_direct_tool:{tool_name or 'missing'}"
                    else:
                        headers = {"X-User-Id": str(user_id), "X-Chat-Type": "private"}
                        if args.docker_exec:
                            code, data = docker_exec_json_post_url(
                                "http://tools-api:8100/corp-db/search",
                                tool_args,
                                request_id=request_id,
                                timeout_s=float(args.timeout_s),
                                headers=headers,
                            )
                            http_status = 200 if code == 0 else 500
                        else:
                            http_status, data, _headers = http_post_json(
                                f"{args.tools_api_url.rstrip('/')}/corp-db/search",
                                tool_args,
                                headers={"X-Request-Id": request_id, **headers},
                                timeout_s=float(args.timeout_s),
                            )

                        if isinstance(data, dict) and http_status == 200:
                            primary_artifact = {
                                "tool": tool_name,
                                "success": True,
                                "kind": str(tool_args.get("kind") or data.get("kind") or ""),
                                "captured_from": "direct_tool",
                                "payload": data,
                            }
                            bench_artifacts = [primary_artifact]
                            meta = {
                                "llm_calls": 0,
                                "llm_time_ms": 0.0,
                                "llm_usage": None,
                                "llm_models": [],
                                "tools_used": [tool_name],
                                "tool_stats": {tool_name: 1},
                                "tools_time_ms": 0.0,
                                "had_search_tool": False,
                                "tool_errors": 0,
                                "retrieval_intent": "",
                                "retrieval_selected_source": "corp_db",
                                "retrieval_explicit_wiki_request": False,
                                "retrieval_wiki_after_corp_db_success": False,
                                "routing_guardrail_hits": 0,
                                "bench_artifacts": bench_artifacts,
                                "primary_artifact": primary_artifact,
                                "bench_artifacts_total_bytes": len(json.dumps(primary_artifact, ensure_ascii=False).encode("utf-8")),
                                "bench_artifacts_dropped": 0,
                            }
                        else:
                            status = "error"
                            error = str(data.get("error") if isinstance(data, dict) else data)[:200]
                else:
                    status = "error"
                    error = f"unsupported_execution_mode:{execution_mode}"
            except subprocess.TimeoutExpired:
                status = "timeout"
                error = "docker_exec_timeout"
            except Exception as exc:
                status = "timeout" if isinstance(exc, TimeoutError) else "error"
                error = str(exc)[:200]

            duration_ms = (time.perf_counter() - wall_started) * 1000
            estimated_cost = estimate_cost_usd(meta, pricing)
            if estimated_cost is None and execution_mode == "direct_tool" and status == "ok":
                estimated_cost = 0.0
            if meta is not None and primary_artifact is None:
                primary_artifact = meta.get("primary_artifact") if isinstance(meta.get("primary_artifact"), dict) else None
            if meta is not None and bench_artifacts is None:
                raw_artifacts = meta.get("bench_artifacts")
                bench_artifacts = raw_artifacts if isinstance(raw_artifacts, list) else None

            record: dict[str, Any] = {
                "run_id": run_id,
                "dataset": str(dataset_path),
                "case_id": case_id,
                "request_id": request_id,
                "started_at": started_at,
                "duration_ms": round(duration_ms, 3),
                "status": status,
                "http_status": http_status,
                "question": question,
                "answer": answer,
                "meta": meta,
                "execution": execution,
                "validation": validation,
                "execution_mode": execution_mode,
                "validation_mode": str(validation.get("mode") or ""),
                "estimated_cost_usd": None if estimated_cost is None else round(float(estimated_cost), 8),
            }
            if primary_artifact is not None:
                record["primary_artifact"] = primary_artifact
            if bench_artifacts is not None:
                record["bench_artifacts"] = bench_artifacts
            if error:
                record["error"] = error

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            if args.sleep_ms and args.sleep_ms > 0:
                time.sleep(args.sleep_ms / 1000.0)

    print("done")


if __name__ == "__main__":
    main()
