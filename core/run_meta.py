"""Per-request agent run metadata for bench/debug.

This module intentionally keeps state in a ContextVar so it can be updated from
different parts of the stack (agent LLM calls, tool execution) without creating
import cycles.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any, Optional

from tool_output_policy import EXECUTION_MODE_RUNTIME, is_benchmark_execution_mode, normalize_execution_mode


RUN_META: ContextVar[Optional[dict[str, Any]]] = ContextVar("run_meta", default=None)
BENCH_ARTIFACTS_MAX_COUNT = 8
BENCH_ARTIFACTS_MAX_BYTES = 128 * 1024


def run_meta_get() -> Optional[dict[str, Any]]:
    return RUN_META.get()


def run_meta_set(meta: dict[str, Any]) -> Any:
    """Return token to be passed into run_meta_reset()."""
    return RUN_META.set(meta)


def run_meta_reset(token: Any) -> None:
    RUN_META.reset(token)


def run_meta_execution_mode(default: str = EXECUTION_MODE_RUNTIME) -> str:
    meta = RUN_META.get()
    if not isinstance(meta, dict):
        return normalize_execution_mode(default)
    return normalize_execution_mode(meta.get("execution_mode"), default=default)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def run_meta_update_llm(duration_ms: float, usage: Optional[dict[str, Any]] = None, model: str = "") -> None:
    meta = RUN_META.get()
    if not meta:
        return

    meta["llm_calls"] = int(meta.get("llm_calls", 0)) + 1
    meta["llm_time_ms"] = float(meta.get("llm_time_ms", 0.0)) + float(duration_ms)

    if model:
        models = meta.get("llm_models")
        if not isinstance(models, list):
            models = []
            meta["llm_models"] = models
        if model not in models:
            models.append(model)

    if not isinstance(usage, dict):
        return

    totals = meta.get("llm_usage")
    if not isinstance(totals, dict):
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0},
        }

    totals["prompt_tokens"] = int(totals.get("prompt_tokens", 0)) + _coerce_int(usage.get("prompt_tokens"))
    totals["completion_tokens"] = int(totals.get("completion_tokens", 0)) + _coerce_int(usage.get("completion_tokens"))
    totals["total_tokens"] = int(totals.get("total_tokens", 0)) + _coerce_int(usage.get("total_tokens"))

    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        totals_prompt_details = totals.get("prompt_tokens_details")
        if not isinstance(totals_prompt_details, dict):
            totals_prompt_details = {"cached_tokens": 0}
        totals_prompt_details["cached_tokens"] = int(totals_prompt_details.get("cached_tokens", 0)) + _coerce_int(
            prompt_details.get("cached_tokens")
        )
        totals["prompt_tokens_details"] = totals_prompt_details

    meta["llm_usage"] = totals


def run_meta_update_tool(name: str, duration_ms: float, success: bool, error: str = "") -> None:
    meta = RUN_META.get()
    if not meta:
        return

    meta["tools_time_ms"] = float(meta.get("tools_time_ms", 0.0)) + float(duration_ms)

    stats = meta.get("tool_stats")
    if not isinstance(stats, dict):
        stats = {}
        meta["tool_stats"] = stats
    stats[name] = int(stats.get(name, 0)) + 1

    tools_used = meta.get("tools_used")
    if not isinstance(tools_used, list):
        tools_used = []
        meta["tools_used"] = tools_used
    if name and name not in tools_used:
        tools_used.append(name)

    if name == "search_web":
        meta["had_search_tool"] = True

    if not success:
        meta["tool_errors"] = int(meta.get("tool_errors", 0)) + 1
        if error:
            last_errors = meta.get("tool_errors_last")
            if not isinstance(last_errors, list):
                last_errors = []
                meta["tool_errors_last"] = last_errors
            # Keep small bounded list for debugging.
            if len(last_errors) < 5:
                last_errors.append({"tool": name, "error": str(error)[:200]})


def run_meta_append_artifact(artifact: dict[str, Any]) -> bool:
    meta = RUN_META.get()
    if not meta or not isinstance(artifact, dict) or not artifact:
        return False
    if not is_benchmark_execution_mode(meta.get("execution_mode")):
        return False

    artifacts = meta.get("bench_artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
        meta["bench_artifacts"] = artifacts

    if len(artifacts) >= BENCH_ARTIFACTS_MAX_COUNT:
        meta["bench_artifacts_dropped"] = int(meta.get("bench_artifacts_dropped", 0)) + 1
        return False

    try:
        serialized = json.dumps(artifact, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        meta["bench_artifacts_dropped"] = int(meta.get("bench_artifacts_dropped", 0)) + 1
        return False

    artifact_size = len(serialized.encode("utf-8"))
    current_size = int(meta.get("bench_artifacts_total_bytes", 0) or 0)
    if current_size + artifact_size > BENCH_ARTIFACTS_MAX_BYTES:
        meta["bench_artifacts_dropped"] = int(meta.get("bench_artifacts_dropped", 0)) + 1
        return False

    artifacts.append(artifact)
    meta["bench_artifacts_total_bytes"] = current_size + artifact_size
    if not isinstance(meta.get("primary_artifact"), dict):
        meta["primary_artifact"] = artifact
    return True
