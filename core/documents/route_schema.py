"""Runtime route-card schema and selector argument validation.

RFC-025 route cards are the shared contract between generated catalogs, the
runtime router, selector prompts, and tests. This module intentionally supports
only the JSON Schema subset needed for route tool arguments:

- object schemas with declared properties only
- string, integer, number, boolean, array, and object value checks
- enum, numeric bounds, string pattern/maxLength, array maxItems, and required
- compact enum enforcement so selector prompts do not carry large finite domains

Argument merge order is:

1. ``executor_args_template`` provides route defaults.
2. validated selector ``tool_args`` may override defaults.
3. ``locked_args`` are applied last and cannot be changed by selector output.

Invalid selector JSON/arguments may be repaired once by the caller. Unsafe
selector output is rejected outright.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


MAX_COMPACT_ENUM_VALUES = 60
MAX_COMPACT_ENUM_VALUE_LENGTH = 80
MAX_SELECTOR_STRING_LENGTH = 600

ROUTE_CONTRACT_FIELDS = (
    "argument_schema",
    "locked_args",
    "argument_hints",
    "evidence_policy",
    "fallback_route_ids",
    "cross_family_fallback_route_ids",
    "fallback_policy",
    "document_selectors",
    "table_scopes",
    "negative_keywords",
)

PROHIBITED_SELECTOR_KEYS = {
    "command",
    "commands",
    "executor",
    "executor_args_template",
    "evidence_policy",
    "evidence_policy_override",
    "path",
    "paths",
    "shell",
    "sql",
    "tool",
    "tool_name",
}
EVIDENCE_BYPASS_KEYS = {
    "bypass_evidence",
    "bypass_evidence_policy",
    "disable_evidence",
    "skip_evidence",
}
SAFE_SELECTOR_KEYS = {
    "selected_family_id",
    "selected_route_id",
    "confidence",
    "reason",
    "tool_args",
    "fallback_route_ids",
}


class RouteCardContractError(ValueError):
    """Route card does not satisfy the runtime route-card contract."""


class RouteSelectorOutputError(ValueError):
    """Selector output is invalid or unsafe."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SelectorValidationResult:
    valid: bool
    selected_family_id: str = ""
    selected_route_id: str = ""
    route: dict[str, Any] | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    fallback_route_ids: list[str] = field(default_factory=list)
    error_code: str = ""
    error: str = ""
    repairable: bool = False
    repair_prompt: str = ""


def _dedupe_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _infer_property_schema(value: Any) -> dict[str, Any]:
    value_type = _infer_type(value)
    schema: dict[str, Any] = {"type": value_type}
    if value_type == "string":
        schema["maxLength"] = MAX_SELECTOR_STRING_LENGTH
    elif value_type == "array":
        schema["maxItems"] = 20
        item_schema = {"type": "string", "maxLength": 160}
        for item in value:
            if item is not None:
                item_schema = _infer_property_schema(item)
                break
        schema["items"] = item_schema
    elif value_type == "object":
        schema["additionalProperties"] = False
        schema["properties"] = {
            str(key): _infer_property_schema(item)
            for key, item in value.items()
            if str(key).strip()
        }
    return schema


def _string_property(max_length: int = MAX_SELECTOR_STRING_LENGTH, pattern: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "maxLength": max_length}
    if pattern:
        schema["pattern"] = pattern
    return schema


def _string_array_property(max_items: int = 20, item_max_length: int = 160) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": max_items,
        "items": {"type": "string", "maxLength": item_max_length},
    }


