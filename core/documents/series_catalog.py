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


def _validate_series_catalog(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("series catalog must be an object")
    raw_series = payload.get("series")
    if not isinstance(raw_series, list):
        raise ValueError("series catalog must contain a series list")

    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
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
        category_families = item.get("category_families") or []
        if not isinstance(category_families, list):
            raise ValueError(f"series[{index}].category_families must be a list")
        normalized.append(
            {
                "name": name,
                "knowledge_base_label": str(item.get("knowledge_base_label") or name).strip(),
                "category_families": [str(value).strip() for value in category_families if str(value).strip()],
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


def extract_kb_series_labels(markdown: str) -> list[str]:
    return [match.group("label").strip() for match in SERIES_LINE_RE.finditer(markdown or "")]
