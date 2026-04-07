"""Shared utilities for the bench module (stdlib only)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Optional


NUMBER_RE = re.compile(r"(?<!\d)\d+(?:[\.,]\d+)?")
DASH_VARIANTS_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent
SOURCE_ALIASES = {
    "wiki": "doc_search",
    "doc_search": "doc_search",
    "corp_db": "corp_db",
}
TOOL_ALIASES = {
    "corp_wiki_search": "doc_search",
    "doc_search": "doc_search",
}
EXECUTION_MODES = {"agent_chat", "direct_tool", "agent_chat_shadow"}
VALIDATION_MODES = {"legacy_text", "algorithmic", "hybrid", "routing_only"}


def _infer_selected_source(meta: dict[str, Any]) -> str:
    raw = str(meta.get("retrieval_selected_source") or "unknown")
    normalized = SOURCE_ALIASES.get(raw, raw)
    if normalized != "unknown":
        return normalized

    tools_used_raw = meta.get("tools_used") if isinstance(meta.get("tools_used"), list) else []
    tools_used = {TOOL_ALIASES.get(str(tool), str(tool)) for tool in tools_used_raw if isinstance(tool, str)}
    if "doc_search" in tools_used:
        return "doc_search"
    if {"run_command", "list_directory", "read_file", "search_text"} & tools_used and "corp_db_search" in tools_used:
        return "doc_search"
    if "corp_db_search" in tools_used:
        return "corp_db"
    return normalized


def resolve_repo_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def repo_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            val = json.loads(line)
        except Exception as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{idx}: {exc}") from exc
        if not isinstance(val, dict):
            raise SystemExit(f"Expected object JSON at {path}:{idx}")
        rows.append(val)
    return rows


def load_pricing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"default": {"prompt_per_1m_usd": 0.0, "completion_per_1m_usd": 0.0}, "models": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Invalid pricing JSON at {path}: {exc}") from exc


def get_execution(case: dict[str, Any]) -> dict[str, Any]:
    execution = case.get("execution") if isinstance(case.get("execution"), dict) else {}
    mode = str(execution.get("mode") or "agent_chat")
    if mode not in EXECUTION_MODES:
        mode = "agent_chat"
    return {**execution, "mode": mode}


def get_validation(case: dict[str, Any]) -> dict[str, Any]:
    validation = case.get("validation") if isinstance(case.get("validation"), dict) else {}
    mode = str(validation.get("mode") or "")
    if mode not in VALIDATION_MODES:
        golden = case.get("golden") if isinstance(case.get("golden"), dict) else {}
        checks = golden.get("checks") if isinstance(golden.get("checks"), list) else []
        mode = "legacy_text" if checks else "routing_only"
    return {**validation, "mode": mode}


def get_text_checks(case: dict[str, Any], validation: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    validation = validation if isinstance(validation, dict) else get_validation(case)
    checks = validation.get("text_checks")
    if isinstance(checks, list):
        return checks
    golden = case.get("golden") if isinstance(case.get("golden"), dict) else {}
    checks = golden.get("checks")
    return checks if isinstance(checks, list) else []


def get_structured_checks(case: dict[str, Any], validation: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    validation = validation if isinstance(validation, dict) else get_validation(case)
    checks = validation.get("checks")
    return checks if isinstance(checks, list) else []


def get_result_meta(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("meta")
    return meta if isinstance(meta, dict) else {}


def get_result_artifacts(row: dict[str, Any]) -> list[dict[str, Any]]:
    meta = get_result_meta(row)
    artifacts = meta.get("bench_artifacts")
    if not isinstance(artifacts, list):
        artifacts = row.get("bench_artifacts")
    if not isinstance(artifacts, list):
        return []
    return [item for item in artifacts if isinstance(item, dict)]


def get_primary_artifact(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    meta = get_result_meta(row)
    primary = meta.get("primary_artifact")
    if isinstance(primary, dict):
        return primary
    primary = row.get("primary_artifact")
    return primary if isinstance(primary, dict) else None


def _read_price_unit(entry: dict[str, Any], prompt_key: str, completion_key: str, legacy_prompt_key: str, legacy_completion_key: str) -> tuple[float, float]:
    if prompt_key in entry or completion_key in entry:
        return (
            float(entry.get(prompt_key, 0.0) or 0.0),
            float(entry.get(completion_key, 0.0) or 0.0),
        )
    if legacy_prompt_key in entry or legacy_completion_key in entry:
        return (
            float(entry.get(legacy_prompt_key, 0.0) or 0.0) * 1000.0,
            float(entry.get(legacy_completion_key, 0.0) or 0.0) * 1000.0,
        )
    return (0.0, 0.0)


def _read_cached_input_price(entry: dict[str, Any], default_value: float) -> float:
    if "cached_input_per_1m_usd" in entry:
        return float(entry.get("cached_input_per_1m_usd", default_value) or default_value)
    if "cached_input_per_1k_usd" in entry:
        return float(entry.get("cached_input_per_1k_usd", 0.0) or 0.0) * 1000.0
    return default_value


def pick_price(pricing: dict[str, Any], model: str) -> tuple[float, float, float]:
    default = pricing.get("default") or {}
    default_prompt, default_completion = _read_price_unit(
        default,
        prompt_key="prompt_per_1m_usd",
        completion_key="completion_per_1m_usd",
        legacy_prompt_key="prompt_per_1k_usd",
        legacy_completion_key="completion_per_1k_usd",
    )
    default_cached_input = _read_cached_input_price(default, default_prompt)

    for entry in pricing.get("models") or []:
        if not isinstance(entry, dict):
            continue
        match = str(entry.get("match", "") or "")
        if match and match in model:
            prompt_per_1m, completion_per_1m = _read_price_unit(
                entry,
                prompt_key="prompt_per_1m_usd",
                completion_key="completion_per_1m_usd",
                legacy_prompt_key="prompt_per_1k_usd",
                legacy_completion_key="completion_per_1k_usd",
            )
            cached_input_per_1m = _read_cached_input_price(entry, default_cached_input)
            return (
                prompt_per_1m or default_prompt,
                cached_input_per_1m,
                completion_per_1m or default_completion,
            )

    return default_prompt, default_cached_input, default_completion


def estimate_cost_usd(meta: Optional[dict[str, Any]], pricing: dict[str, Any]) -> Optional[float]:
    if not meta:
        return None
    usage = meta.get("llm_usage")
    if not isinstance(usage, dict):
        return None

    model = ""
    llm_models = meta.get("llm_models")
    if isinstance(llm_models, list) and llm_models:
        model = str(llm_models[-1])
    if not model:
        model = str(meta.get("model", "") or "")

    prompt_per_1m, cached_input_per_1m, completion_per_1m = pick_price(pricing, model)
    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    cached_tokens = int(prompt_details.get("cached_tokens", 0) or 0)
    cached_tokens = max(0, min(cached_tokens, prompt_tokens))
    uncached_prompt_tokens = max(0, prompt_tokens - cached_tokens)

    return (
        (uncached_prompt_tokens / 1_000_000.0) * prompt_per_1m
        + (cached_tokens / 1_000_000.0) * cached_input_per_1m
        + (completion_tokens / 1_000_000.0) * completion_per_1m
    )


def parse_path(path: str) -> list[tuple[str, Optional[str]]]:
    if not path:
        return []
    parts = []
    for raw_part in path.split("."):
        part = raw_part.strip()
        if not part:
            raise ValueError(f"bad_path:{path}")
        match = re.fullmatch(r"([^\[\]]+)(?:\[(\*|\d+)])?", part)
        if not match:
            raise ValueError(f"bad_path:{path}")
        parts.append((match.group(1), match.group(2)))
    return parts


def resolve_path_values(data: Any, path: str) -> tuple[list[Any], Optional[str]]:
    if not path:
        return [data], None
    try:
        parts = parse_path(path)
    except ValueError as exc:
        return [], str(exc)

    current: list[Any] = [data]
    for key, index_token in parts:
        next_values: list[Any] = []
        for item in current:
            if not isinstance(item, dict) or key not in item:
                continue
            value = item.get(key)
            if index_token is None:
                next_values.append(value)
                continue
            if not isinstance(value, list):
                continue
            if index_token == "*":
                next_values.extend(value)
                continue
            idx = int(index_token)
            if 0 <= idx < len(value):
                next_values.append(value[idx])
        current = next_values
        if not current:
            return [], f"path_not_found:{path}"
    return current, None


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        nums = extract_numbers(value)
        if nums:
            return float(nums[0])
    return None


def _string_values(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out.append(str(value))
    return out


def check_equals(values: list[Any], expected: Any) -> tuple[bool, str]:
    if any(value == expected for value in values):
        return True, ""
    return False, f"expected={expected!r} actual={values[:5]!r}"


def check_one_of(values: list[Any], expected: list[Any]) -> tuple[bool, str]:
    if any(value in expected for value in values):
        return True, ""
    return False, f"expected_one_of={expected!r} actual={values[:5]!r}"


def check_exists(values: list[Any]) -> tuple[bool, str]:
    if values:
        return True, ""
    return False, "missing"


def check_len_gte(values: list[Any], expected: int) -> tuple[bool, str]:
    target = values[0] if len(values) == 1 else values
    if isinstance(target, (list, str, dict)):
        actual = len(target)
    else:
        actual = len(values)
    if actual >= expected:
        return True, ""
    return False, f"expected_len>={expected} actual={actual}"


def check_path_contains_any(values: list[Any], expected: list[str]) -> tuple[bool, str]:
    strings = [norm_text(item) for item in _string_values(values)]
    needles = [norm_text(item) for item in expected]
    for hay in strings:
        if any(needle in hay for needle in needles):
            return True, ""
    return False, f"none_of={expected!r}"


def check_all_prefix(values: list[Any], prefix: str) -> tuple[bool, str]:
    strings = _string_values(values)
    if not strings:
        return False, "no_values"
    if all(item.startswith(prefix) for item in strings):
        return True, ""
    return False, f"prefix={prefix!r} actual={strings[:5]!r}"


def check_number_eq(values: list[Any], expected: float, tolerance: float) -> tuple[bool, str]:
    numbers = [num for num in (_coerce_number(value) for value in values) if num is not None]
    if not numbers:
        return False, "no_numbers"
    if any(abs(number - expected) <= tolerance for number in numbers):
        return True, ""
    return False, f"expected={expected}±{tolerance} actual={numbers[:5]!r}"


def check_number_range(values: list[Any], min_value: Optional[float], max_value: Optional[float]) -> tuple[bool, str]:
    numbers = [num for num in (_coerce_number(value) for value in values) if num is not None]
    if not numbers:
        return False, "no_numbers"
    for number in numbers:
        if min_value is not None and number < min_value:
            continue
        if max_value is not None and number > max_value:
            continue
        return True, ""
    return False, f"expected_range=[{min_value},{max_value}] actual={numbers[:5]!r}"


def select_artifact(row: dict[str, Any], selector: Optional[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], Any, Optional[str]]:
    primary = get_primary_artifact(row)
    artifacts = get_result_artifacts(row)
    if primary and primary not in artifacts:
        artifacts = [primary] + artifacts
    if not artifacts:
        return None, None, "missing_artifact"

    selector = selector if isinstance(selector, dict) else {}
    tool = str(selector.get("tool") or "")
    kind = str(selector.get("kind") or "")
    all_matches = bool(selector.get("all_matches"))
    matching: list[dict[str, Any]] = []
    for artifact in artifacts:
        artifact_tool = str(artifact.get("tool") or "")
        artifact_kind = str(artifact.get("kind") or "")
        if tool and artifact_tool != tool:
            continue
        if kind and artifact_kind != kind:
            continue
        if all_matches:
            matching.append(artifact)
            continue
        return artifact, artifact.get("payload"), None
    if all_matches and matching:
        payloads = [artifact.get("payload") for artifact in matching if isinstance(artifact.get("payload"), dict)]
        combined_payload: dict[str, Any] = {}
        if payloads:
            combined_payload.update(payloads[0])
        combined_results: list[Any] = []
        queries: list[str] = []
        for payload in payloads:
            if isinstance(payload.get("results"), list):
                combined_results.extend(payload.get("results") or [])
            query = payload.get("query")
            if isinstance(query, str) and query:
                queries.append(query)
        if combined_results:
            combined_payload["results"] = combined_results
            combined_payload["result_count"] = len(combined_results)
        if queries:
            combined_payload["queries"] = queries
        if payloads and "status" not in combined_payload:
            combined_payload["status"] = payloads[0].get("status")
        combined_artifact = {
            "tool": tool or str(matching[0].get("tool") or ""),
            "kind": kind or str(matching[0].get("kind") or ""),
            "combined_artifacts": len(matching),
        }
        return combined_artifact, combined_payload, None
    return None, None, f"missing_artifact_selector:tool={tool or '*'} kind={kind or '*'}"


def eval_algorithmic_payload(payload: Any, checks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            errors.append("bad_check_format")
            continue
        ctype = str(check.get("type") or "")
        path = str(check.get("path") or "")
        values, path_error = resolve_path_values(payload, path)
        if path_error:
            errors.append(f"{ctype}:{path_error}")
            continue

        if ctype == "equals":
            ok, msg = check_equals(values, check.get("value"))
        elif ctype == "one_of":
            val = check.get("value")
            if not isinstance(val, list):
                errors.append("one_of:bad_value")
                continue
            ok, msg = check_one_of(values, val)
        elif ctype == "exists":
            ok, msg = check_exists(values)
        elif ctype == "len_gte":
            try:
                expected = int(check.get("value"))
            except Exception:
                errors.append("len_gte:bad_value")
                continue
            ok, msg = check_len_gte(values, expected)
        elif ctype == "contains_any":
            val = check.get("value")
            if not isinstance(val, list) or not all(isinstance(item, str) for item in val):
                errors.append("contains_any:bad_value")
                continue
            ok, msg = check_path_contains_any(values, val)
        elif ctype == "all_prefix":
            prefix = str(check.get("value") or "")
            if not prefix:
                errors.append("all_prefix:bad_value")
                continue
            ok, msg = check_all_prefix(values, prefix)
        elif ctype == "number_eq":
            try:
                expected = float(check.get("value"))
                tolerance = float(check.get("tolerance", 0) or 0)
            except Exception:
                errors.append("number_eq:bad_value")
                continue
            ok, msg = check_number_eq(values, expected, tolerance)
        elif ctype == "number_range":
            min_value = _coerce_number(check.get("min"))
            max_value = _coerce_number(check.get("max"))
            ok, msg = check_number_range(values, min_value, max_value)
        else:
            errors.append(f"unknown_check_type:{ctype}")
            continue

        if not ok:
            errors.append(f"{ctype}:{msg}")
    return (len(errors) == 0), errors


def eval_algorithmic(row: dict[str, Any], validation: dict[str, Any]) -> tuple[bool, list[str], Optional[dict[str, Any]], Any]:
    selector = validation.get("artifact_selector") if isinstance(validation.get("artifact_selector"), dict) else {}
    checks = get_structured_checks({}, validation)
    artifact, payload, select_error = select_artifact(row, selector)
    if select_error:
        return False, [select_error], artifact, payload
    ok, errors = eval_algorithmic_payload(payload, checks)
    return ok, errors, artifact, payload


def norm_text(text: str) -> str:
    normalized = DASH_VARIANTS_RE.sub("-", text or "")
    return " ".join(normalized.lower().split())


def extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for raw in NUMBER_RE.findall(text or ""):
        raw_norm = raw.replace(",", ".")
        try:
            values.append(float(raw_norm))
        except Exception:
            continue
    return values


def percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    d0 = s[f] * (c - k)
    d1 = s[c] * (k - f)
    return d0 + d1


def check_contains_all(answer: str, expected: list[str]) -> tuple[bool, str]:
    a = norm_text(answer)
    missing = [s for s in expected if norm_text(s) not in a]
    if missing:
        return False, f"missing={missing}"
    return True, ""


def check_contains_any(answer: str, expected: list[str]) -> tuple[bool, str]:
    a = norm_text(answer)
    for s in expected:
        if norm_text(s) in a:
            return True, ""
    return False, f"none_of={expected}"


def check_regex(answer: str, pattern: str) -> tuple[bool, str]:
    try:
        ok = re.search(pattern, answer or "", flags=re.IGNORECASE | re.MULTILINE) is not None
        return ok, "" if ok else f"no_match={pattern}"
    except re.error as exc:
        return False, f"bad_regex={exc}"


def check_number(answer: str, value: float, tolerance: float) -> tuple[bool, str]:
    nums = extract_numbers(answer)
    if not nums:
        return False, "no_numbers"
    for n in nums:
        if abs(n - value) <= tolerance:
            return True, ""
    return False, f"expected={value}±{tolerance} got={nums[:10]}"


def eval_checks(answer: str, checks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            errors.append("bad_check_format")
            continue
        ctype = str(check.get("type") or "")
        if ctype in ("contains_all", "contains_any"):
            val = check.get("value")
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                errors.append(f"{ctype}:bad_value")
                continue
            ok, msg = (check_contains_all(answer, val) if ctype == "contains_all" else check_contains_any(answer, val))
            if not ok:
                errors.append(f"{ctype}:{msg}")
            continue

        if ctype == "regex":
            pattern = str(check.get("pattern") or check.get("value") or "")
            if not pattern:
                errors.append("regex:missing_pattern")
                continue
            ok, msg = check_regex(answer, pattern)
            if not ok:
                errors.append(f"regex:{msg}")
            continue

        if ctype == "number":
            try:
                value = float(check.get("value"))
            except Exception:
                errors.append("number:bad_value")
                continue
            tol_raw = check.get("tolerance", 0)
            try:
                tolerance = float(tol_raw)
            except Exception:
                tolerance = 0.0
            ok, msg = check_number(answer, value=value, tolerance=tolerance)
            if not ok:
                errors.append(f"number:{msg}")
            continue

        errors.append(f"unknown_check_type:{ctype}")

    return (len(errors) == 0), errors


def eval_routing(meta: Optional[dict[str, Any]], routing: Optional[dict[str, Any]]) -> tuple[bool, list[str]]:
    if not isinstance(routing, dict) or not routing:
        return True, []

    errors: list[str] = []
    if not isinstance(meta, dict):
        return False, ["routing:no_meta"]

    expected_source = routing.get("selected_source")
    if expected_source:
        actual_source = _infer_selected_source(meta)
        expected_source_norm = SOURCE_ALIASES.get(str(expected_source), str(expected_source))
        if actual_source != expected_source_norm:
            errors.append(f"routing:selected_source expected={expected_source} actual={actual_source}")

    expected_intent = routing.get("intent")
    if expected_intent:
        actual_intent = str(meta.get("retrieval_intent") or "")
        if actual_intent and actual_intent != str(expected_intent):
            errors.append(f"routing:intent expected={expected_intent} actual={actual_intent}")

    if "wiki_after_corp_db_success" in routing:
        expected = bool(routing.get("wiki_after_corp_db_success"))
        actual = bool(meta.get("retrieval_wiki_after_corp_db_success"))
        if actual != expected:
            errors.append(f"routing:wiki_after_corp_db_success expected={expected} actual={actual}")

    if "guardrail_hits_max" in routing:
        try:
            max_hits = int(routing.get("guardrail_hits_max"))
        except Exception:
            max_hits = 0
        actual_hits = int(meta.get("routing_guardrail_hits", 0) or 0)
        if actual_hits > max_hits:
            errors.append(f"routing:guardrail_hits expected<={max_hits} actual={actual_hits}")

    forbid_tools = routing.get("forbid_tools")
    if isinstance(forbid_tools, list):
        tools_used_raw = meta.get("tools_used") if isinstance(meta.get("tools_used"), list) else []
        tools_used = {TOOL_ALIASES.get(str(tool), str(tool)) for tool in tools_used_raw if isinstance(tool, str)}
        used = []
        for tool in forbid_tools:
            if not isinstance(tool, str):
                continue
            normalized = TOOL_ALIASES.get(tool, tool)
            if normalized in tools_used:
                used.append(tool)
        if used:
            errors.append(f"routing:forbid_tools_used={used}")

    return (len(errors) == 0), errors


def evaluate_case_result(case: dict[str, Any], row: Optional[dict[str, Any]]) -> dict[str, Any]:
    validation = get_validation(case)
    mode = str(validation.get("mode") or "legacy_text")
    routing = case.get("routing") if isinstance(case.get("routing"), dict) else {}

    if row is None:
        return {
            "mode": mode,
            "passed": False,
            "status": "missing_result",
            "answer_ok": False,
            "algorithmic_ok": False,
            "routing_ok": False,
            "errors": ["missing_result"],
            "artifact": None,
            "payload": None,
        }

    status = str(row.get("status") or "ok")
    answer = str(row.get("answer") or "")
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else None
    routing_ok, routing_errors = eval_routing(meta, routing)

    if status != "ok":
        return {
            "mode": mode,
            "passed": False,
            "status": status,
            "answer_ok": False,
            "algorithmic_ok": False,
            "routing_ok": routing_ok,
            "errors": [f"status={status}"],
            "artifact": None,
            "payload": None,
        }

    text_checks = get_text_checks(case, validation)
    answer_ok, answer_errors = eval_checks(answer, text_checks) if text_checks else (True, [])
    algorithmic_ok = True
    algorithmic_errors: list[str] = []
    artifact = None
    payload = None

    if mode in {"algorithmic", "hybrid"}:
        algorithmic_ok, algorithmic_errors, artifact, payload = eval_algorithmic(row, validation)

    if mode == "legacy_text":
        passed = answer_ok and routing_ok
        errors = answer_errors + routing_errors
    elif mode == "algorithmic":
        passed = algorithmic_ok and routing_ok
        errors = algorithmic_errors + routing_errors
    elif mode == "hybrid":
        passed = answer_ok and algorithmic_ok and routing_ok
        errors = answer_errors + algorithmic_errors + routing_errors
    elif mode == "routing_only":
        passed = routing_ok
        errors = routing_errors
    else:
        passed = answer_ok and routing_ok
        errors = answer_errors + routing_errors

    return {
        "mode": mode,
        "passed": bool(passed),
        "status": status,
        "answer_ok": bool(answer_ok),
        "algorithmic_ok": bool(algorithmic_ok),
        "routing_ok": bool(routing_ok),
        "errors": errors,
        "artifact": artifact,
        "payload": payload,
    }
