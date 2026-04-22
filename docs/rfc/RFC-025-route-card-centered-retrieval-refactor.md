RFC-025 LLM-Selected Route Cards And Retrieval Arguments
========================================================

Status
------

Implemented

Date
----

2026-04-20

Last updated
------------

2026-04-22

Related RFCs
------------

- RFC-014 introduced the company-fact fast path and KB ranking hardening.
- RFC-016 defined authoritative route completion and LLM finalization boundaries.
- RFC-018 introduced the unified routing catalog for tables, scripts, and documents.
- RFC-019 fixed `doc_search` as a first-class document domain, not a generic fallback.
- RFC-021 proposed simplifying runtime orchestration and reducing hard-coded Python routing.

Context and motivation
----------------------

Two production traces exposed the same routing failure mode:

- `Какие используются комплектующие?` did not get an authoritative company KB route, then fell through to `doc_search` and answered that data was unavailable.
- `какие есть сертификаты?` was classified as `document_lookup`, selected the sports lighting document route, treated a non-empty but irrelevant `doc_search` payload as sufficient, and answered that certificates were not found.

In both cases the corporate DB already had the right content when called with the correct route:

- `knowledge_route_id=corp_kb.company_common`, `topic_facets=["quality"]` finds the component quality chunk.
- `knowledge_route_id=corp_kb.company_common`, `topic_facets=["certification"]` finds the certification chunk.

The direct bug is small, but the underlying defect is architectural. Retrieval routing is duplicated across:

- `core/agent.py`
- `core/documents/routing.py`
- `db/search_docs.py`
- `tools-api/src/routes/corp_db.py`
- `doc-corpus/manifests/routes/`
- runtime manifests under `/data/corp_docs`
- shared skills and `skills_cache.json`

This makes route behavior hard to reason about and easy to regress.

Problem statement
-----------------

The current runtime does not have one authoritative place where a retrieval decision is represented.

Instead, the system combines:

- route cards;
- hard-coded intent keywords;
- separate topic facet logic;
- separate query rewrite logic;
- separate evidence sufficiency logic;
- prompt instructions;
- skill descriptions.

That creates several classes of failure:

- a word like `сертификат` can force `doc_search` even when the user asks a generic company question;
- `doc_search` can be treated as a generic document/certificate search instead of a search inside a specific indexed document domain;
- any non-empty `doc_search` result can close retrieval even if it came from the wrong document;
- facets already materialized in DB rows are not used consistently by the router;
- stale or duplicate skills can reintroduce old retrieval paths after cache rebuild.

Goals
-----

- Make route cards the single source of truth for retrieval routing and execution hints.
- Keep `doc_search` scoped to concrete document-domain routes.
- Route generic company facts, including certification and quality questions, to `corp_db_search`.
- Move query rewrite, argument extraction, topic facets, and evidence policy out of ad hoc agent branches and into route metadata.
- Use one small LLM call to select the route and produce route-specific tool arguments.
- Validate LLM-produced arguments against route-card schemas before executing tools.
- Support many routes per table/document and one route spanning multiple tables.
- Make route selection and evidence acceptance explainable from one request trace.
- Reduce unnecessary LLM iterations by closing retrieval only on scoped, relevant evidence.
- Remove the unused `corp-wiki-md-search` runtime skill path.

Non-goals
---------

- Replacing the LLM with a fully deterministic router.
- Introducing a new ML-trained router.
- Keeping the current hand-weighted scoring algorithm as the primary production router.
- Moving every document into Postgres in v1.
- Removing `doc_search`.
- Removing benchmark-specific deterministic checks.
- Rewriting all corporate DB search modes in one change.

Decision
--------

Production retrieval should be route-card-centered and LLM-selected.

A route card represents an authoritative execution path, not only an intent label. A small dedicated LLM call receives the user query and a compact route catalog, then returns the best route plus route-specific tool arguments as strict JSON.

The route card catalog becomes the only place that defines:

- which user wording belongs to a retrieval domain;
- which tool executes the search;
- which DB route, source file, table set, document id, topic facet, or argument schema scopes the search;
- what counts as sufficient evidence;
- which fallback routes are allowed.

Runtime code should interpret and validate route-card decisions, not recreate route-specific knowledge in parallel.