def _corp_db_argument_properties() -> dict[str, dict[str, Any]]:
    kind_values = [
        "hybrid_search",
        "lamp_exact",
        "lamp_suggest",
        "sku_by_code",
        "application_recommendation",
        "category_lamps",
        "portfolio_by_sphere",
        "portfolio_examples_by_lamp",
        "sphere_curated_categories",
        "sphere_categories",
        "lamp_filters",
        "category_mountings",
    ]
    profile_values = [
        "kb_search",
        "kb_route_lookup",
        "entity_resolver",
        "candidate_generation",
        "related_evidence",
    ]
    properties: dict[str, dict[str, Any]] = {
        "kind": {"type": "string", "enum": kind_values},
        "query": _string_property(500),
        "profile": {"type": "string", "enum": profile_values},
        "knowledge_route_id": _string_property(120, r"^[A-Za-z0-9_.-]+$"),
        "source_files": _string_array_property(10, 180),
        "topic_facets": _string_array_property(12, 80),
        "entity_types": _string_array_property(12, 80),
        "include_debug": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
        "name": _string_property(240),
        "document_type": {"type": "string", "enum": ["passport", "certificate", "manual", "ies"]},
        "lookup_direction": {"type": "string", "enum": ["by_name", "by_code"]},
        "code_system": {
            "type": "string",
            "enum": ["etm", "oracl", "sku", "article", "catalog_identifier", "mixed"],
        },
        "etm": _string_property(80),
        "oracl": _string_property(80),
        "category": _string_property(240),
        "series": _string_property(200),
        "sphere": _string_property(240),
        "mounting_type": _string_property(160),
        "beam_pattern": _string_property(160),
        "climate_execution": _string_property(160),
        "electrical_protection_class": _string_property(80),
        "explosion_protection_marking": _string_property(160),
        "supply_voltage_raw": _string_property(120),
        "dimensions_raw": _string_property(120),
        "power_factor_operator": _string_property(8),
        "ip": _string_property(12, r"^[A-Za-z0-9 .+-]+$"),
        "voltage_kind": {"type": "string", "enum": ["AC", "DC", "AC/DC"]},
        "explosion_protected": {"type": "boolean"},
        "fuzzy": {"type": "boolean"},
        "limit_categories": {"type": "integer", "minimum": 1, "maximum": 10},
        "limit_lamps": {"type": "integer", "minimum": 1, "maximum": 10},
        "limit_portfolio": {"type": "integer", "minimum": 0, "maximum": 10},
    }
    for prefix in (
        "power_w",
        "flux_lm",
        "cct_k",
        "cri_ra",
        "temp_c",
        "warranty_years",
    ):
        properties[f"{prefix}_min"] = {"type": "integer"}
        properties[f"{prefix}_max"] = {"type": "integer"}
    for prefix in (
        "weight_kg",
        "power_factor_min",
        "voltage_nominal_v",
        "voltage_min_v",
        "voltage_max_v",
        "voltage_tol_minus_pct",
        "voltage_tol_plus_pct",
        "length_mm",
        "width_mm",
        "height_mm",
    ):
        properties[f"{prefix}_min"] = {"type": "number"}
        properties[f"{prefix}_max"] = {"type": "number"}
    return properties


def default_argument_schema(
    *,
    executor: str,
    executor_args_template: dict[str, Any],
    locked_args: dict[str, Any],
    selector_visible_only: bool = False,
) -> dict[str, Any]:
    if executor == "corp_db_search":
        properties = _corp_db_argument_properties()
        required = [] if selector_visible_only else ["kind"]
    elif executor == "doc_search":
        properties = {
            "query": _string_property(500),
            "top": {"type": "integer", "minimum": 1, "maximum": 20},
            "preferred_document_ids": _string_array_property(20, 240),
        }
        required = ["query"]
    else:
        properties = {}
        required = []

    for source in (executor_args_template, locked_args):
        for key, value in source.items():
            if key not in properties:
                properties[key] = _infer_property_schema(value)

    if selector_visible_only:
        hidden_keys = set(executor_args_template).union(locked_args)
        properties = {
            key: value
            for key, value in properties.items()
            if key not in hidden_keys
        }
        required = [key for key in required if key in properties]

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _validate_compact_enum(field_path: str, values: Any) -> None:
    if not isinstance(values, list):
        raise RouteCardContractError(f"{field_path}.enum must be a list")
    if len(values) > MAX_COMPACT_ENUM_VALUES:
        raise RouteCardContractError(
            f"{field_path}.enum has {len(values)} values; use a free string/resolver field instead"
        )
    for item in values:
        if len(str(item)) > MAX_COMPACT_ENUM_VALUE_LENGTH:
            raise RouteCardContractError(f"{field_path}.enum contains an overlong value")


