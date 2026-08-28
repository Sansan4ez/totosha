"""Declarative corp_db_search kind contracts used by route schema generation and CI.

This manifest describes operational executor semantics. A field accepted by the global
Pydantic request model is intentionally not considered consumed by every kind.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_LAMP_FILTER_FIELDS = (
    "category",
    "series",
    "mounting_type",
    "beam_pattern",
    "climate_execution",
    "electrical_protection_class",
    "explosion_protection_marking",
    "supply_voltage_raw",
    "dimensions_raw",
    "power_factor_operator",
    "ip",
    "voltage_kind",
    "explosion_protected",
    "power_w_min",
    "power_w_max",
    "flux_lm_min",
    "flux_lm_max",
    "cct_k_min",
    "cct_k_max",
    "weight_kg_min",
    "weight_kg_max",
    "cri_ra_min",
    "cri_ra_max",
    "power_factor_min_min",
    "power_factor_min_max",
    "temp_c_min",
    "temp_c_max",
    "voltage_nominal_v_min",
    "voltage_nominal_v_max",
    "voltage_min_v_min",
    "voltage_min_v_max",
    "voltage_max_v_min",
    "voltage_max_v_max",
    "voltage_tol_minus_pct_min",
    "voltage_tol_minus_pct_max",
    "voltage_tol_plus_pct_min",
    "voltage_tol_plus_pct_max",
    "length_mm_min",
    "length_mm_max",
    "width_mm_min",
    "width_mm_max",
    "height_mm_min",
    "height_mm_max",
    "warranty_years_min",
    "warranty_years_max",
)

_PAGINATION = {
    "limit": "The HTTP dispatcher clamps and forwards the result limit to the kind executor.",
    "offset": "The HTTP dispatcher clamps and forwards the result offset to the kind executor.",
}

# ``variants`` refine requirements when a route locks a discriminator such as
# lookup_direction. ``required_any_of`` represents executor alternatives without
# pretending that every alternative is individually mandatory.
CORP_DB_KIND_CONTRACTS: dict[str, dict[str, Any]] = {
    "hybrid_search": {
        "required": ("query",),
        "consumed": (
            "query", "profile", "knowledge_route_id", "source_files", "topic_facets",
            "entity_types", "include_debug", "fuzzy", *_LAMP_FILTER_FIELDS,
        ),
        "passthrough": {"limit": _PAGINATION["limit"]},
    },
    "lamp_exact": {
        "required": ("name",),
        "consumed": ("name",),
        "passthrough": _PAGINATION,
    },
    "lamp_suggest": {
        "required": ("query",),
        "consumed": ("query", "profile", "entity_types", "include_debug", "fuzzy", *_LAMP_FILTER_FIELDS),
        "passthrough": {"limit": _PAGINATION["limit"]},
    },
    "sku_by_code": {
        "required_any_of": (("etm", "oracl"),),
        "consumed": ("etm", "oracl"),
        "passthrough": _PAGINATION,
    },
    "lamp_code_lookup": {
        "consumed": ("lookup_direction", "code_system", "name", "query", "etm", "oracl"),
        "passthrough": _PAGINATION,
        "variants": (
            {
                "when": {"lookup_direction": "by_name"},
                "required": ("name",),
                "consumed": ("lookup_direction", "code_system", "name"),
            },
            {
                "when": {"lookup_direction": "by_code"},
                "required_any_of": (("query", "etm", "oracl"),),
                "consumed": ("lookup_direction", "code_system", "query", "etm", "oracl"),
            },
        ),
    },
    "lamp_documents_index": {
        "required_any_of": (("names", "name"),),
        "consumed": ("names", "name", "document_type"),
        "passthrough": _PAGINATION,
    },
    "showcase_category_lamps": {
        "required": ("category",),
        "consumed": ("category", "fuzzy"),
        "passthrough": _PAGINATION,
    },
    "application_recommendation": {
        "required": ("query",),
        "consumed": (
            "query", "application_key", "context_profile", "limit_categories", "limit_lamps",
            "limit_portfolio", *_LAMP_FILTER_FIELDS,
        ),
        "passthrough": _PAGINATION,
    },
    "category_lamps": {
        "required": ("category",),
        "consumed": ("category", "fuzzy", *_LAMP_FILTER_FIELDS),
        "passthrough": _PAGINATION,
    },
    "portfolio_by_sphere": {
        "required": ("sphere",),
        "consumed": ("sphere", "fuzzy"),
        "passthrough": _PAGINATION,
    },
    "portfolio_examples_by_lamp": {
        "required": ("name",),
        "consumed": ("name",),
        "passthrough": _PAGINATION,
    },
    "sphere_curated_categories": {
        "required": ("sphere",),
        "consumed": ("sphere", "fuzzy"),
        "passthrough": {},
    },
    "sphere_categories": {
        "required": ("sphere",),
        "consumed": ("sphere", "fuzzy"),
        "passthrough": _PAGINATION,
    },
    "lamp_filters": {
        "required": (),
        "consumed": _LAMP_FILTER_FIELDS,
        "passthrough": _PAGINATION,
    },
    "category_mountings": {
        "required_any_of": (("category", "series", "mounting_type"),),
        "consumed": ("category", "series", "mounting_type"),
        "passthrough": _PAGINATION,
    },
}

# Temporary exceptions are intentionally centralized. Every entry must name an open br
# issue and explain why the executable mismatch remains. CI validates this metadata before
# applying a waiver.
CORP_DB_CONTRACT_WAIVERS: tuple[dict[str, Any], ...] = ()


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def contract_for_kind(kind: str, fixed_args: dict[str, Any] | None = None) -> dict[str, Any] | None:
    base = CORP_DB_KIND_CONTRACTS.get(str(kind or "").strip())
    if base is None:
        return None
    fixed = dict(fixed_args or {})
    required = list(base.get("required") or ())
    required_any_of = [tuple(group) for group in base.get("required_any_of") or ()]
    consumed = tuple(base.get("consumed") or ())
    passthrough = dict(base.get("passthrough") or {})
    for variant in base.get("variants") or ():
        when = dict(variant.get("when") or {})
        if when and all(fixed.get(key) == value for key, value in when.items()):
            required.extend(variant.get("required") or ())
            required_any_of.extend(tuple(group) for group in variant.get("required_any_of") or ())
            if "consumed" in variant:
                consumed = tuple(variant.get("consumed") or ())
            if "passthrough" in variant:
                passthrough = dict(variant.get("passthrough") or {})
    return {
        "required": tuple(dict.fromkeys(str(field) for field in required)),
        "required_any_of": tuple(dict.fromkeys(group) for group in required_any_of),
        "consumed": frozenset(str(field) for field in consumed),
        "passthrough": passthrough,
    }


def allowed_fields_for_kind(kind: str, fixed_args: dict[str, Any] | None = None) -> frozenset[str]:
    contract = contract_for_kind(kind, fixed_args)
    if contract is None:
        return frozenset()
    required_alternatives = {field for group in contract["required_any_of"] for field in group}
    return frozenset(contract["consumed"] | set(contract["passthrough"]) | set(contract["required"]) | required_alternatives)


def apply_requirements(
    schema: dict[str, Any],
    *,
    kind: str,
    fixed_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply manifest requirements to a schema after route-specific property pruning."""
    contract = contract_for_kind(kind, fixed_args)
    if contract is None:
        return schema
    fixed = dict(fixed_args or {})
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required: set[str] = set()
    any_of: list[dict[str, list[str]]] = []

    for field in contract["required"]:
        if _has_value(fixed.get(field)):
            continue
        if field in properties:
            required.add(field)

    for group in contract["required_any_of"]:
        if any(_has_value(fixed.get(field)) for field in group):
            continue
        available = [field for field in group if field in properties]
        if len(available) == 1:
            required.add(available[0])
        elif len(available) > 1:
            any_of.extend({"required": [field]} for field in available)

    ordered_properties = list(properties)
    schema["required"] = [field for field in ordered_properties if field in required]
    if any_of:
        schema["anyOf"] = any_of
    else:
        schema.pop("anyOf", None)
    return schema


