RFC-026 Canonical Route Arguments, Curated Sphere Categories, And Bounded Portfolio Retrieval
==============================================================================================

Status
------

Proposed

Date
----

2026-04-24

Last updated
------------

2026-04-25

Related RFCs
------------

- RFC-018 introduced the unified routing catalog for tables, scripts, and documents.
- RFC-021 moved production routing toward a small LLM-led selector.
- RFC-025 made route cards the primary runtime contract for route selection and tool arguments.

Context and motivation
----------------------

Production traces from 2026-04-24 show that the current route-card-centered selector still fails on simple portfolio questions:

- `расскажи про реализованные объекты ржд`
- `реализованные промышленные объкты`

The failure is not caused by missing data:

- `db/spheres.json` contains 12 canonical spheres, including `РЖД` and `Промышленное освещение`;
- `db/mounting_types.json` contains 20 canonical mounting types;
- `docs/knowledge_base/common_information_about_company.md` defines 7 canonical lighting series and their category families:
  - `LAD LED R500`
  - `LAD LED R700`
  - `LAD LED R500 2Ex`
  - `LAD LED R320 Ex`
  - `LAD LED LINE`
  - `NL Nova`
  - `NL VEGA`
- `db/categories.json` contains 163 categories, including 23 root categories with `parent: null`.
- application and sphere-oriented answers currently pull too many categories from `corp.sphere_categories`, which reflects the full imported site linkage instead of a compact runtime-facing subset.

Further analysis on 2026-04-25 clarified that the desired runtime subset is not the same thing as `root categories`.

- the proposed curated sphere mapping spans all 12 spheres;
- it contains 33 sphere-to-category edges;
- it references 25 unique categories;
- it includes both root categories and selected child families such as `34 LAD LED R700 PROM`, `32 LAD LED R700 HT`, `33 LAD LED R700 ST`, `63 LAD LED R500 ZD`, `64 LAD LED R500 LZD`, `121 LAD LED R500 2Ex (12/24/36V)`, `147 LAD LED R320 Ex (36V)`, and `168 Охранное освещение`.

The failure is caused by argument selection and evidence policy:

1. the selector does not receive canonical domain values for `sphere` and similar fields;
2. `portfolio_lookup` is broad enough that the selector can choose it instead of `portfolio_by_sphere`;
3. `hybrid_search + profile=entity_resolver` is treated as sufficient evidence for broad portfolio questions;
4. after `portfolio_by_sphere` returns `empty`, runtime falls back into a generic LLM loop instead of a short, deterministic portfolio-specific recovery path;
5. `tools-api` portfolio sphere fallback uses `APPLICATION_PROFILES`, which currently does not cover all real spheres, including `РЖД` and `Промышленное освещение`;
6. sphere-oriented category answers and recommendations currently derive from the full imported `sphere_categories` relation instead of a curated runtime-facing subset.

Problem statement
-----------------

RFC-025 correctly moved route selection and argument extraction into a compact LLM call, but it left one unresolved architectural issue:

the selector knows which argument fields are allowed, but often does not know the canonical values those fields should take.

As a result:

- the model can emit `sphere="промышленные объекты"` instead of canonical `Промышленное освещение`;
- the model can select a broad route that postpones concrete argument resolution instead of selecting the route that already requires the canonical domain field;
- backend fallbacks depend on a partial alias map rather than on the actual domain catalogs.
- when the user asks about application spheres, runtime can return a large noisy list of categories instead of the short business-approved set that should actually be shown.

Goals
-----

- Provide canonical argument values to the selector where the domain is small and stable.
- Keep large domains out of the selector payload when the list is too large to be useful.
- Introduce a curated per-sphere category subset that is separate from the full imported sphere-category relation.
- Add a dedicated route for "categories by sphere" that returns all curated categories for the resolved sphere.
- Make portfolio routing choose `portfolio_by_sphere` for broad object/project questions.
- Prevent `entity_resolver` from prematurely closing retrieval for broad portfolio asks.
- Replace open-ended post-empty LLM loops with bounded portfolio-specific fallback.
- Reuse real domain catalogs as the source of canonical values and alias resolution.

Non-goals
---------

- Replacing the LLM selector with a deterministic scoring engine.
- Enumerating every catalog category or SKU in selector payloads.
- Solving all catalog normalization problems in one change.
- Introducing a new generic ontology service.
- Replacing the full imported `corp.sphere_categories` relation with the curated runtime subset.