def _validate_property_schema(field_path: str, schema: Any) -> None:
    if not isinstance(schema, dict):
        raise RouteCardContractError(f"{field_path} must be an object")
    value_type = schema.get("type")
    if value_type not in {"string", "integer", "number", "boolean", "array", "object"}:
        raise RouteCardContractError(f"{field_path}.type is unsupported")
    if "enum" in schema:
        _validate_compact_enum(field_path, schema["enum"])
    if "pattern" in schema:
        try:
            re.compile(str(schema["pattern"]))
        except re.error as exc:
            raise RouteCardContractError(f"{field_path}.pattern is invalid: {exc}") from exc
    for numeric_key in ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        if numeric_key in schema and not isinstance(schema[numeric_key], (int, float)):
            raise RouteCardContractError(f"{field_path}.{numeric_key} must be numeric")
    if value_type == "array":
        if "items" in schema:
            _validate_property_schema(f"{field_path}.items", schema["items"])
    if value_type == "object":
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            raise RouteCardContractError(f"{field_path}.properties must be an object")
        for key, child in properties.items():
            _validate_property_schema(f"{field_path}.properties.{key}", child)


def normalize_argument_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise RouteCardContractError("argument_schema must be an object")
    normalized = dict(schema)
    if normalized.get("type", "object") != "object":
        raise RouteCardContractError("argument_schema.type must be object")
    normalized["type"] = "object"
    properties = normalized.get("properties")
    if not isinstance(properties, dict):
        raise RouteCardContractError("argument_schema.properties must be an object")
    normalized["properties"] = {str(key): dict(value) for key, value in properties.items()}
    normalized["additionalProperties"] = False
    required = normalized.get("required") or []
    if not isinstance(required, list) or any(str(item) not in normalized["properties"] for item in required):
        raise RouteCardContractError("argument_schema.required must reference declared properties")
    normalized["required"] = [str(item) for item in required]
    for key, property_schema in normalized["properties"].items():
        _validate_property_schema(f"argument_schema.properties.{key}", property_schema)
    return normalized


def _validate_value(field_path: str, value: Any, schema: dict[str, Any]) -> None:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} must be a string")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} exceeds maxLength")
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} is shorter than minLength")
        if "pattern" in schema and not re.search(str(schema["pattern"]), value):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} does not match pattern")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} must be an integer")
    elif expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} must be a number")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} must be a boolean")
    elif expected == "array":
        if not isinstance(value, list):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} must be an array")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} exceeds maxItems")
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} is shorter than minItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_value(f"{field_path}[{index}]", item, item_schema)
    elif expected == "object":
        if not isinstance(value, dict):
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} must be an object")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, item in value.items():
            if key not in properties:
                raise RouteSelectorOutputError("invalid_tool_args", f"{field_path}.{key} is undeclared")
            _validate_value(f"{field_path}.{key}", item, properties[key])
    else:
        raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} uses unsupported schema type")

    if "enum" in schema and value not in schema["enum"]:
        raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} is not one of the declared enum values")
    if expected in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise RouteSelectorOutputError("invalid_tool_args", f"{field_path} is above maximum")


def validate_tool_args(
    route: dict[str, Any],
    tool_args: dict[str, Any],
    *,
    require_required: bool,
    schema_field: str = "argument_schema",
) -> None:
    schema = normalize_argument_schema(route.get(schema_field) or {})
    properties = schema["properties"]
    for key, value in tool_args.items():
        if key not in properties:
            raise RouteSelectorOutputError("invalid_tool_args", f"tool_args.{key} is undeclared for route")
        _validate_value(f"tool_args.{key}", value, properties[key])
    if require_required:
        for key in schema.get("required", []):
            if key not in tool_args:
                raise RouteSelectorOutputError("missing_required", f"tool_args.{key} is required")


