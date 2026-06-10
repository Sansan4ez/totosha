Retrieval Routing Architecture
==============================

Status
------

Living architecture note for the current retrieval-routing implementation.
This document records the post-RFC-025 ownership model. See
[`RFC-025`](../rfc/RFC-025-route-card-centered-retrieval-refactor.md) for the
design intent behind route-card-centered retrieval and LLM-selected route
arguments.

Routing Ownership
-----------------

Retrieval routing is intentionally split across source catalogs, runtime
catalog loading, selector validation, orchestration, and executor APIs.

| Area | Owner | Responsibility |
| ---- | ----- | -------------- |
| Runtime orchestration and guardrails | `core/agent.py` | Builds or receives route selection, calls the selector LLM when enabled, executes selected tools, classifies evidence, applies bounded fallbacks, blocks unsafe or duplicate retrieval attempts, records routing telemetry. |
| Catalog loading and formatting | `core/documents/routing.py` | Loads repo/runtime route manifests, builds bootstrap and live-document route cards, normalizes route cards, merges source-owned catalogs, validates catalog health, builds compact selector payloads, and orders degraded candidate lists when the catalog is too large. |
| Selector argument contract | `core/documents/route_schema.py` | Defines the route-card contract, validates route-card schemas, validates selector JSON, rejects unsafe selector keys, merges template args, selector args, and locked args, and enforces compact enum limits. |
| Search-document materialization | `db/search_docs.py` | Materializes rows into `corp.corp_search_docs` and route metadata such as `knowledge_route_id`, `retrieval_route_family`, aliases, entity types, and facets. It is not a runtime router. |
| Versioned route/source manifests | `doc-corpus/manifests/routes/` | Repo-tracked manifests and generated route catalogs used as source inputs for runtime catalog loading and publication. |
| Runtime document state | `workspace/_shared/corp_docs` mounted as `/data/corp_docs` | Deployment-local generated state: live document records, parse cache, generated document manifests, sync reports, and active runtime route catalogs. |
| Corp DB executors | `tools-api/src/routes/corp_db.py` | Executes the selected `corp_db_search` mode. It interprets `kind`, `profile`, route scope, filters, and limits, but it does not choose the retrieval route. |

`core/agent.py` is the boundary that owns request lifecycle, observability,
guardrails, and evidence acceptance. It should not duplicate catalog knowledge
that belongs in route cards. `core/documents/routing.py` owns the catalog view
that the selector sees. `core/documents/route_schema.py` owns the safety
contract for LLM-produced route arguments.

Route Catalog Lifecycle
-----------------------

1. Source data is loaded into corp DB tables and corp search docs. `db/search_docs.py`
   materializes searchable documents from normalized tables and KB files.
2. Operator-provided documents live in `doc-corpus/inbox/` with optional sidecar
   metadata. Document ingestion publishes live records and document route
   metadata into `/data/corp_docs`.
3. Route specs come from repo manifests, corp DB route definitions, document
   ingestion metadata, and bootstrap routes used as a local/development safety
   net.
4. `core/documents/routing.py` merges these inputs into one active catalog,
   normalizes each route card, validates route ownership and scope, and exposes
   compact cards to the selector.
5. `core/agent.py` calls the selector LLM with the compact route catalog when
   route selection is enabled. The selector returns strict JSON containing a
   visible `selected_route_id`, route-specific `tool_args`, and optional bounded
   `fallback_route_ids`.
6. `core/documents/route_schema.py` validates the selector output. Argument
   merge order is: `executor_args_template`, validated selector `tool_args`,
   then `locked_args` applied last.
7. The selected executor runs. Evidence is accepted only if it matches the
   selected route scope. A non-empty payload from the wrong route is weak
   evidence, not sufficient evidence.

When `ROUTING_CATALOG_REQUIRED=true`, runtime catalog loading should fail closed
if no valid active merged catalog exists. In non-production/local modes,
repo manifests, legacy runtime catalogs, and bootstrap cards may be used as
fallback inputs so local development remains possible.

Catalog Roles
-------------

Use these terms consistently:

- Source catalog: reviewed inputs such as `doc-corpus/manifests/routes/*.json`,
  repo-static route specs, corp DB route definitions, and document metadata.
- Generated catalog: a merged or regenerated artifact with `schema_version`,
  `catalog_version`, `generated_at`, source digests, route counts, and validation
  results. Generated catalogs may be produced by document ingestion, route
  rebuilds, or `build_routing_index()`.
- Runtime catalog: the active catalog loaded from
  `/data/corp_docs/manifests/routes/catalog.v1.json`, then revalidated by
  current core code before use. This is the catalog the selector request path
  should consume.

Bootstrap routes are not the source of truth for production. They are a local
fallback and a compatibility bridge while generated/source-owned catalogs catch
up with deployed code.

Selector Payload And Degraded Ordering
--------------------------------------

`build_route_selector_payload()` sends compact route cards to the selector. If
the visible catalog has at most `SELECTOR_ROUTE_LIMIT` routes, the payload uses
`candidate_mode=all_visible` and includes every visible route.

If the catalog grows beyond that limit, `core/documents/routing.py` performs a
simple degraded ordering pass to produce a bounded candidate list. That ordering
uses intent hints, exact route or document id matches, and catalog/card metadata
only to decide which cards are shown to the LLM. It is not the final route
decision and must not become a parallel production router.