Current domain sizes
--------------------

As of 2026-04-24:

- spheres: 12
- mounting types: 20
- categories: 163
- root categories where `parent: null`: 23
- canonical series: 7
- proposed curated sphere-category edges: 33
- unique categories referenced by the curated sphere mapping: 25

This matters because RFC-025 already limits compact selector enums to roughly 60 values.

Decision
--------

Route cards should expose canonical argument values when the domain is small enough, runtime should use bounded, domain-specific fallback when canonicalization still fails, and sphere-oriented category answers should use a dedicated curated relation rather than the full imported sphere-category linkage.

The selector should not receive only a field name like `sphere`; it should receive either:

- an explicit compact enum of allowed values, or
- a free string field plus a clear instruction that runtime will resolve it against a concrete domain catalog.

The split is:

1. `sphere`
   - use explicit enum from `db/spheres.json`
   - current size 12, well within the compact enum limit

2. `mounting_type`
   - use explicit enum from `db/mounting_types.json`
   - current size 20, well within the compact enum limit

3. `series`
   - use explicit enum from the canonical series list defined in `docs/knowledge_base/common_information_about_company.md`
   - current size 7, well within the compact enum limit
   - series enum is appropriate for routes whose argument semantics are broad model family / business series rather than exact lamp model or exact category leaf

4. `category`
   - do not expose all 163 categories as one enum
   - do not equate runtime-facing category choices with `parent: null`
   - introduce a curated per-sphere category relation for routes that present or constrain categories within a resolved sphere
   - keep global leaf-category lookup as free string or resolver-assisted field unless the enum can be narrowed dynamically by sphere context
   - for now, runtime category enum means only scoped curated-category enum, not root-category enum

5. `curated category enum`
   - use dynamic enum only after the sphere is already resolved
   - derive the enum from curated categories attached to that sphere
   - never expose a cross-sphere union of all curated categories when the sphere is still unknown
   - this is the only category-enum mode in the current proposal

Design principles
-----------------

1. Real catalogs beat handwritten aliases
   - if a field maps to a concrete DB or JSON domain, selector payloads and backend resolvers should derive from that domain, not from duplicated Python dictionaries.

2. Small enums are good
   - spheres, mounting types, and canonical series are compact enough to help the model choose canonically correct values.

3. Dynamic scoped enums are better than global medium-sized enums
   - curated categories are useful once the sphere is known, because then the per-sphere choice set is small and semantically coherent.

4. Large enums are not good
   - 163 categories and hundreds of model families should not be dumped into every selector prompt.

5. Broad portfolio asks need broad portfolio routes
   - questions like `какие объекты были реализованы для РЖД` are not named-object lookup; they are portfolio-by-segment requests.

6. Curated runtime subsets should not overwrite imported source structure
   - the system should keep both:
     - the full imported `sphere -> categories` linkage;
     - the curated runtime subset used by the agent.

7. Intermediate evidence is not final evidence
   - `entity_resolver` may identify a likely segment or object family, but that does not answer a broad portfolio question by itself.

8. Empty should close quickly
   - after one canonicalization attempt and one bounded fallback, runtime should stop rather than synthesize unrelated catalog filters.

Data model change
-----------------

Add a new relation dedicated to runtime-facing curated category subsets, and preserve enough hierarchy metadata to expand curated display categories into executable leaf categories when needed.

Proposed table:

- `corp.sphere_curated_categories`
  - `sphere_id`
  - `category_id`
  - `position`
  - `source_hash`
  - timestamps if needed by local conventions

Additional required catalog metadata:

- `corp.categories.parent_category_id`
  - nullable self-reference to `corp.categories(category_id)`
  - sourced from `db/categories.json.parent.id`

Optional future materialization:

- `corp.series_catalog`
  - canonical series names sourced from `docs/knowledge_base/common_information_about_company.md`
- `corp.series_categories`
  - mapping from canonical series to categories
  - may be materialized later if multiple runtime paths need direct DB access to series/category families

Semantics:

- `corp.sphere_categories`
  - full imported sphere-to-category relation from `db/spheres.json`
  - source-of-fact linkage

- `corp.sphere_curated_categories`
  - business-approved runtime subset used by the agent for sphere-oriented answers and scoped category selection

