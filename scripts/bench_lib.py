"""Shared utilities for bench runner/eval/dashboard scripts (stdlib only)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Optional


NUMBER_RE = re.compile(r"(?<!\d)\d+(?:[\.,]\d+)?")


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


def norm_text(text: str) -> str:
    return " ".join((text or "").lower().split())


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