Why `workspace/_shared/corp_docs` Duplicates `doc-corpus`
--------------------------------------------------------

`doc-corpus/` is the git-tracked source and operator input area. It contains
raw inbox files and versioned/source manifests.

`workspace/_shared/corp_docs` is generated runtime state. Docker mounts
`workspace/_shared` as `/data`, so the document worker and core see
`/data/corp_docs` through `CORP_DOCS_ROOT`. This tree stores mutable deployment
artifacts that should not be edited by hand: parse caches, live document records,
published document manifests, sync reports, and active runtime route catalogs.

The duplication exists because source and runtime state have different owners:

- repo state is reviewed and versioned in git;
- runtime state is produced by ingestion workers and mounted into containers;
- core needs a stable `/data/corp_docs` path at request time;
- generated catalogs may include live deployment data that is not present in
  the repo source tree.

Treat `/data/corp_docs` as derived state. If it disagrees with `doc-corpus/`,
rerun the document publication workflow instead of manually patching runtime
files.

`doc_search` Semantics
----------------------

`doc_search` is not a generic "search all documents" fallback. Under RFC-025 it
means "search inside one or more indexed documents owned by a concrete
`doc_domain` route."

Use `doc_search` when the selected route is a document-domain route with
concrete `document_selectors` or `preferred_document_ids`, or when the user gives
explicit document context such as asking for a quote, fragment, file, PDF, or
named document.

Do not route generic company facts, certification, product components, quality,
or warranty questions to `doc_search` unless a document-domain route explicitly
owns that topic. Those belong to source-scoped corp DB/KB routes such as
`corp_kb.company_common` until a concrete document route says otherwise.

Current Corp DB Executor Modes
------------------------------

`tools-api` currently exposes `corp_db_search` modes for:

- `hybrid_search`
- `lamp_exact`
- `lamp_suggest`
- `sku_by_code`
- `application_recommendation`
- `category_lamps`
- `portfolio_by_sphere`
- `portfolio_examples_by_lamp`
- `sphere_categories`
- `category_mountings`
- `lamp_filters`

The route selector chooses route cards; these modes only execute selected
arguments. Route cards should lock stable executor arguments such as `kind`,
`profile`, `knowledge_route_id`, `source_files`, or `entity_types` whenever the
selector must not override them.

Current Table Coverage
----------------------

| Data area | Current routing status |
| --------- | ---------------------- |
| `corp.categories` | Covered by structured routes such as `corp_db.category_lamps`, `corp_db.sphere_categories`, `corp_db.application_recommendation`, and `corp_db.lamp_filters`. Category rows are also materialized into `corp.corp_search_docs` as `entity_type=category`. |
| `corp.etm_oracl_catalog_sku` | Covered by `corp_db.sku_lookup` / `sku_by_code` and by entity-resolution search over `entity_type=sku`. ETM/ORACL/SKU values are extracted as free strings; large SKU domains must not be enumerated into selector prompts. |
| `corp.mounting_types` and `corp.category_mountings` | Covered by `corp_db.category_mountings`, `corp_db.lamp_mounting_compatibility`, and mounting-related `lamp_filters`. Rows are materialized into search docs as `entity_type=mounting_type` and `entity_type=category_mounting`. |

The checked-in and runtime route manifests can lag behind code changes until
`doc-worker rebuild-routes` or the equivalent route publication step is run.
When adding or changing a route, verify both code-level bootstrap/default route
coverage and the active `/data/corp_docs/manifests/routes/catalog.v1.json`
published catalog.

Adding Tables, Documents, Or Routes
-----------------------------------

For a new corp DB table or table-backed capability:

1. Add or update the loader and schema in `db/`.
2. Add search-doc materialization in `db/search_docs.py` only if the table should
   participate in hybrid/entity search.
3. Add or update a `tools-api` executor mode in `tools-api/src/routes/corp_db.py`.
4. Extend selector argument properties in `core/documents/route_schema.py` if
   the route needs new validated arguments.
5. Publish a route card with `route_kind`, `executor`, `executor_args_template`,
   `locked_args`, `argument_schema`, `evidence_policy`, and `table_scopes`.
6. Add focused tests for route catalog validation, selector argument validation,
   and executor behavior.

For a new document domain:

1. Put the source file under `doc-corpus/inbox/`.
2. Add sidecar metadata when the document needs a stable thematic route,
   aliases, topics, keywords, or multiple route cards.
3. Run the document sync and route rebuild workflow so runtime state is
   published under `/data/corp_docs`.
4. Ensure each document route has concrete `document_selectors`; do not add a
   generic catch-all `doc_search` route.

For a new route card:

1. Choose a unique `route_id` and explicit owner.
2. Set `route_kind` to `corp_table`, `corp_script`, or `doc_domain`.
3. Keep route-specific knowledge in the route card, not in `core/agent.py`.
4. Lock executor arguments that define authority or scope.
5. Declare bounded fallback routes instead of relying on generic fallbacks.
6. Verify that selector output cannot introduce tools, SQL, paths, shell
   commands, or evidence-policy bypasses through `tool_args`.