- `display categories`
  - the exact rows from `corp.sphere_curated_categories`
  - shown to the user for sphere application questions
  - used to build scoped `category` enum after sphere resolution

- `executable categories`
  - the category ids actually used in DB search and recommendation queries
  - derived from display categories by expanding through the category tree via `parent_category_id`
  - if a curated category has no children, it is executable as-is
  - if a curated category is a family node, runtime expands it to its leaf descendants before lamp-ranking or exact catalog retrieval

Proposed source-of-truth shape in `db/spheres.json`:

```json
{
  "id": 3,
  "name": "Складские помещения",
  "categoriesId": [
    {"id": 89},
    {"id": 87},
    {"id": 39}
  ],
  "curatedCategoryIds": [
    {"id": 37, "position": 1},
    {"id": 34, "position": 2},
    {"id": 39, "position": 3},
    {"id": 33, "position": 4},
    {"id": 13, "position": 5}
  ]
}
```

This preserves the imported structure and adds a second explicit runtime-facing subset.

Display vs executable categories
--------------------------------

The review concern here is real: the curated sphere list is a business-facing set of category families, but some runtime operations need leaf-like executable categories.

The split should be explicit:

1. display categories
   - what the user sees for `какие категории подходят для склада`
   - examples:
     - `LAD LED R500`
     - `LAD LED R700 PROM`
     - `LAD LED LINE-OZ`

2. executable categories
   - what the backend uses to fetch lamps, rank recommendations, or run category-scoped retrieval
   - if the chosen display category is already a leaf, the executable set is that single category
   - if the chosen display category is a parent/family node, the executable set is its descendant leaf categories

This avoids two opposite errors:

- showing too many categories to the user;
- overconstraining search to a broad family node that is not directly executable in the current query path.

Sphere context model
--------------------

Scoped curated-category enum requires a precise context model. It should not be an implicit long-lived conversational guess.

Proposed runtime state:

- `resolved_sphere_context`
  - `sphere_id`
  - `sphere_name`
  - `source_route_id`
  - `source_message_id` or equivalent turn identifier
  - `confidence`
  - `confirmed` boolean

Context is created when:

- a route with explicit `sphere` succeeds, such as:
  - `corp_db.sphere_curated_categories`
  - `corp_db.portfolio_by_sphere`
  - `corp_db.application_recommendation`
- or the user explicitly selects/clarifies a sphere in a follow-up turn

Context may be used when:

- the next user turn is a local follow-up that refers to:
  - `эта категория`
  - `эта серия`
  - `из этого списка`
  - `для этой сферы`
- or the next route requires scoped `category` disambiguation and the previous successful turn set a high-confidence sphere

Context must be cleared when:

- the user explicitly names another sphere;
- the user asks an unrelated global query such as:
  - exact model lookup
  - ETM/ORACL/SKU lookup
  - generic company facts
  - document lookup
- the context becomes stale after a small number of user turns without reuse;
- the previous sphere resolution had low confidence and was never confirmed

Recommended lifecycle:

- last-sphere-wins
- valid for immediate follow-ups only
- automatic expiry after 2 user turns if not reused or confirmed

Proposed route-card changes
---------------------------

`corp_db.portfolio_lookup`

- Narrow the summary and hints so the route means named-object lookup:
  - `расскажи про объект Белый Раст`
  - `покажи проект <название>`
  - `что известно об объекте <name>`
- Remove wording that makes it look like the primary route for generic `реализованные объекты` questions.

`corp_db.portfolio_by_sphere`

- Make this the preferred route for broad project/object questions:
  - `какие объекты были реализованы`
  - `проекты для РЖД`
  - `покажи промышленные объекты`
  - `примеры объектов по складам`
- Add `argument_schema.properties.sphere.enum` built from `db/spheres.json`.
- Keep `query` as optional supporting text for ambiguous cases.

`corp_db.sphere_curated_categories`

- Add a new primary route for user questions about categories or lighting series by application sphere.
- This route resolves the sphere, fetches curated categories from `corp.sphere_curated_categories`, and returns all curated categories for that sphere in display order.
- It replaces the current user-facing role of `corp_db.sphere_categories`, which should remain available only if full imported linkage is still needed for diagnostics or offline analysis.
- Add `argument_schema.properties.sphere.enum` built from `db/spheres.json`.
- Do not require a `category` argument for this route.