def _contains_selector_bypass(value: Any) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip()
            if normalized in PROHIBITED_SELECTOR_KEYS or normalized in EVIDENCE_BYPASS_KEYS:
                return normalized
            nested = _contains_selector_bypass(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _contains_selector_bypass(item)
            if nested:
                return nested
    return ""


def merge_route_tool_args(
    route: dict[str, Any],
    selector_tool_args: dict[str, Any] | None = None,
    *,
    validate_required: bool = True,
) -> dict[str, Any]:
    selector_args = dict(selector_tool_args or {})
    if _contains_selector_bypass(selector_args):
        raise RouteSelectorOutputError("unsafe_selector_output", "tool_args contain unsafe selector keys")

    locked_args = dict(route.get("locked_args") or {})
    for key, value in selector_args.items():
        if key in locked_args and locked_args[key] != value:
            raise RouteSelectorOutputError("unsafe_selector_output", f"tool_args.{key} attempts to override locked_args")

    validate_tool_args(route, selector_args, require_required=False, schema_field="argument_schema")
    final_args = dict(route.get("executor_args_template") or {})
    final_args.update(selector_args)
    final_args.update(locked_args)
    schema_field = "execution_argument_schema" if route.get("execution_argument_schema") else "argument_schema"
    validate_tool_args(route, final_args, require_required=validate_required, schema_field=schema_field)
    return final_args


def _default_evidence_policy(route: dict[str, Any]) -> dict[str, Any]:
    route_kind = str(route.get("route_kind") or "")
    if route_kind == "doc_domain":
        return {"mode": "document_scoped", "require_document_selector_match": True}
    if route_kind == "corp_table":
        return {"mode": "table_scoped", "require_route_scope_match": True}
    return {"mode": "route_scoped", "require_route_scope_match": True}


def _normalize_evidence_policy(route: dict[str, Any]) -> dict[str, Any]:
    policy = route.get("evidence_policy")
    if not isinstance(policy, dict) or not policy:
        policy = _default_evidence_policy(route)
    normalized = dict(policy)
    mode = str(normalized.get("mode") or "").strip().lower()
    if mode in {"", "none", "off", "disabled", "bypass"}:
        raise RouteCardContractError("evidence_policy must require scoped evidence")
    if normalized.get("required") is False:
        raise RouteCardContractError("evidence_policy.required cannot be false")
    return normalized


def _infer_locked_args(executor_args_template: dict[str, Any]) -> dict[str, Any]:
    return dict(executor_args_template)


def _infer_document_selectors(route: dict[str, Any], executor_args_template: dict[str, Any]) -> list[str]:
    selectors: list[str] = []
    for value in route.get("document_selectors") or []:
        selectors.append(str(value or "").strip())
    document_id = str(route.get("document_id") or "").strip()
    if document_id:
        selectors.append(document_id)
    preferred = executor_args_template.get("preferred_document_ids")
    if isinstance(preferred, list):
        selectors.extend(str(item or "").strip() for item in preferred)
    return _dedupe_strings(selectors)


def _infer_table_scopes(route: dict[str, Any], executor_args_template: dict[str, Any]) -> list[str]:
    scopes = [str(item or "").strip() for item in route.get("table_scopes") or []]
    for key in ("knowledge_route_id", "kind", "profile"):
        value = str(executor_args_template.get(key) or "").strip()
        if value:
            scopes.append(value)
    for source_file in executor_args_template.get("source_files") or []:
        scopes.append(str(source_file or "").strip())
    if str(route.get("route_kind") or "") in {"corp_table", "corp_script"}:
        scopes.append(str(route.get("route_family") or route.get("route_id") or "").strip())
    return _dedupe_strings(scopes)


def normalize_route_card_contract(route: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(route)
    executor = str(normalized.get("executor") or normalized.get("tool_name") or "").strip()
    if not executor:
        raise RouteCardContractError("executor is required")

    executor_args_template = normalized.get("executor_args_template")
    if not isinstance(executor_args_template, dict):
        executor_args_template = {}
    executor_args_template = dict(executor_args_template)
    explicit_locked = normalized.get("locked_args")
    locked_args = dict(explicit_locked) if isinstance(explicit_locked, dict) else _infer_locked_args(executor_args_template)

    schema = normalized.get("argument_schema")
    if not isinstance(schema, dict) or not schema:
        schema = default_argument_schema(
            executor=executor,
            executor_args_template=executor_args_template,
            locked_args=locked_args,
            selector_visible_only=True,
        )
    argument_schema = normalize_argument_schema(schema)

    execution_schema = normalized.get("execution_argument_schema")
    if not isinstance(execution_schema, dict) or not execution_schema:
        execution_schema = default_argument_schema(
            executor=executor,
            executor_args_template=executor_args_template,
            locked_args=locked_args,
            selector_visible_only=False,
        )
    execution_argument_schema = normalize_argument_schema(execution_schema)

    contract_route = dict(normalized)
    contract_route["argument_schema"] = argument_schema
    contract_route["execution_argument_schema"] = execution_argument_schema
    contract_route["locked_args"] = locked_args
    contract_route["argument_hints"] = dict(normalized.get("argument_hints") or {})
    contract_route["evidence_policy"] = _normalize_evidence_policy(contract_route)
    contract_route["fallback_route_ids"] = _dedupe_strings(normalized.get("fallback_route_ids") or [])
    contract_route["cross_family_fallback_route_ids"] = _dedupe_strings(
        normalized.get("cross_family_fallback_route_ids") or []
    )
    contract_route["fallback_policy"] = _normalize_fallback_policy(contract_route)
    contract_route["document_selectors"] = _infer_document_selectors(contract_route, executor_args_template)
    contract_route["table_scopes"] = _infer_table_scopes(contract_route, executor_args_template)
    contract_route["negative_keywords"] = _dedupe_strings(normalized.get("negative_keywords") or [])

    try:
        validate_tool_args(
            contract_route,
            executor_args_template,
            require_required=False,
            schema_field="execution_argument_schema",
        )
        validate_tool_args(
            contract_route,
            locked_args,
            require_required=False,
            schema_field="execution_argument_schema",
        )
    except RouteSelectorOutputError as exc:
        raise RouteCardContractError(exc.message) from exc
    final_args = dict(executor_args_template)
    final_args.update(locked_args)
    contract_route["tool_args"] = final_args
    return contract_route


def _visible_routes_by_id(routes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    visible: dict[str, dict[str, Any]] = {}
    for route in routes:
        if not isinstance(route, dict):
            continue
        route_id = str(route.get("route_id") or "").strip()
        if not route_id:
            continue
        if route.get("hidden") is True or route.get("selector_visible") is False:
            continue
        visible[route_id] = route
    return visible


def _route_selector_family_id(route: dict[str, Any]) -> str:
    return str(route.get("family_id") or route.get("route_family") or route.get("route_id") or "").strip()


def _normalize_fallback_policy(route: dict[str, Any]) -> dict[str, Any]:
    declared_fallback_ids = _dedupe_strings(route.get("fallback_route_ids") or [])
    raw_policy = route.get("fallback_policy") if isinstance(route.get("fallback_policy"), dict) else {}
    explicit_cross_family_ids = _dedupe_strings(
        raw_policy.get("cross_family_route_ids")
        or route.get("cross_family_fallback_route_ids")
        or []
    )
    same_family_route_ids = [route_id for route_id in declared_fallback_ids if route_id not in explicit_cross_family_ids]
    return {
        "default_scope": str(raw_policy.get("default_scope") or "family_local"),
        "family_id": _route_selector_family_id(route),
        "same_family_route_ids": same_family_route_ids,
        "cross_family_route_ids": explicit_cross_family_ids,
        "allow_cross_family": bool(explicit_cross_family_ids),
    }


def _build_repair_prompt(error: RouteSelectorOutputError) -> str:
    return (
        "Return one corrected strict JSON object with selected_family_id, selected_route_id, optional "
        "fallback_route_ids that stay inside the selected family unless the selected leaf explicitly allows "
        "cross-family fallbacks, and tool_args that contain only fields declared by "
        f"the selected route schema. Error: {error.message}"
    )


def _selector_error_result(error: RouteSelectorOutputError, *, repair_attempted: bool) -> SelectorValidationResult:
    repairable = (not repair_attempted) and error.code in {"invalid_json", "invalid_tool_args", "missing_required"}
    return SelectorValidationResult(
        valid=False,
        error_code=error.code,
        error=error.message,
        repairable=repairable,
        repair_prompt=_build_repair_prompt(error) if repairable else "",
    )


def validate_selector_output(
    selector_output: str | dict[str, Any],
    routes: list[dict[str, Any]],
    *,
    repair_attempted: bool = False,
) -> SelectorValidationResult:
    try:
        if isinstance(selector_output, str):
            try:
                parsed = json.loads(selector_output)
            except json.JSONDecodeError as exc:
                raise RouteSelectorOutputError("invalid_json", f"selector output is not valid JSON: {exc}") from exc
        else:
            parsed = selector_output
        if not isinstance(parsed, dict):
            raise RouteSelectorOutputError("invalid_json", "selector output must be a JSON object")

        root_unsafe_key = next((key for key in parsed if key not in SAFE_SELECTOR_KEYS), "")
        if root_unsafe_key:
            raise RouteSelectorOutputError("unsafe_selector_output", f"selector key {root_unsafe_key} is not allowed")
        bypass_key = _contains_selector_bypass(parsed)
        if bypass_key:
            raise RouteSelectorOutputError("unsafe_selector_output", f"selector output contains unsafe key {bypass_key}")

        routes_by_id = _visible_routes_by_id(routes)
        selected_route_id = str(parsed.get("selected_route_id") or "").strip()
        if not selected_route_id:
            raise RouteSelectorOutputError("missing_required", "selected_route_id is required")
        route = routes_by_id.get(selected_route_id)
        if route is None:
            raise RouteSelectorOutputError("unsafe_selector_output", f"selected route {selected_route_id} is not visible")

        selected_family_id = str(parsed.get("selected_family_id") or "").strip()
        route_family_id = _route_selector_family_id(route)
        if selected_family_id and selected_family_id != route_family_id:
            raise RouteSelectorOutputError(
                "unsafe_selector_output",
                f"selected family {selected_family_id} does not match route {selected_route_id} family {route_family_id}",
            )
        if not selected_family_id:
            selected_family_id = route_family_id

        selector_tool_args = parsed.get("tool_args") or {}
        if not isinstance(selector_tool_args, dict):
            raise RouteSelectorOutputError("invalid_tool_args", "tool_args must be an object")
        final_args = merge_route_tool_args(route, selector_tool_args, validate_required=True)

        route_fallback_ids = set(_dedupe_strings(route.get("fallback_route_ids") or []))
        fallback_policy = route.get("fallback_policy") if isinstance(route.get("fallback_policy"), dict) else {}
        cross_family_fallback_ids = set(
            _dedupe_strings(
                fallback_policy.get("cross_family_route_ids")
                or route.get("cross_family_fallback_route_ids")
                or []
            )
        )
        same_family_fallback_ids = set(
            _dedupe_strings(
                fallback_policy.get("same_family_route_ids")
                or [route_id for route_id in route_fallback_ids if route_id not in cross_family_fallback_ids]
            )
        )
        declared_fallback_ids = same_family_fallback_ids | cross_family_fallback_ids
        fallback_route_ids = _dedupe_strings(parsed.get("fallback_route_ids") or [])
        for fallback_id in fallback_route_ids:
            fallback_route = routes_by_id.get(fallback_id)
            if fallback_route is None:
                raise RouteSelectorOutputError("unsafe_selector_output", f"fallback route {fallback_id} is not visible")
            if fallback_id not in declared_fallback_ids:
                raise RouteSelectorOutputError(
                    "unsafe_selector_output",
                    f"fallback route {fallback_id} is not declared by selected route",
                )
            fallback_family_id = _route_selector_family_id(fallback_route)
            if fallback_id in same_family_fallback_ids and fallback_family_id != route_family_id:
                raise RouteSelectorOutputError(
                    "unsafe_selector_output",
                    f"fallback route {fallback_id} leaves family {route_family_id} without explicit cross-family declaration",
                )

        return SelectorValidationResult(
            valid=True,
            selected_family_id=selected_family_id,
            selected_route_id=selected_route_id,
            route=dict(route),
            tool_args=final_args,
            fallback_route_ids=fallback_route_ids,
        )
    except RouteSelectorOutputError as exc:
        return _selector_error_result(exc, repair_attempted=repair_attempted)