The previous score-based selector is removed from production routing. Route selector payload construction must not compute a hand-weighted score, must not expose score fields to the prompt, and must not use score fallback after selector failures.

The current v1 implementation keeps only a small deterministic ordering path for non-production/degraded configurations and tests. Production with the LLM selector enabled fails closed with a temporary-unavailable response when selector or finalizer LLM access is unavailable.

Route model
-----------

The existing route card model remains the right foundation, but v1 needs a stricter contract.

Required fields:

- `route_id`
- `route_family`
- `route_kind=corp_table|corp_script|doc_domain`
- `authority=primary|secondary`
- `title`
- `summary`
- `topics`
- `keywords`
- `patterns`
- `executor`
- `executor_args_template`
- `observability_labels`

New recommended fields:

- `argument_schema`: JSON-Schema-like allowed argument contract for this route.
- `locked_args`: arguments from the route card that the LLM cannot override.
- `argument_hints`: short natural-language guidance for extracting route arguments.
- `evidence_policy`: scoped rules for accepting a result as sufficient.
- `fallback_route_ids`: bounded fallback list.
- `negative_keywords`: terms that tell the selector or simple prefilter that this route is probably not suitable.
- `document_selectors`: stable document ids plus aliases for `doc_domain` routes.
- `table_scopes`: logical table/entity scopes for `corp_table` and `corp_script` routes.

`executor_args_template` remains useful, but it should be treated as defaults plus locked scope. The LLM fills only fields allowed by `argument_schema`.

Example for company certification:

```json
{
  "route_id": "corp_kb.company_common.certification",
  "route_family": "corp_kb.company_common",
  "route_kind": "corp_table",
  "authority": "primary",
  "title": "Company certification",
  "summary": "Company certificates, declarations, CE/EAC mentions, and certification links.",
  "topics": ["company", "certification"],
  "keywords": ["сертификат", "сертификация", "декларация", "ce", "eac"],
  "patterns": ["какие есть сертификаты", "сертификаты компании"],
  "executor": "corp_db_search",
  "executor_args_template": {
    "kind": "hybrid_search",
    "profile": "kb_route_lookup",
    "knowledge_route_id": "corp_kb.company_common",
    "source_files": ["common_information_about_company.md"],
    "topic_facets": ["certification"]
  },
  "locked_args": {
    "kind": "hybrid_search",
    "profile": "kb_route_lookup",
    "knowledge_route_id": "corp_kb.company_common",
    "source_files": ["common_information_about_company.md"],
    "topic_facets": ["certification"]
  },
  "argument_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "query": {
        "type": "string",
        "maxLength": 240,
        "description": "Search query rewritten for certification evidence."
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 10,
        "default": 5
      }
    },
    "required": ["query"]
  },
  "argument_hints": "For generic certificate questions, search for certification, CE, EAC, fire certificates, and declarations of conformity.",
  "evidence_policy": {
    "required_knowledge_route_id": "corp_kb.company_common",
    "required_topic_facets_any": ["certification"],
    "min_result_count": 1
  }
}
```

Argument schema policy
----------------------

Argument extraction is an LLM task. It should not be rebuilt as another complex deterministic rules engine.

Each route card should expose the arguments that are meaningful for that route:

- closed sets as `enum`;
- bounded numeric fields with `minimum` and `maximum`;
- strings with descriptions, `maxLength`, and optional regex `pattern`;
- booleans for explicit binary filters;
- arrays with bounded `maxItems`;
- defaults where safe;
- locked arguments that cannot be changed by the LLM.

Examples:

- `topic_facets` can usually be an enum or locked list because facet values are known.
- `voltage_kind` can be enum: `AC`, `DC`, `AC/DC`.
- `explosion_protected` can be boolean.
- power, flux, CCT, CRI, voltage, weight, and dimensions can use numeric or short string fields with bounds.
- `etm`, `oracl`, `sku`, and exact model names should usually be free strings with validation constraints, not giant enums.

Small bounded lists are acceptable in the selector prompt. As a practical v1 rule, route cards may expose enum-like lists up to roughly 50-60 values when the values are short and directly useful for argument selection. This is enough for most route facets, modes, document domains, mounting classes, voltage kinds, and other compact business taxonomies.

Do not enumerate large domains only because they are technically finite. For example, a SKU list with 700+ values should not be injected into every routing prompt. The route card should instead describe the field and let the LLM extract the likely value from the user query.

