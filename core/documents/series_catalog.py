"""Canonical lighting series catalog shared by routing contracts."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
SERIES_CATALOG_PATH = _REPO_ROOT / "db" / "series_catalog.json"
SERIES_KB_PATH = _REPO_ROOT / "docs" / "knowledge_base" / "common_information_about_company.md"
SERIES_LINE_RE = re.compile(r"^- Серия (?P<label>[^-]+?) -", re.MULTILINE)


def normalize_series_alias(value: Any) -> str:
    """Normalize only case and whitespace; safety-significant punctuation stays meaningful."""
    return " ".join(str(value or "").casefold().split())


def _validate_series_catalog(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("series catalog must be an object")
    raw_series = payload.get("series")
    if not isinstance(raw_series, list):
        raise ValueError("series catalog must contain a series list")

    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_aliases: dict[str, str] = {}
    seen_category_families: dict[str, str] = {}
    for index, item in enumerate(raw_series):
        if not isinstance(item, dict):
            raise ValueError(f"series[{index}] must be an object")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"series[{index}].name is required")
        key = name.casefold()
        if key in seen_names:
            raise ValueError(f"duplicate canonical series name: {name}")
        seen_names.add(key)
        family_owner = seen_category_families.get(key)
        if family_owner is not None and family_owner != name:
            raise ValueError(f"category family {name!r} is shared by {family_owner} and {name}")
        seen_category_families[key] = name
        raw_aliases = item.get("aliases") or []
        if not isinstance(raw_aliases, list):
            raise ValueError(f"series[{index}].aliases must be a list")
        aliases: list[str] = []
        local_aliases: set[str] = set()
        for raw_alias in raw_aliases:
            alias = str(raw_alias or "").strip()
            alias_key = normalize_series_alias(alias)
            if not alias_key:
                raise ValueError(f"series[{index}].aliases cannot contain empty values")
            if alias_key in local_aliases:
                raise ValueError(f"duplicate alias for {name}: {alias}")
            owner = seen_aliases.get(alias_key)
            if owner is not None and owner != name:
                raise ValueError(f"series alias {alias!r} is shared by {owner} and {name}")
            local_aliases.add(alias_key)
            seen_aliases[alias_key] = name
            aliases.append(alias)
        raw_category_families = item.get("category_families") or []
        if not isinstance(raw_category_families, list):
            raise ValueError(f"series[{index}].category_families must be a list")
        category_families: list[str] = []
        for raw_family in raw_category_families:
            family = str(raw_family or "").strip()
            if not family:
                raise ValueError(f"series[{index}].category_families cannot contain empty values")
            family_key = family.casefold()
            owner = seen_category_families.get(family_key)
            if owner is not None:
                if owner != name:
                    raise ValueError(f"category family {family!r} is shared by {owner} and {name}")
                continue
            seen_category_families[family_key] = name
            category_families.append(family)
        normalized.append(
            {
                "name": name,
                "knowledge_base_label": str(item.get("knowledge_base_label") or name).strip(),
                "aliases": aliases,
                "category_families": category_families,
            }
        )
    if len(normalized) != 7:
        raise ValueError(f"expected 7 canonical series, found {len(normalized)}")

    result = dict(payload)
    result["series"] = normalized
    return result


@lru_cache(maxsize=1)
def load_canonical_series_catalog() -> dict[str, Any]:
    payload = json.loads(SERIES_CATALOG_PATH.read_text(encoding="utf-8"))
    return _validate_series_catalog(payload)


def canonical_series_names() -> list[str]:
    return [entry["name"] for entry in load_canonical_series_catalog()["series"]]


def _alias_pattern(alias: str) -> re.Pattern[str]:
    tokens = normalize_series_alias(alias).split()
    body = r"\s+".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def explicit_series_alias_candidates(query: Any) -> list[str]:
    """Return canonical series named by non-overlapping, boundary-aware aliases in user text."""
    normalized_query = normalize_series_alias(query)
    if not normalized_query:
        return []
    matches: list[tuple[int, int, str]] = []
    for entry in load_canonical_series_catalog()["series"]:
        aliases = [entry["name"], *entry["aliases"]]
        for alias in aliases:
            matches.extend(
                (match.start(), match.end(), entry["name"])
                for match in _alias_pattern(alias).finditer(normalized_query)
            )
    maximal_matches = [
        match
        for match in matches
        if not any(
            other[0] <= match[0]
            and other[1] >= match[1]
            and (other[1] - other[0]) > (match[1] - match[0])
            for other in matches
        )
    ]
    candidates: list[str] = []
    for _start, _end, name in maximal_matches:
        if name not in candidates:
            candidates.append(name)
    return candidates


def resolve_explicit_series_alias(query: Any) -> str | None:
    """Resolve exactly one explicit alias, returning None for no match or ambiguity."""
    candidates = explicit_series_alias_candidates(query)
    return candidates[0] if len(candidates) == 1 else None


def contains_bare_ex_token(query: Any) -> bool:
    """Detect standalone Ex without treating the suffix in 2Ex as a bare token."""
    return re.search(r"(?<!\w)ex(?!\w)", normalize_series_alias(query), re.IGNORECASE) is not None


def extract_kb_series_labels(markdown: str) -> list[str]:
    return [match.group("label").strip() for match in SERIES_LINE_RE.finditer(markdown or "")]
