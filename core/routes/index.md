Route catalog index
====================

This directory is the RFC-028 declarative source of truth for the bootstrap route catalog
(`documents/routing.py::bootstrap_route_cards`). Each business family from `families.yaml` has
its own subdirectory; each file inside is one leaf route card.

```text
routes/
  index.md          # this file
  families.yaml      # family_id -> {title, summary}
  <family_id>/
    <leaf>.yaml         # one route card: prose (title, summary, when_to_use), keywords/patterns
                        # (humans + degraded fallback only), executor, args, fallbacks, schema_ref
    <leaf>.schema.json  # RFC-029: the route's selector-visible argument schema (machine contract)
```

Loading and validation
-----------------------

- `documents.routing.load_static_route_cards()` reads every `<family>/<leaf>.yaml` file plus its
  sibling `.schema.json` (via `schema_ref`, defaulting to `<leaf>.schema.json`) and returns the
  raw route dicts. A YAML card must not embed an `argument_schema` key — the JSON file is the
  executed contract (RFC-029 workstream 4); regenerate it with
  `scripts/generate_route_argument_schemas.py` after changing an executor template or the
  canonical enum sources.
- `_normalize_route_card` layers in family/stage metadata from `ROUTE_BUSINESS_METADATA`, and
  `_apply_runtime_argument_overrides` refreshes the live enum values (spheres, mounting types,
  series, sphere-scoped categories) on top of the file-declared schema. Those cross-cutting
  tables stayed in code deliberately — they are policy overlays applied to *any* route, not
  per-route data.
- RFC-029 selector visibility: only `route_id`, `family_id`, `title`, and the human-authored
  `when_to_use` reach the route-selection LLM call (Call A). `keywords`/`patterns` never
  serialize into any selector payload — they remain here for humans, tests, and the degraded
  (LLM-unavailable) ordering. The selected route's `.schema.json` plus `argument_hints` are the
  only contract the argument-builder call (Call B) sees.
- `python -m documents.route_catalog_check` (see `documents/route_catalog_check.py`) enforces:
  referential integrity of `fallback_route_ids`, cross-family fallback declarations, executor
  names resolving to a registered tool, `additionalProperties: false` on every argument schema,
  presence and validity of every `.schema.json` file, a `when_to_use` on every card, and
  RFC-028's sibling-fallback-coverage rule (see below). Run it before merging any change
  under `routes/`.

Sibling-fallback-coverage rule
-------------------------------

Two routes in the same family that execute against the identical corp_kb scope (same
`knowledge_route_id` + `source_files`) are close substitutes for the LLM selector. The catalog
check requires them to declare each other in `fallback_route_ids`, unless the route explicitly
opts out:

```yaml
fallback_policy:
  no_sibling_fallback: true
  no_sibling_fallback_reason: "why the broader/narrower sibling wouldn't add evidence here"
```

This exists because of a production incident (2026-07-06, trace
`7852fc7fe6909eec06529a124817e571`): `corp_kb.company_common` and `corp_kb.series_description`
shared a KB scope but neither declared the other as a fallback. The selector correctly proposed
the fallback anyway; the runtime rejected the whole response and the user saw a bounded
"service unavailable" answer. See `docs/rfc/RFC-028-declarative-route-catalog-and-sanitizing-selector-contract.md`.

Adding a route
--------------

1. Pick (or create) the business family directory under `routes/`.
2. Add `<leaf>.yaml` with `route_id`, `route_family`, `route_kind`, `authority`, `title`,
   `summary`, `when_to_use`, `schema_ref`, `topics`, `keywords`, `patterns`, `executor`,
   `executor_args_template`, and (if applicable) `argument_hints` / `fallback_route_ids` /
   `cross_family_fallback_route_ids`.
3. Add the route's family/stage/leaf mapping to `ROUTE_BUSINESS_METADATA` in `routing.py` if the
   family doesn't already cover it, plus any argument allowlist entry in
   `ROUTE_ARGUMENT_PROPERTY_ALLOWLISTS` / `ROUTE_REQUIRED_ARGUMENTS`.
4. Generate the argument schema file: `scripts/generate_route_argument_schemas.py`.
5. Run `python -m documents.route_catalog_check` and the `tests/test_routing_catalog.py` /
   `tests/test_route_catalog_check.py` / `tests/test_route_schema_files.py` suites.