Large value sets may be handled later with a separate resolver route or a compact candidate prefetch, but they should not make the route selector prompt large.

LLM route and argument selection
--------------------------------

The production selector is one compact LLM call.

Input:

- user query;
- compact route cards;
- for each route: route id, title, summary, topics, keywords, executor, locked args, argument schema, and short argument hints;
- optional shortlist if the route catalog becomes too large.

Output must be strict JSON:

```json
{
  "selected_route_id": "corp_kb.company_common.certification",
  "confidence": "high",
  "reason": "The user asks about company certificates, not about searching inside a specific document.",
  "tool_args": {
    "query": "сертификация продукции CE EAC пожарные сертификаты декларации соответствия ЛАДзавод",
    "limit": 5
  },
  "fallback_route_ids": []
}
```

Runtime validation:

- `selected_route_id` must exist in the active catalog.
- `tool_args` may contain only fields allowed by the selected route's `argument_schema`.
- field values must satisfy type, enum, bounds, pattern, and length constraints.
- `locked_args` always override conflicting LLM output.
- final tool args are `locked_args + executor_args_template defaults + validated LLM args`.
- invalid JSON or invalid args may get one repair attempt with the validation error.
- after one failed repair, runtime may use safe route-card defaults only when every required argument has a route-card default; otherwise it returns a routing error or temporary-unavailable response.
- invalid selector output must not trigger a separate score-based routing fallback.

This keeps the route and argument choice intelligent while keeping execution safe and predictable.

Selector security contract
--------------------------

The selector LLM receives untrusted user text. The runtime must treat selector output as a proposal, not as executable authority.

Hard rules:

- user text cannot create routes;
- user text cannot select tools outside the active route catalog;
- user text cannot override `locked_args`;
- user text cannot add raw filesystem paths, shell commands, SQL, URLs, or tool names unless the selected route schema explicitly permits that field;
- user text cannot instruct the selector to ignore the schema, choose hidden routes, expose prompts, or bypass evidence policy;
- selector output must be parsed as strict JSON and validated before any tool call;
- invalid or unsafe selector output is rejected or repaired once with a validation error.

This is the boundary that allows the LLM to do intelligent routing and argument extraction without turning retrieval into free-form tool execution.

Route type examples
-------------------

The catalog should include small examples or generated cards for every major data shape. These examples are not exhaustive; they show the intended modeling style.

### SKU lookup

```json
{
  "route_id": "corp_db.sku_lookup",
  "route_family": "corp_db.catalog",
  "route_kind": "corp_table",
  "title": "ETM and ORACL SKU lookup",
  "summary": "Lookup catalog SKU rows by ETM or ORACL code.",
  "executor": "corp_db_search",
  "locked_args": {"kind": "sku_by_code"},
  "argument_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "etm": {"type": "string", "maxLength": 40},
      "oracl": {"type": "string", "maxLength": 40}
    },
    "oneOf": [{"required": ["etm"]}, {"required": ["oracl"]}]
  },
  "argument_hints": "Extract exactly one ETM or ORACL code from the user query."
}
```

### Lamp filters

```json
{
  "route_id": "corp_db.lamp_filters",
  "route_family": "corp_db.catalog",
  "route_kind": "corp_table",
  "title": "Lamp parameter filter",
  "summary": "Filter lamps by compact structured parameters such as IP, power, CCT, voltage, CRI, mounting, and explosion protection.",
  "executor": "corp_db_search",
  "locked_args": {"kind": "lamp_filters"},
  "argument_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "ip": {"type": "string", "maxLength": 8},
      "power_w_min": {"type": "integer", "minimum": 1, "maximum": 2000},
      "power_w_max": {"type": "integer", "minimum": 1, "maximum": 2000},
      "cct_k_min": {"type": "integer", "minimum": 1800, "maximum": 10000},
      "cct_k_max": {"type": "integer", "minimum": 1800, "maximum": 10000},
      "voltage_kind": {"type": "string", "enum": ["AC", "DC", "AC/DC"]},
      "explosion_protected": {"type": "boolean"},
      "mounting_type": {"type": "string", "maxLength": 80}
    }
  }
}
```

### Portfolio by sphere