Routes with series semantics

- Add `series` as a first-class optional argument for routes whose semantics are broad product family selection rather than exact lamp model lookup.
- Build `argument_schema.properties.series.enum` from the canonical series list in `docs/knowledge_base/common_information_about_company.md`.
- Series enum is appropriate for:
  - series-aware catalog narrowing
  - series-aware mounting compatibility
  - sphere-to-series or series-to-category follow-up flows
- Series enum is not a substitute for exact `name` in exact-model lookup routes.

`corp_db.category_mountings`

- Add `argument_schema.properties.mounting_type.enum` built from `db/mounting_types.json`.

Routes that use curated category families

- Do not use one global `category` enum.
- Use a dynamic per-sphere curated-category enum only when the sphere is already known in the request or conversation state.
- Do not force curated-category enum onto routes that need exact leaf-category retrieval across the whole catalog.

Selector payload policy
-----------------------

The compact selector payload should include route-specific value lists only when they are small and useful.

Examples:

```json
{
  "route_id": "corp_db.portfolio_by_sphere",
  "argument_schema": {
    "type": "object",
    "properties": {
      "sphere": {
        "type": "string",
        "enum": [
          "Промышленное освещение",
          "Тяжелые условия эксплуатации",
          "Складские помещения",
          "Спортивное и освещение высокой мощности",
          "РЖД",
          "Периметральное и охранное освещение",
          "Наружное, уличное и дорожное освещение",
          "Офисное, торговое, ЖКХ и АБК освещение",
          "Взрывозащищенное оборудование",
          "Низковольтное оборудование",
          "Светильники специального назначения",
          "Архитектурное освещение"
        ]
      },
      "query": {
        "type": "string",
        "maxLength": 500
      }
    },
    "required": ["sphere"]
  }
}
```

This lets the model choose `РЖД` directly instead of inventing another wording.

Curated categories should be exposed differently:

- not as a global enum across all spheres;
- only as a dynamic enum when runtime already knows the sphere;
- only for routes where `category` means one of the curated sphere families, not an arbitrary catalog leaf.

Example after sphere resolution:

```json
{
  "route_id": "corp_db.category_lamps",
  "context_scope": {
    "sphere_id": 3,
    "sphere_name": "Складские помещения"
  },
  "argument_schema": {
    "type": "object",
    "properties": {
      "category": {
        "type": "string",
        "enum": [
          "LAD LED R500",
          "LAD LED R700 PROM",
          "LAD LED LINE-OZ",
          "LAD LED R700 ST",
          "LAD LED LINE"
        ]
      }
    },
    "required": ["category"]
  }
}
```

This is small, coherent, and derived from a resolved sphere instead of the full catalog.

Route analysis for curated-category enum usage
----------------------------------------------

The current route set uses `category` in several different semantic modes. Curated-category enum is useful only in some of them.

Good candidates:

1. `corp_db.sphere_curated_categories`
   - no `category` input is needed
   - the route should resolve `sphere` and return all curated categories for display
   - this is the main new user-facing route for sphere application questions

2. `corp_db.application_recommendation`
   - use curated categories internally as a whitelist after sphere resolution
   - do not expose `category` enum in the initial selector call
   - if the flow later asks the model to narrow within a resolved sphere, then a dynamic curated-category enum is appropriate

3. `corp_db.category_lamps`
   - curated-category enum is useful only after sphere is known
   - example: user first asks `какие категории подходят для склада`, then asks `покажи модели из LAD LED LINE-OZ`

4. `corp_db.category_mountings`
   - curated-category enum is useful only after sphere is known or inferred from the current thread
   - this helps avoid choosing irrelevant categories outside the selected application area

5. `corp_db.lamp_mounting_compatibility`
   - same as `category_mountings`
   - use scoped enum only in a resolved-sphere follow-up flow

Conditionally useful:

6. `corp_db.lamp_filters`
   - keep `category` as a free string in the initial selector call
   - use curated-category enum only when the user is already filtering inside a known sphere and wants to narrow to one approved family

Also useful:

7. routes with explicit `series` semantics
   - series enum can be global because it contains only 7 business-defined values
   - use it in routes where the user asks about a family such as `что доступно в серии LAD LED R700` or `какие крепления у серии NL Nova`
   - do not mix `series` enum into routes whose primary semantics are exact lamp model or exact SKU