def validate_waivers(repo_root: Path) -> list[str]:
    errors: list[str] = []
    issue_statuses: dict[str, str] = {}
    issues_path = repo_root / ".beads" / "issues.jsonl"
    if CORP_DB_CONTRACT_WAIVERS and issues_path.is_file():
        for line in issues_path.read_text(encoding="utf-8").splitlines():
            try:
                issue = json.loads(line)
            except json.JSONDecodeError:
                continue
            issue_statuses[str(issue.get("id") or "")] = str(issue.get("status") or "")
    for index, waiver in enumerate(CORP_DB_CONTRACT_WAIVERS):
        prefix = f"corp-db contract waiver #{index + 1}"
        issue_id = str(waiver.get("issue_id") or "").strip()
        comment = str(waiver.get("comment") or "").strip()
        if not issue_id or not comment:
            errors.append(f"{prefix}: issue_id and comment are required")
        elif issue_statuses.get(issue_id) not in {"open", "in_progress"}:
            errors.append(f"{prefix}: issue {issue_id} must exist and remain open")
    return errors


def waiver_fields(route_id: str, mismatch: str) -> frozenset[str]:
    fields: set[str] = set()
    for waiver in CORP_DB_CONTRACT_WAIVERS:
        if waiver.get("route_id") == route_id and waiver.get("mismatch") == mismatch:
            fields.update(str(field) for field in waiver.get("fields") or ())
    return frozenset(fields)