```json
{
  "route_id": "corp_db.portfolio_by_sphere",
  "route_family": "corp_db.portfolio",
  "route_kind": "corp_script",
  "title": "Portfolio examples by application sphere",
  "summary": "Find completed projects and implementation references by application area.",
  "executor": "corp_db_search",
  "locked_args": {"kind": "portfolio_by_sphere", "fuzzy": true},
  "argument_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "sphere": {"type": "string", "maxLength": 120},
      "query": {"type": "string", "maxLength": 240}
    },
    "required": ["query"]
  }
}
```

### Portfolio object lookup

```json
{
  "route_id": "corp_db.portfolio_lookup",
  "route_family": "corp_db.portfolio_lookup",
  "route_kind": "corp_table",
  "title": "Portfolio object lookup",
  "summary": "Find named realized projects, portfolio objects, references, customers, and implementation cases.",
  "topics": ["portfolio", "projects", "objects", "references", "realized_projects"],
  "keywords": ["портфолио", "реализованные проекты", "ржд", "логистический центр", "белый раст"],
  "executor": "corp_db_search",
  "locked_args": {
    "kind": "hybrid_search",
    "profile": "entity_resolver",
    "entity_types": ["portfolio", "sphere"]
  },
  "argument_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "query": {"type": "string", "maxLength": 500},
      "limit": {"type": "integer", "minimum": 1, "maximum": 50}
    },
    "required": ["query"]
  },
  "argument_hints": "Use the original user wording with named object, customer, project, or portfolio terms.",
  "fallback_route_ids": ["corp_db.portfolio_by_sphere", "corp_db.portfolio_examples_by_lamp"]
}
```

### Document-domain search

```json
{
  "route_id": "doc_search.sports_lighting_norms",
  "route_family": "doc_search.sports_lighting_norms",
  "route_kind": "doc_domain",
  "title": "СП 440.1325800.2023 Освещение спортивных сооружений",
  "summary": "Search inside the sports lighting norms document.",
  "executor": "doc_search",
  "document_selectors": ["doc_d535db29801e363a", "part_440.1325800.2023.doc"],
  "locked_args": {
    "preferred_document_ids": ["doc_d535db29801e363a", "part_440.1325800.2023.doc"]
  },
  "argument_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "query": {"type": "string", "maxLength": 240},
      "top": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5}
    },
    "required": ["query"]
  }
}
```

Document search semantics
-------------------------

`doc_search` does not mean "search documents generally".

It means "search inside one or more indexed documents that already have a route card with a concrete domain".

For v1:

- remove `doc_search.document_lookup` as a generic route;
- keep document-domain routes created from document metadata, such as `doc_search.sports_lighting_norms`;
- require `preferred_document_ids` or `document_selectors` for primary `doc_domain` routes;
- use `doc_search` for explicit document context: `в документе`, `согласно документу`, `покажи фрагмент`, `цитата`, exact document title, exact file name, or a route-specific topic match;
- do not route generic `сертификаты`, `паспорта`, `комплектующие`, or `качество` to `doc_search` unless a document route explicitly owns that topic.

This preserves the original document-search idea: when a document is added and indexed, its metadata defines the thematic route used for later search.

A single document may publish multiple thematic routes. For example, a large technical document may expose one route for lighting norms, another for emergency lighting, and another for TV broadcast lighting. These routes can share the same `document_selectors` but differ by `topics`, `summary`, `argument_hints`, and optional section/page scopes.

The inverse is also allowed: one route may search multiple documents when those documents jointly define a domain. The route card must still list concrete selectors and must not degrade into a catch-all corpus search.

Candidate prefilter policy
--------------------------

The route selector should not depend on a complex hand-weighted score in normal production.

If the active catalog is small enough, pass all compact route cards to the LLM selector.

The implemented v1 limit is 60 selector-visible routes. If the catalog is at or below that limit, the selector payload uses `candidate_mode=all_visible` and includes the whole compact catalog.

If the catalog becomes larger than the compact limit, use only simple deterministic ordering to reduce prompt size:

- exact route id or document id matches;
- exact phrase matches on title, summary, topics, and keywords;
- simple token overlap;
- source availability filters.

The ordering layer must not make the final production route decision. It only produces a bounded candidate list. The LLM then selects the route and arguments.