Usually not useful:

8. `corp_db.portfolio_examples_by_lamp`
   - primary argument is exact `name`
   - category-level use exists, but curated-category enum is secondary and should not be the default route design

Not recommended:

9. global `catalog_lookup`
   - this route spans exact models, series, codes, and category-like wording across the whole catalog
   - curated-category enum would overconstrain it and would mix sphere-local semantics into a global route
   - series enum may still be useful here only if `catalog_lookup` is split or extended to distinguish exact-model mode from broad-series mode

Portfolio evidence policy
-------------------------

Broad portfolio questions should not close on `entity_resolver`.

For these questions:

- `hybrid_search + profile=entity_resolver` is intermediate evidence;
- retrieval may close only after a portfolio-capable route succeeds:
  - `portfolio_by_sphere`, or
  - another explicitly declared portfolio route that returns final portfolio rows.

In practice:

- `расскажи про реализованные объекты ржд` must not close after non-empty entity resolver output;
- it should continue to `portfolio_by_sphere(sphere="РЖД")`.

Bounded portfolio fallback
--------------------------

When `portfolio_by_sphere` returns `empty`, runtime should not enter an open-ended generic LLM loop.

Instead it should execute this bounded policy:

1. primary attempt
   - use selector-provided canonical `sphere` if present

2. canonicalization retry
   - if `sphere` is free text or fails to match exactly, resolve it against the real sphere catalog
   - examples:
     - `ржд` -> `РЖД`
     - `промышленные объекты` -> `Промышленное освещение`
     - `логистический центр` -> `Складские помещения`

3. one bounded fallback
   - either:
     - ask a concise clarification if there are 2-3 near-equal sphere candidates, or
     - execute one route-card-declared fallback

4. stop
   - if still empty, return a clean no-data answer instead of continuing with unrelated retrieval attempts such as `sphere_categories` or noisy lamp filters.

Backend canonicalization policy
-------------------------------

`tools-api` should resolve portfolio sphere input against the actual sphere catalog first, and only then use curated alias helpers.

Resolution order:

1. exact canonical sphere name
2. case-insensitive normalized exact match
3. compact alias map derived from the real sphere catalog and maintained per sphere
4. substring or token fallback when confidence is high
5. explicit ambiguity result when confidence is low

`APPLICATION_PROFILES` remains useful for recommendation logic, but it should not be the sole fallback resolver for `portfolio_by_sphere`.

Why this is simpler than the current behavior
---------------------------------------------

This proposal removes complexity from the unstable places:

- less dependence on broad route summaries;
- less dependence on partial handwritten alias maps;
- less dependence on repeated LLM retries after empty search;
- less dependence on `entity_resolver` being treated as both resolver and final evidence.

It adds only two simple forms of structure:

- compact enums for genuinely small domains;
- compact series enum for business-defined families;
- dynamic scoped enums for sphere-local curated categories;
- a short bounded fallback policy for portfolio retrieval.

Implementation outline
----------------------

1. Add route-card enum support for domain-backed compact values
   - generate sphere enum from `db/spheres.json`
   - generate mounting type enum from `db/mounting_types.json`
   - generate series enum from `docs/knowledge_base/common_information_about_company.md`

2. Add curated sphere-category data model
   - extend `db/spheres.json` with `curatedCategoryIds`
   - create `corp.sphere_curated_categories`
   - persist `parent_category_id` in `corp.categories`
   - update `db/catalog_loader.py` to seed the new table and the parent linkage

3. Add new route behavior for sphere application questions
   - introduce `corp_db.sphere_curated_categories`
   - resolve the sphere and return all curated categories for that sphere
   - keep old `corp_db.sphere_categories` out of user-facing routing unless full imported linkage is explicitly needed

4. Tighten portfolio route semantics
   - narrow `corp_db.portfolio_lookup`
   - make `corp_db.portfolio_by_sphere` primary for broad project/object wording

5. Update selector payload generation
   - include compact enums in route-specific argument schemas
   - keep large domains as free strings
   - inject dynamic curated-category enums only when sphere context exists

6. Update application/category routes
   - switch `application_recommendation` display layer to curated categories
   - expand curated display categories to executable category ids before lamp-ranking
   - use scoped curated-category enums in category follow-up routes when sphere context exists

