"""RFC-028 CI check for the declarative route catalog (core/routes/).

Run as: python -m documents.route_catalog_check

Fails (exit 1) when the bootstrap route catalog violates any of:

1. Existing referential-integrity / cross-family fallback rules, already enforced at catalog
   merge time by routing.py::_validate_route_fallback_policies (surfaced here so a broken
   route card fails CI instead of only degrading a running deploy's validation_report).
2. Executor names resolve to a tool actually registered in tools.TOOL_EXECUTORS.
3. Every route's argument_schema and execution_argument_schema forbid additional properties.
4. RFC-028 sibling-fallback coverage: two routes in the same business family that execute
   against the identical corp_kb scope (same knowledge_route_id + source_files) are close
   substitutes for the selector and must declare each other in fallback_route_ids, unless the
   route opts out via fallback_policy.no_sibling_fallback with a no_sibling_fallback_reason.
   This is the invariant the 2026-07-06 production incident (trace
   7852fc7fe6909eec06529a124817e571) fell through: corp_kb.company_common and
   corp_kb.series_description shared a KB scope but neither declared the other as a fallback.
"""
from __future__ import annotations

import json
import sys
from typing import Any

import yaml

from documents.route_schema import RouteCardContractError, normalize_argument_schema
from documents.routing import _bootstrap_catalog_payload, _route_schema_file_path, static_route_catalog_dir

try:
    # Deferred/best-effort: some test runs replace sys.modules["tools"] with a partial stub
    # for unrelated sandbox/bash tests (test_bash_public_mode.py), which would otherwise break
    # collection of this module. When TOOL_EXECUTORS isn't available, check_executor_resolution
    # simply skips (the other checks still run); `python -m documents.route_catalog_check` in a
    # clean process always has the real tools package.
    from tools import TOOL_EXECUTORS
except Exception:
    TOOL_EXECUTORS = None


def _kb_scope_key(route: dict[str, Any]) -> tuple[str, tuple[str, ...]] | None:
    template = route.get("executor_args_template")
    if not isinstance(template, dict):
        return None
    knowledge_route_id = str(template.get("knowledge_route_id") or "").strip()
    source_files = template.get("source_files")
    if not knowledge_route_id or not isinstance(source_files, list) or not source_files:
        return None
    return (knowledge_route_id, tuple(sorted(str(item) for item in source_files)))


def check_executor_resolution(
    routes: list[dict[str, Any]],
    *,
    known_executors: dict[str, Any] | None = None,
) -> list[str]:
    executors = known_executors if known_executors is not None else TOOL_EXECUTORS
    if executors is None:
        return []
    errors = []
    for route in routes:
        executor = str(route.get("executor") or "").strip()
        if executor not in executors:
            errors.append(f"{route.get('route_id')}: executor '{executor}' is not registered in tools.TOOL_EXECUTORS")
    return errors


def check_schema_closed(routes: list[dict[str, Any]]) -> list[str]:
    errors = []
    for route in routes:
        route_id = str(route.get("route_id") or "")
        for schema_field in ("argument_schema", "execution_argument_schema"):
            schema = route.get(schema_field)
            if not isinstance(schema, dict):
                errors.append(f"{route_id}: missing {schema_field}")
                continue
            if schema.get("additionalProperties") is not False:
                errors.append(f"{route_id}: {schema_field}.additionalProperties must be false")
    return errors


def check_sibling_fallback_coverage(routes: list[dict[str, Any]]) -> list[str]:
    errors = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    for route in routes:
        family_id = str(route.get("family_id") or "")
        by_family.setdefault(family_id, []).append(route)

    for family_routes in by_family.values():
        for i, route_a in enumerate(family_routes):
            scope_a = _kb_scope_key(route_a)
            if scope_a is None:
                continue
            for route_b in family_routes[i + 1 :]:
                scope_b = _kb_scope_key(route_b)
                if scope_a != scope_b:
                    continue
                a_id = str(route_a.get("route_id") or "")
                b_id = str(route_b.get("route_id") or "")
                a_policy = route_a.get("fallback_policy") if isinstance(route_a.get("fallback_policy"), dict) else {}
                b_policy = route_b.get("fallback_policy") if isinstance(route_b.get("fallback_policy"), dict) else {}
                a_declares_b = b_id in (route_a.get("fallback_route_ids") or [])
                b_declares_a = a_id in (route_b.get("fallback_route_ids") or [])
                a_opts_out = bool(a_policy.get("no_sibling_fallback")) and bool(a_policy.get("no_sibling_fallback_reason"))
                b_opts_out = bool(b_policy.get("no_sibling_fallback")) and bool(b_policy.get("no_sibling_fallback_reason"))
                if not a_declares_b and not a_opts_out:
                    errors.append(
                        f"{a_id}: shares a KB scope with sibling {b_id} ({scope_a[0]}) but does not "
                        "declare it in fallback_route_ids, and has no fallback_policy.no_sibling_fallback_reason"
                    )
                if not b_declares_a and not b_opts_out:
                    errors.append(
                        f"{b_id}: shares a KB scope with sibling {a_id} ({scope_a[0]}) but does not "
                        "declare it in fallback_route_ids, and has no fallback_policy.no_sibling_fallback_reason"
                    )
    return errors


def check_schema_files() -> list[str]:
    """RFC-029 workstream 4: every route card has a standalone, valid .schema.json and no
    argument_schema key inline in YAML."""
    errors: list[str] = []
    for card_path in sorted(static_route_catalog_dir().glob("*/*.yaml")):
        try:
            payload = yaml.safe_load(card_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{card_path.name}: invalid YAML: {exc}")
            continue
        if not isinstance(payload, dict) or not payload.get("route_id"):
            continue
        route_id = str(payload.get("route_id"))
        if "argument_schema" in payload:
            errors.append(f"{route_id}: argument_schema must live in a .schema.json file, not in the YAML card")
        schema_path = _route_schema_file_path(card_path, payload)
        if not schema_path.is_file():
            errors.append(f"{route_id}: missing argument schema file {schema_path.name}")
            continue
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{route_id}: {schema_path.name} is not valid JSON: {exc}")
            continue
        try:
            normalized = normalize_argument_schema(schema)
        except RouteCardContractError as exc:
            errors.append(f"{route_id}: {schema_path.name}: {exc}")
            continue
        if schema.get("additionalProperties") is not False:
            errors.append(f"{route_id}: {schema_path.name}: additionalProperties must be false")
        if not str(payload.get("when_to_use") or "").strip():
            errors.append(f"{route_id}: route card must declare when_to_use (RFC-029 workstream 1)")
        del normalized
    return errors


def run_checks() -> list[str]:
    payload = _bootstrap_catalog_payload()
    routes = payload.get("routes") or []
    errors: list[str] = list(payload.get("validation_report", {}).get("errors") or [])
    errors.extend(check_executor_resolution(routes))
    errors.extend(check_schema_closed(routes))
    errors.extend(check_sibling_fallback_coverage(routes))
    errors.extend(check_schema_files())
    return errors


def main() -> int:
    errors = run_checks()
    if errors:
        print(f"route catalog check FAILED with {len(errors)} error(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("route catalog check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