The previous weighted scoring rules should not remain in production selector payload construction, route prompts, or degraded route fallback. If future diagnostics need ranking experiments, they should live in separate offline tooling and must not share the runtime selector contract.

If the selector or finalizer LLM is unavailable, the service should not try to emulate route selection or answer synthesis with complex scoring. The agent cannot produce a trustworthy final answer without LLM access anyway, so the runtime should return a clear temporary-unavailable response instead of running an uncertain route.

Example user-facing message:

```text
Извините, сервис сейчас временно недоступен. Попробуйте повторить запрос немного позже.
```

This keeps the runtime simpler and avoids creating a second, lower-quality routing system.

Runtime retrieval state machine
-------------------------------

Production retrieval should follow one explicit state machine:

1. Load active merged route catalog.
2. Build compact route-card payload for the selector.
3. If the catalog is too large, run the simple prefilter to produce a candidate list.
4. Call the selector LLM with the user query and compact route candidates.
5. Parse strict JSON selector output.
6. Validate `selected_route_id`, `tool_args`, `fallback_route_ids`, and locked/default arg merge.
7. Execute the selected route's `executor`.
8. Classify tool output through the selected route's `evidence_policy`.
9. If evidence is `sufficient`, pass the evidence to the finalizer LLM and answer.
10. If evidence is `empty`, `weak`, or `error`, run at most one route-aware fallback.
11. Classify fallback evidence through that fallback route's `evidence_policy`.
12. Pass sufficient or exhausted evidence to the finalizer LLM.
13. If selector or finalizer LLM access is unavailable, return the temporary-unavailable response.

The selector LLM chooses the first retrieval route and arguments. The finalizer LLM writes the user-facing answer from validated evidence. This is consistent with RFC-021: the runtime still uses LLM-led orchestration, but the first retrieval step is constrained by route cards and schemas.

Evidence policy
---------------

Tool success is not the same as sufficient evidence.

Each retrieval result should be classified as:

- `sufficient`
- `weak`
- `empty`
- `error`

For `corp_db_search`, sufficient evidence requires route scope alignment:

- expected `knowledge_route_id` matches;
- expected `source_files` match when present;
- expected `topic_facets` intersect when present;
- result count is above the route policy threshold;
- payload rows have relevant headings/content for the user query or selected facet.

For `doc_search`, sufficient evidence requires document scope alignment:

- top results come from the route's `document_selectors`;
- result score is above threshold;
- matched text contains route-relevant query terms;
- the selected document route is still the active route family.

A non-empty result from the wrong route is `weak`, not `sufficient`.

Fallback policy
---------------

Fallbacks should be bounded and route-aware.

Default v1 policy:

- run the selected primary route first;
- if it returns `empty`, `error`, or `weak`, allow at most one fallback;
- fallback priority is: selected route card `fallback_route_ids`, selector output `fallback_route_ids`, then the prefilter candidate list only if the candidate has a compatible route kind and evidence policy;
- do not use `doc_search` as generic fallback for company facts;
- do not use a separately ranked route as fallback unless it is already in the bounded candidate list;
- do not continue LLM iterations after scoped evidence is sufficient;
- do not retry the same tool with semantically identical args.

Implemented portfolio hardening:

- if the selected route is `corp_kb.company_common`;
- and primary evidence is `empty` or `weak`;
- and the query contains strong portfolio/project signals such as `проект`, `реализован`, `РЖД`, `логистический центр`, or `Белый Раст`;
- run exactly one controlled fallback to `corp_db.portfolio_lookup` or `corp_db.portfolio_by_sphere`;
- classify that fallback evidence independently, without carrying the previous `knowledge_route_id` scope.

This reduces latency and removes the current pattern where most time is spent on extra LLM iterations after a fast DB call.

Catalog lifecycle
-----------------

The route catalog must have an explicit publication lifecycle.

Source inputs:

- repo-side static route specs for stable corp script routes;
- corp DB route specs generated or validated by DB loaders and `tools-api` search modes;
- document route specs generated from document ingestion metadata and live manifests;
- optional hand-authored bootstrap routes for local development only.

Build output:

- one merged route catalog consumed by runtime;
- `schema_version`;
- `catalog_version`;
- `generated_at`;
- source digests or source manifest versions;
- route count by `route_kind`;
- validation report.

Merge rules:

- route ids must be unique after merge;
- duplicate route ids from different owners are validation errors unless an explicit override is declared;
- generated source-owned routes take precedence over bootstrap routes;
- bootstrap routes are development fallback only and should not be the normal production source of truth;
- production runtime should fail health checks or return temporary-unavailable if no valid merged catalog exists.

Validation rules:

- every production route has `executor`, `locked_args`, `argument_schema`, and `evidence_policy`;
- every `doc_domain` route has concrete `document_selectors`;
- every `corp_table` route has table/entity/source scope or an explicit reason for being broad;
- every route's `locked_args` are accepted by the executor schema;
- enum-like lists above the compact threshold are rejected unless explicitly marked as external resolver input.

Runtime catalog hardening:

- loaded `catalog.v1.json` payloads are revalidated with the current code before they become active;
- stale embedded `validation_report` fields are not trusted as-is;
- current bootstrap route cards are merged during revalidation so newly shipped core routes are visible even when the runtime catalog file is older than the deployed code;
- when `ROUTING_CATALOG_REQUIRED=true`, runtime fails closed if the active merged catalog is missing or invalid, instead of falling back to repo manifests or bootstrap-only routing.

Route ownership by source
-------------------------

Route cards should be published by the source that owns the data.

Corporate DB routes:

- owned by corp DB schema/loaders;
- generated or validated from `db/search_docs.py`, `tools-api` search modes, and source manifests;
- include routes for KB chunks, catalog entities, SKUs, categories, mounting types, category mountings, spheres, and portfolio.

Document routes:

- owned by document ingestion metadata;
- generated from live document manifests;
- include concrete document ids and aliases;
- never create a generic catch-all document route by default.

Static script routes:

- owned by repo-side route specs;
- describe multi-table execution paths such as application recommendation and portfolio workflows.

Runtime catalog:

- merges source-published routes;
- records catalog version and origin;
- writes an explainable selector candidate set into request telemetry.

Skills cleanup
--------------

`corp-wiki-md-search` should be removed from the runtime shared skills layer.

The current state is inconsistent:

- `shared_skills/skills/corp-wiki-md-search` exists as an empty or non-functional local folder;
- `workspace/_shared/skills/corp-wiki-md-search` is a full skill and is loaded as `/data/skills/corp-wiki-md-search`;
- `workspace/_shared/skills_cache.json` marks it enabled.

Because `tools-api` rebuilds `skills_cache.json` from `skill.json`, disabling only the cache is not durable.

The durable cleanup is:

- delete or archive `workspace/_shared/skills/corp-wiki-md-search`;
- remove stale local copies that imply it is installable;
- rescan skills;
- verify `skills_cache.json` no longer includes it;
- update prompts/skills to prefer `corp_db_search` and concrete `doc_search` routes.

Runtime code responsibilities
-----------------------------

`core/agent.py` should stop owning business routing knowledge.

It should keep:

- LLM loop execution;
- the small route-selector LLM call;
- tool execution and safety guardrails;
- route-card interpretation;
- route argument validation and locked-arg merging;
- duplicate attempt protection;
- evidence classification through route policies;
- observability.

It should shed or shrink:

- duplicated `COMPANY_FACT_KEYWORDS`;
- duplicated `DOCUMENT_LOOKUP_KEYWORDS`;
- `_authoritative_kb_route_hint()` as a separate hard-coded router;
- route-specific query rewrite functions;
- route-specific argument extraction functions;
- generic non-empty `doc_search` sufficiency.

The selector in `core/documents/routing.py` should become the catalog loader, compact route-card formatter, optional prefilter, and validator. It should not remain a second business taxonomy.

System prompt update
--------------------

`core/src/agent/system.txt` must be updated as part of this refactor.

The prompt should no longer teach the agent the old broad source rule:

- `doc_search` for generic documents, PDFs, certificates, passports, and document facts;
- `corp_db_search` for a manually maintained list of company facts.

Instead, it should state:

- route cards and the LLM route selector choose the first retrieval path;
- `corp_db_search` is the normal source for structured corporate data and promoted KB routes selected by the route card;
- `doc_search` is only for concrete document-domain routes or explicit requests to search inside a known document;
- if selected route evidence is `sufficient`, answer from that evidence and do not continue tool exploration;
- if selected route evidence is `empty`, `weak`, or `error`, use only bounded route-aware fallback;
- do not browse skill files, raw filesystem paths, or shell search when a high-level route tool is available.