7. Add sphere context lifecycle
   - persist `resolved_sphere_context` in runtime state
   - inject scoped curated-category enum only when context is valid
   - clear context on explicit sphere change, unrelated global queries, or staleness

8. Update runtime evidence policy
   - mark `entity_resolver` as non-sufficient for broad portfolio queries
   - require final portfolio evidence before closure

9. Update `tools-api` portfolio sphere resolution
   - resolve against real spheres first
   - add ambiguity output rather than silent failure where needed

10. Extend contracts for the new route/tool kind
   - add `sphere_curated_categories` to `corp_db_search.kind` enums in:
     - `core/documents/route_schema.py`
     - `tools-api/src/tools/corp_db.py`
     - `tools-api` route dispatch

11. Replace open-ended post-empty behavior
   - implement one canonicalization retry
   - implement at most one bounded fallback or clarification

Testing approach
----------------

Unit tests:

- selector payload includes 12-value sphere enum for `portfolio_by_sphere`
- selector payload includes 20-value mounting-type enum where applicable
- selector payload includes 7-value series enum where route semantics require `series`
- curated sphere-category seeding creates the expected 33 sphere-category edges
- curated category order is preserved
- category parent linkage is preserved in DB
- executable-category expansion from curated display categories works for both leaf and family nodes
- large category domains are not emitted as full enums
- scoped curated-category enum is emitted only when sphere context exists
- scoped curated-category enum is not emitted when sphere context is missing or stale
- `portfolio_lookup` and `portfolio_by_sphere` ordering matches broad vs named-object phrasing
- `entity_resolver` does not produce `sufficient` for broad portfolio intents

Integration tests:

- `Какие категории подходят для склада?` resolves to `Складские помещения` and returns exactly the curated category set for that sphere
- `Какие категории подходят для РЖД?` returns `LAD LED R500 ZD` and `LAD LED R500 LZD`
- `Какие серии доступны?` can use the canonical 7-series enum on series-aware routes
- `Какие объекты были реализованы для РЖД?` selects `portfolio_by_sphere` with `sphere=РЖД`
- `Покажи промышленные объекты` resolves to `Промышленное освещение` or asks a bounded clarification
- `Расскажи про объект Белый Раст` still uses named-object lookup
- after `portfolio_by_sphere` empty, runtime performs at most one bounded fallback and stops
- a follow-up like `покажи модели из этой категории` uses the scoped curated-category enum if sphere context is already known
- a follow-up after an unrelated company or document query does not reuse stale sphere context

Manual checks:

- confirm sphere application answers no longer dump the full imported category list
- confirm curated categories are shown in the configured order
- confirm series-aware routes show only the canonical 7 business series where appropriate
- confirm route traces show canonical `sphere` arguments
- confirm no noisy lamp-filter arguments appear in portfolio fallback flows
- confirm overall latency drops by removing extra LLM iterations after empty portfolio retrieval

Acceptance criteria
-------------------

1. The selector receives canonical sphere values from the real sphere catalog.
2. The selector receives canonical mounting type values from the real mounting-type catalog.
3. The selector receives canonical series values from the KB-defined series catalog on routes where `series` is a first-class argument.
4. A new `corp.sphere_curated_categories` table exists and is seeded from `db/spheres.json`.
5. `corp.categories` preserves parent linkage needed for executable-category expansion.
6. User-facing sphere application questions return curated display categories, not the full imported `sphere_categories` set.
7. Runtime expands curated display categories into executable categories before recommendation and category-scoped search.
8. The runtime does not expose all 163 categories as one selector enum.
9. Curated-category enum is used only in scoped situations where sphere context already exists and is still valid.
10. `Какие объекты были реализованы для РЖД?` routes to a portfolio-capable route and does not close on entity resolver output.
11. `Покажи промышленные объекты` does not fail only because the user used non-canonical wording instead of exact `Промышленное освещение`.
12. `tools-api` portfolio sphere fallback is no longer limited to the current `APPLICATION_PROFILES` coverage.
13. After `portfolio_by_sphere` returns `empty`, runtime executes at most one bounded fallback or one clarification step.
14. Portfolio fallback does not generate unrelated structured lamp-filter arguments.
15. Named-object portfolio lookup remains supported and is not regressed by the broader portfolio routing changes.
