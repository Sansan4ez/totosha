"""Compact route-argument catalogs shared by routing contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATEGORIES_PATH = _REPO_ROOT / "db" / "categories.json"
SPHERES_PATH = _REPO_ROOT / "db" / "spheres.json"
MOUNTING_TYPES_PATH = _REPO_ROOT / "db" / "mounting_types.json"


def _load_named_values(path: Path, *, list_key: str) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get(list_key)
    if not isinstance(rows, list):
        raise ValueError(f"{path.name} must contain a {list_key} list")

    values: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{list_key}[{index}] must be an object")
        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError(f"{path.name}:{list_key}[{index}].name is required")
        key = name.casefold()
        if key in seen:
            raise ValueError(f"{path.name} contains duplicate name: {name}")
        seen.add(key)
        values.append(name)
    return values


@lru_cache(maxsize=1)
def canonical_sphere_names() -> list[str]:
    return _load_named_values(SPHERES_PATH, list_key="spheres")


@lru_cache(maxsize=1)
def canonical_mounting_type_names() -> list[str]:
    return _load_named_values(MOUNTING_TYPES_PATH, list_key="mountingTypes")


@lru_cache(maxsize=1)
def _category_names_by_id() -> dict[int, str]:
    payload = json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8"))
    rows = payload.get("categories")
    if not isinstance(rows, list):
        raise ValueError("categories.json must contain a categories list")

    result: dict[int, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"categories.json:categories[{index}] must be an object")
        category_id = row.get("id")
        name = str(row.get("name") or "").strip()
        if not isinstance(category_id, int):
            raise ValueError(f"categories.json:categories[{index}].id must be an integer")
        if not name:
            raise ValueError(f"categories.json:categories[{index}].name is required")
        result[category_id] = name
    return result


@lru_cache(maxsize=1)
def curated_category_names_by_sphere() -> dict[str, list[str]]:
    payload = json.loads(SPHERES_PATH.read_text(encoding="utf-8"))
    rows = payload.get("spheres")
    if not isinstance(rows, list):
        raise ValueError("spheres.json must contain a spheres list")

    category_names = _category_names_by_id()
    result: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"spheres.json:spheres[{index}] must be an object")
        sphere_name = str(row.get("name") or "").strip()
        if not sphere_name:
            raise ValueError(f"spheres.json:spheres[{index}].name is required")
        curated = row.get("curatedCategoryIds") or []
        if not isinstance(curated, list):
            raise ValueError(f"spheres.json:spheres[{index}].curatedCategoryIds must be a list")

        scoped_names: list[str] = []
        seen: set[str] = set()
        for item_index, item in enumerate(curated):
            if not isinstance(item, dict):
                raise ValueError(
                    f"spheres.json:spheres[{index}].curatedCategoryIds[{item_index}] must be an object"
                )
            category_id = item.get("id")
            if not isinstance(category_id, int):
                raise ValueError(
                    f"spheres.json:spheres[{index}].curatedCategoryIds[{item_index}].id must be an integer"
                )
            category_name = category_names.get(category_id)
            if not category_name:
                raise ValueError(
                    f"spheres.json:spheres[{index}].curatedCategoryIds[{item_index}].id={category_id} "
                    "does not exist in categories.json"
                )
            key = category_name.casefold()
            if key in seen:
                continue
            seen.add(key)
            scoped_names.append(category_name)
        result[sphere_name] = scoped_names
    return result


def curated_category_names_for_sphere(sphere_name: str) -> list[str]:
    normalized = str(sphere_name or "").strip().casefold()
    if not normalized:
        return []
    for name, categories in curated_category_names_by_sphere().items():
        if name.casefold() == normalized:
            return list(categories)
    return []