The prompt should stay short. Detailed routing rules belong in route cards, schemas, and evidence policies, not in the system prompt.

Data lifecycle
--------------

The repo and runtime paths should have explicit ownership:

- `doc-corpus/` is the versioned repo-side document source and manifest area.
- `/data/corp_docs`, mounted in this checkout as `workspace/_shared/corp_docs`, is runtime/generated state.
- DB source JSON files are source data for corp DB loaders.
- generated route catalogs are artifacts, not hand-edited business logic.

If a generated runtime manifest is checked into the repo for review, it must be clear whether it is source, generated fixture, or operational state.

Implementation outline
----------------------

Phase 1. Stop the immediate regressions:

1. Remove bare `сертификат` from unconditional explicit document triggers.
2. Remove or disable generic `doc_search.document_lookup`.
3. Add company KB routes or facets for `certification` and `quality`.
4. Add argument schemas and argument hints for certification and component quality routes.
5. Make `doc_search` evidence sufficient only when document scope matches.

Phase 2. Define route schema and catalog lifecycle:

1. Extend route card schema with `argument_schema`, `locked_args`, `argument_hints`, `evidence_policy`, `fallback_route_ids`, and `document_selectors`.
2. Add merged catalog generation with schema version, catalog version, source digests, route counts, and validation report.
3. Define merge precedence and duplicate route id validation.
4. Make production runtime depend on a valid merged catalog.

Phase 3. Consolidate route ownership:

1. Move route-specific topic facets out of `core/agent.py`.
2. Move KB route specs out of `tools-api` and `db/search_docs.py` duplication into a shared generated manifest or a small common source module.
3. Add route cards for missing structured domains:
   - categories;
   - ETM/ORACL SKU lookup;
   - mounting types;
   - category mountings;
   - lamp/category mounting compatibility.
4. Add support for multiple thematic document routes per document and multi-document route selectors.

Phase 4. Simplify runtime orchestration:

1. Add a small strict-JSON LLM selector for route and argument selection.
2. Validate selected route and `tool_args` against the route card.
3. Replace `_authoritative_kb_route_hint()` with LLM-selected route-card tool args.
4. Replace route-specific query rewrite and argument extraction functions with route `argument_schema` and `argument_hints`.
5. Replace hard-coded evidence rules with route `evidence_policy`.
6. Implement the explicit retrieval state machine from selector through finalizer.
7. Keep only security and anti-loop guardrails as hard runtime constraints.

Phase 5. Clean skills and docs:

1. Remove `corp-wiki-md-search` from runtime shared skills.
2. Rescan skills and verify cache.
3. Update `core/src/agent/system.txt` for the LLM route-selector model and concrete `doc_search` semantics.
4. Update doc-search and corp-pg-db skill descriptions if needed.

Phase 6. Add regression tests and replay:

1. Add route selector tests for the failed production queries.
2. Add evidence policy tests for wrong-document non-empty `doc_search`.
3. Add tests that `паспорт` does not match `спорт`.
4. Add catalog validation tests for missing table/entity route coverage.
5. Add bench/replay cases for the request ids that exposed the bug.

Phase 7. Remove score-gated routing remnants:

1. Remove production score calculation from selector payload construction.
2. Remove `score` and `selection_score` fields from route selector prompts and normal route-selection results.
3. Pass all selector-visible routes when the catalog fits the compact selector budget.
4. Use simple intent/catalog ordering only as a bounded candidate-size reducer for large catalogs or non-production degraded routing.
5. Verify selector/finalizer LLM outage returns temporary-unavailable instead of score fallback.

Phase 8. Portfolio route hardening:

1. Add `corp_db.portfolio_lookup` for named portfolio objects and realized project queries.
2. Add portfolio keywords for `РЖД`, `Белый Раст`, `логистический центр`, and realized project wording.
3. Add controlled fallback from weak/empty `corp_kb.company_common` evidence to portfolio routes for strong project queries.
4. Add replay tests for `Белый Раст` and `РЖД` project questions.

Testing approach
----------------

Unit tests:

- route catalog lifecycle and merge validation;
- route catalog compact formatting;
- argument schema validation;
- locked-argument merging;
- selector security rejection for unsafe args and prompt-injection attempts;
- invalid selector JSON and one-shot repair behavior;
- optional prefilter token/phrase boundary behavior;
- company KB facet selection;
- runtime retrieval state machine transitions;
- evidence classification for `corp_db_search` and `doc_search`.

Integration tests:

- `Какие используются комплектующие?` selects a quality route and calls `corp_db_search` with `corp_kb.company_common`, `topic_facets=["quality"]`, and an LLM-produced component-quality query;
- `какие есть сертификаты?` selects a certification route and calls `corp_db_search` with `corp_kb.company_common`, `topic_facets=["certification"]`, and an LLM-produced certification query;
- `Какие нормы освещенности для спортивных объектов?` selects the sports lighting document route only when document-domain wording or route-specific sports lighting wording is present;
- `Расскажи подробнее про терминально-логистический центр Белый Раст` selects `corp_db.portfolio_lookup` and can reach portfolio entity evidence;
- `Какие объекты были реализованы для РЖД?` selects `corp_db.portfolio_by_sphere` or a portfolio-capable route and does not stay trapped in `corp_kb.company_common`;
- generic company questions do not call `doc_search` after a sufficient company KB payload.

Operational checks:

- `/skills/mentions` does not list `corp-wiki-md-search`;
- routing telemetry includes selected route id, route family, route kind, selected source, selector model, selector latency, selector confidence, selector reason, catalog version, schema version, candidate ids, validated args shape, validation errors, repair attempt status, fallback source, evidence status, and close reason;
- selector/finalizer LLM outage returns a clear temporary-unavailable response without running score-based route fallback;
- route catalog validation reports missing route coverage for known corp DB entity types.

Acceptance criteria
-------------------

1. The generic query `какие есть сертификаты?` selects a company KB certification route, not `doc_search`.
2. The generic query `Какие используются комплектующие?` selects a company KB quality route, not `doc_search`.
3. A non-empty `doc_search` result from the wrong document does not close retrieval as sufficient.
4. `doc_search.document_lookup` no longer exists as a generic catch-all production route.
5. Every production `doc_search` primary route has concrete document selectors.
6. The selector LLM returns strict JSON with `selected_route_id`, `confidence`, `reason`, `tool_args`, and optional `fallback_route_ids`.
7. Route-specific argument extraction is represented through route `argument_schema`, `locked_args`, and `argument_hints`, not hard-coded in `core/agent.py`.
8. Compact enums up to roughly 50-60 short values are allowed in route cards when they materially improve argument selection.
9. Large finite value domains, such as SKU lists, are not injected as giant enums into the route selector prompt.
10. Invalid LLM-produced tool args are rejected or repaired before tool execution.
11. Selector prompt-injection attempts cannot override locked args, add undeclared tool args, choose hidden routes, or bypass evidence policy.
12. A valid merged catalog with schema version, catalog version, source digests, and validation report exists before runtime routing.
13. The runtime follows the explicit retrieval state machine from selector through finalizer.
14. One document can expose multiple thematic `doc_domain` routes without creating generic corpus lookup.
15. `core/src/agent/system.txt` describes route-card/LLM selector behavior and no longer presents generic certificates/passports as unconditional `doc_search` source selection.
16. If selector or finalizer LLM access is unavailable, runtime returns a clear temporary-unavailable message instead of using a complex score-based route fallback.
17. Route-specific evidence requirements are represented in route metadata or a shared policy module, not as scattered special cases.
18. `corp-wiki-md-search` is not loaded as an enabled runtime skill.
19. Route catalog validation covers KB, catalog, SKU, category, mounting, portfolio, and document-domain routes.
20. `Расскажи подробнее про терминально-логистический центр Белый Раст` reaches `corp_db.portfolio_lookup`, not only `corp_kb.company_common`.
21. `Какие объекты были реализованы для РЖД?` reaches a portfolio-capable route, preferably `corp_db.portfolio_by_sphere`.
22. Normal selector payloads contain route cards and arguments, not score fields.
23. Loaded runtime catalogs are revalidated against current code and do not hide newly shipped bootstrap routes.
24. The original certification/component failures and the portfolio failures complete with one selector call, one fast authoritative DB retrieval when evidence is sufficient, and a final answer, without extra irrelevant tool iterations.
