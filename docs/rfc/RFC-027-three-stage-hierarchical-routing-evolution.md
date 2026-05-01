RFC-027 Three-Stage Hierarchical Routing Evolution
==================================================

Status
------

Proposed

Date
----

2026-04-27

Last updated
------------

2026-04-27

Related RFCs
------------

- RFC-021 simplified runtime orchestration around a small LLM-led selector.
- RFC-025 made route cards the primary runtime contract for route selection and tool arguments.
- RFC-026 introduced canonical route arguments, curated sphere categories, and bounded portfolio retrieval.

Context and motivation
----------------------

The current routing system is already safer than the older free-form ReAct flow, but it still has one architectural mismatch with the product shape of the questions users actually ask.

The runtime route catalog is still too flat.

In one selector space the system mixes:

- general company information;
- series descriptions;
- curated categories by sphere;
- portfolio projects by sphere;
- mountings by category;
- catalog lookup;
- document lookup;
- article and external code lookup.

That creates three recurring problems:

1. the selector sees too many neighboring routes that partially overlap semantically;
2. several routes still expose argument schemas that are broader than the real business question they serve;
3. the runtime often routes by underlying storage shape instead of by user-visible question type.

Recent incidents around broad series questions and sphere-driven recommendations confirmed this gap:

- broad queries like `Какие у вас есть серии светильников?` drifted into catalog/entity routes instead of staying in company knowledge;
- recommendation and portfolio questions around `РЖД` were sensitive to schema drift and route ambiguity;
- document and SKU questions still compete with broader catalog routes when the route model should make them first-class question types.

The product direction is now clearer.

Routing should evolve in three explicit stages:

1. general routes aligned with stable data domains and tables;
2. specialized user-question routes extracted from real traffic;
3. route-specific executors and scripts for hot paths where quality, latency, or correctness matter.

The key correction in this RFC is that the system should not add a brittle algorithmic shortlist of leaf routes before the LLM. Instead, it should introduce a small, stable hierarchy:

- the selector chooses a route family from a fixed business-level map;
- the selector also chooses a leaf route inside that family, ideally in the same compact LLM call;
- only route-local schemas are exposed for argument generation.

This keeps LLM flexibility while reducing semantic overlap and prompt complexity.

Problem statement
-----------------

The current implementation mixes two different ideas of a route:

- a route as a storage-backed access path;
- a route as a user-facing question type.

The first idea is useful for tool implementation. The second is what the selector actually needs.

Today this mismatch causes:

- flat selection over too many routes at once;
- accidental competition between broad and narrow routes;
- over-wide argument schemas that invite invalid fields;
- hidden routing complexity spread across heuristics, route cards, and fallback logic;
- difficulty growing the system in a controlled way as new question classes appear.

The project needs a routing architecture that matches the real product lifecycle:

- start with broad, trustworthy data-domain routes;
- split them into specialized business routes only when real traffic justifies it;
- accelerate selected routes with dedicated executors only after correctness and traffic prove the need.

Goals
-----

- Represent routing as a small hierarchy of business route families and leaf routes.
- Avoid brittle algorithmic shortlists of leaf routes before the LLM.
- Keep the LLM as the primary selector, but reduce the selector space to semantically distinct route families.
- Make leaf routes correspond to clear user question types rather than only to raw tables.
- Narrow every route schema so it contains only fields meaningful for that route.
- Use enums for compact canonical domains such as sphere, curated category, mounting type, document type, and similar small business vocabularies.
- Separate three product stages explicitly: broad routes, specialized leaf routes, and optimized executors.
- Introduce missing first-class routes for category showcase lamps, document lookup by lamp name, and clean SKU/code lookup.
- Bound fallback and recovery inside the selected family instead of letting unrelated routes compete globally.
- Make routing evolution traffic-driven and observable.

Non-goals
---------

- Replacing the LLM selector with a fully deterministic keyword router.
- Creating a mandatory algorithmic shortlist of exact leaf routes before every selection.
- Rewriting every existing tool and table in one release.
- Eliminating route-card metadata or schema validation.
- Solving all catalog normalization problems in this RFC.
- Materializing every future specialization in the database immediately.

Decision
--------

The routing system should evolve into a hierarchical, three-stage model.

The stable production contract becomes:

1. the selector receives a small fixed set of business route families;
2. each family contains a small set of leaf routes representing concrete user question types;
3. the selector returns both the selected family and the selected leaf route, plus strictly validated route-local arguments;
4. route execution stays bounded inside the family unless an explicitly declared cross-family fallback exists;
5. hot routes may later replace generic tool execution with route-specific scripts or resolvers without changing the public routing contract.

This RFC keeps the LLM as the primary chooser. It does not introduce a hard algorithmic leaf-route shortlist.

Instead of:

- `query -> Python narrows to 3 fragile leaf routes -> LLM chooses one`

use:

- `query -> LLM chooses one business family and one leaf route from a compact route tree -> validated execution`

This preserves model flexibility while preventing the selector from seeing an unstructured flat list of unrelated routes.

Design principles
-----------------

1. Family-first, not full-catalog-flat
   - The selector should reason over a small set of semantically distinct families.
   - The selector should not normally see the entire leaf-route catalog as one flat pool.

2. LLM selection, schema-bounded arguments
   - Route choice remains an LLM task.
   - Argument generation remains an LLM task.
   - Validation and canonicalization remain runtime responsibilities.

3. No brittle mandatory keyword shortlist
   - Deterministic logic may enrich context, resolve canonical aliases, or reduce obvious ambiguity.
   - Deterministic logic should not silently hide the correct leaf route from the selector.

4. User-question routes beat storage-shaped routes
   - The selector should think in terms of `documents by lamp`, `projects by sphere`, and `series description`, not only `table X` or `search mode Y`.

5. Narrow schemas beat generic schemas
   - Each leaf route exposes only the fields it really needs.
   - Locked arguments define execution scope; LLM-supplied arguments fill only route-specific gaps.

6. Specialize only when traffic proves it
   - General routes are the starting point.
   - Specialized routes appear when real user questions cluster around a stable business task.

7. Optimize only after the route semantics are stable
   - Dedicated scripts, tables, or resolvers belong to stage 3, not stage 1.

Target routing model
--------------------

The target routing model has three layers.

1. route family
   - the stable business domain presented to the selector;
   - small in number;
   - expected to change rarely.

2. leaf route
   - the concrete question type executed at runtime;
   - may grow over time as the product observes real traffic;
   - owns the route-local schema.

3. executor
   - the actual implementation path;
   - can be generic search, SQL-backed tool, curated resolver, or dedicated script.

The selector contract should look like this conceptually:

```json
{
  "selected_family_id": "portfolio",
  "selected_route_id": "portfolio_projects_by_sphere",
  "confidence": "high",
  "reason": "The user asks for realized projects in a specific application sphere.",
  "tool_args": {
    "sphere": "РЖД",
    "limit": 3
  }
}
```

The public route identity for observability should always include both family and leaf route.

Stage model
-----------

Stage 1: General data-domain routes
-----------------------------------

Stage 1 establishes a minimal, stable set of broad business families aligned with the current trustworthy data domains.

These routes should correspond to the current durable sources of truth:

- company knowledge;
- catalog entities and examples;
- sphere-category mapping;
- portfolio;
- mountings;
- documents;
- SKU/article/code lookup.

Recommended stage-1 family set:

- `company_info`
- `catalog`
- `sphere_category_mapping`
- `portfolio`
- `mountings`
- `documents`
- `codes_and_sku`

At stage 1 the selector can choose directly from these families and, where needed, from one broad leaf route inside each family.

Examples:

- `company_info/company_general`
- `catalog/catalog_entity_lookup`
- `sphere_category_mapping/curated_categories_by_sphere`
- `portfolio/portfolio_projects_by_sphere`
- `mountings/mountings_by_category`
- `documents/documents_by_lamp_name`
- `codes_and_sku/sku_codes_lookup`

Stage 1 is intentionally broad. Its job is not to perfectly encode every user question. Its job is to provide reliable family boundaries and safe schemas.

Stage 2: Traffic-driven specialization
--------------------------------------

Stage 2 begins when repeated user traffic shows that one broad family actually contains several stable question classes that deserve their own leaf routes.

Examples:

- `company_info` may split into:
  - `company_general`
  - `company_contacts`
  - `company_certification_info`
  - `series_description`

- `catalog` may split into:
  - `catalog_entity_lookup`
  - `showcase_lamps_by_category`
  - `catalog_filters_by_category`

- `portfolio` may split into:
  - `portfolio_projects_by_sphere`
  - `portfolio_examples_by_series` if later justified

- `documents` may split into:
  - `documents_by_lamp_name`
  - `passport_by_lamp_name`
  - `certificate_by_lamp_name`

- `codes_and_sku` may split into:
  - `sku_codes_lookup`
  - `sku_by_name`
  - `lamp_by_external_code`

Stage 2 should always be justified by evidence from production traffic, replay traces, or benchmark questions.

A specialization is valid when all of the following hold:

- the question type appears repeatedly in user traffic;
- the broad parent route is becoming overloaded semantically;
- a narrower schema would materially reduce routing or argument errors;
- observability can clearly distinguish the new leaf route from the old broad route.

Stage 3: Route-specific optimization
------------------------------------

Stage 3 starts only after the question type is stable enough to justify dedicated implementation.

At this stage the route keeps the same external contract but swaps a generic executor for a specialized one, for example:

- dedicated SQL query;
- curated lookup table;
- cached resolver;
- direct API method;
- pre-ranked mapping;
- small route-specific script.

This stage exists to improve:

- latency;
- correctness;
- boundedness;
- reproducibility;
- resistance to malformed LLM arguments.

Examples:

- `curated_categories_by_sphere`
  - stage 1 or 2: generic tool call with canonical `sphere`
  - stage 3: direct curated table lookup returning ordered categories

- `portfolio_projects_by_sphere`
  - stage 1: generic portfolio search with canonical `sphere`
  - stage 3: dedicated query with curated ordering and bounded examples

- `mountings_by_category`
  - stage 1: generic category-mounting lookup
  - stage 3: direct mapping query using canonical `category`

- `showcase_lamps_by_category`
  - stage 2: new leaf route with curated semantics
  - stage 3: dedicated showcase mapping table and fast executor

- `documents_by_lamp_name`
  - stage 2: new leaf route over document selectors
  - stage 3: direct lamp-to-document index or precomputed document map

- `sku_codes_lookup`
  - stage 1: generic resolver
  - stage 3: direct code index with exact and reverse lookup modes

How selection works without a brittle shortlist
-----------------------------------------------

The routing system should not create a hidden deterministic shortlist of exact leaf routes and then force the LLM to choose only among those leaves.

That would fail closed in the wrong place if the shortlist logic misses the correct route.

Instead, the selector should see a compact route tree built from a fixed family map.

Preferred production mode:

1. the prompt lists all active families;
2. for each family the prompt includes a short family description and a short list of visible leaf routes;
3. the selector returns both family and leaf route in one compact JSON response;
4. runtime validates the leaf route against the declared family and validates the arguments against the route-local schema.

Optional fallback mode:

- if a family becomes too large, runtime may run a second small in-family selection step;
- this second step should be exceptional, not the default path;
- the second step must operate only after the family is selected, not as a global flat reranking pass.

This solves the shortlist concern directly:

- there is no fragile Python shortlist of exact routes;
- the LLM still performs the semantic choice;
- the prompt remains compact because the first-class units are business families, not every raw route at once.

Target family map
-----------------

The following family map is the target baseline for the next routing wave.

### `company_info`

Purpose:
- general company facts;
- contact and legal information;
- certificates at the company level;
- description of business series from common company knowledge.

Initial leaf routes:
- `company_general`
- `series_description`

Likely future leaf routes:
- `company_contacts`
- `company_certification_info`
- `company_quality_info`

Primary source:
- company KB and source-scoped corp knowledge.

### `sphere_category_mapping`

Purpose:
- map sphere to curated display categories;
- optionally answer reverse category-to-sphere questions later if product traffic requires it.

Initial leaf routes:
- `curated_categories_by_sphere`

Possible future leaf routes:
- `spheres_by_category`

Primary source:
- curated sphere-category relation.

### `portfolio`

Purpose:
- show realized projects and examples tied to sphere or other stable business dimension.

Initial leaf routes:
- `portfolio_projects_by_sphere`

Possible future leaf routes:
- `portfolio_examples_by_series`
- `portfolio_examples_by_category`

Primary source:
- portfolio tables and curated project search logic.

### `mountings`

Purpose:
- show mountings and compatibility based on category or, later, based on series.

Initial leaf routes:
- `mountings_by_category`

Possible future leaf routes:
- `mounting_compatibility_by_series`

Primary source:
- category-to-mounting mapping and compatibility logic.

### `catalog`

Purpose:
- resolve catalog entities and later show representative lamps for a category.

Initial leaf routes:
- `catalog_entity_lookup`

Required future leaf routes:
- `showcase_lamps_by_category`

Possible future leaf routes:
- `catalog_filters_by_category`
- `lamp_examples_by_series`

Primary source:
- catalog entity data plus curated showcase mappings.

### `documents`

Purpose:
- return documents based on lamp naming rather than treating documents as an accidental side effect of generic catalog lookup.

Required initial leaf routes:
- `documents_by_lamp_name`

Possible future leaf routes:
- `passport_by_lamp_name`
- `certificate_by_lamp_name`
- `ies_by_lamp_name`

Primary source:
- document domain routes and lamp-document selectors.

### `codes_and_sku`

Purpose:
- resolve model names, articles, ETM codes, Oracle codes, and reverse lookup between them.

Required initial leaf routes:
- `sku_codes_lookup`

Possible future leaf routes:
- `sku_by_name`
- `lamp_by_external_code`

Primary source:
- exact code lookup and entity resolver data.

Route schema policy
-------------------

Every leaf route must have a narrow schema.

The schema should answer one question only:

- what arguments are genuinely required for this user question type?

It should not answer:

- what fields exist in the underlying generic tool?

Rules:

1. include only meaningful fields for the selected leaf route;
2. use `enum` for compact, stable business domains;
3. keep `additionalProperties: false`;
4. declare required fields explicitly;
5. keep locked arguments separate from user-extracted arguments;
6. prefer one route-local schema per leaf route, not one shared mega-schema.

Examples:

### `curated_categories_by_sphere`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "sphere": {
      "type": "string",
      "enum": ["РЖД", "Промышленное освещение", "Складские помещения"]
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 10,
      "default": 5
    }
  },
  "required": ["sphere"]
}
```

### `portfolio_projects_by_sphere`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "sphere": {
      "type": "string",
      "enum": ["РЖД", "Промышленное освещение", "Складские помещения"]
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 5,
      "default": 3
    }
  },
  "required": ["sphere"]
}
```

### `mountings_by_category`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "category": {
      "type": "string",
      "enum": ["LAD LED R500", "LAD LED R700 PROM", "NL Nova"]
    }
  },
  "required": ["category"]
}
```

### `showcase_lamps_by_category`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "category": {
      "type": "string",
      "enum": ["LAD LED R500", "LAD LED R700 PROM", "NL Nova"]
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 5,
      "default": 3
    }
  },
  "required": ["category"]
}
```

### `documents_by_lamp_name`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "name": {
      "type": "string",
      "maxLength": 240
    },
    "document_type": {
      "type": "string",
      "enum": ["passport", "certificate", "manual", "ies"]
    }
  },
  "required": ["name"]
}
```

### `sku_codes_lookup`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "name": {
      "type": "string",
      "maxLength": 240
    },
    "etm": {
      "type": "string",
      "maxLength": 80
    },
    "oracl": {
      "type": "string",
      "maxLength": 80
    },
    "lookup_mode": {
      "type": "string",
      "enum": ["by_name", "by_code", "reverse", "auto"]
    }
  }
}
```

### `series_description`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "series": {
      "type": "string",
      "enum": ["LAD LED R500", "LAD LED R700", "NL Nova", "NL VEGA"]
    },
    "query": {
      "type": "string",
      "maxLength": 240
    }
  }
}
```

Canonical domains and enums
---------------------------

This RFC keeps the RFC-026 direction and narrows it by route.

The system should use enums where the domain is compact and stable enough to help the selector.

Expected enum sources:

- `sphere`
  - canonical values from `db/spheres.json`

- `curated category`
  - ordered scoped values from the curated sphere-category relation
  - may be dynamic when the sphere is already resolved

- `mounting_type`
  - canonical values from `db/mounting_types.json` or equivalent route-owned source

- `series`
  - canonical business series from company knowledge

- `document_type`
  - small fixed internal vocabulary: `passport`, `certificate`, `manual`, `ies`

The system should not dump large domains into every selector prompt.

Specifically:

- all catalog models should not be global enums;
- all SKUs and codes should not be global enums;
- all categories across all spheres should not be global enums when the sphere is unknown.

Missing leaf routes required by this RFC
----------------------------------------

The following routes are required to align runtime behavior with the product question model.

1. `showcase_lamps_by_category`
   - Purpose: return representative lamps for a category.
   - Business behavior: show a small curated list, not an arbitrary search dump.
   - Example: for `R500`, default examples may prioritize one-module versions such as `R500-1`.
   - Expected stage-3 optimization: curated category showcase table.

2. `documents_by_lamp_name`
   - Purpose: return passports, certificates, manuals, or other documents by lamp name.
   - Business behavior: document retrieval is first-class, not incidental to generic entity lookup.

3. `sku_codes_lookup`
   - Purpose: resolve external codes and model names in both directions.
   - Business behavior: works for lamp name -> code and code -> lamp.

4. `series_description`
   - Purpose: describe a business series from company common knowledge.
   - Business behavior: broad series questions stay in general company information, not in catalog entity lookup.

Family-local fallback rules
---------------------------

Fallback must be bounded and mostly local to the selected family.

Examples:

- `series_description`
  - may fall back to `company_general` inside `company_info`
  - should not fall back to catalog entity lookup for broad series asks

- `curated_categories_by_sphere`
  - may use canonical alias resolution for `sphere`
  - should not fall into generic company fact or broad catalog routes

- `portfolio_projects_by_sphere`
  - may fall back to bounded sphere alias resolution or curated portfolio search inside `portfolio`
  - should not reopen a generic global loop

- `documents_by_lamp_name`
  - may retry with normalized lamp naming or document-type broadening inside `documents`
  - should not drift into unrelated company-level knowledge routes unless explicitly requested

Cross-family fallback should be rare and declared explicitly in route metadata.

Data model implications
-----------------------

This RFC does not require all stage-2 and stage-3 optimizations immediately, but it does identify the likely supporting data structures.

Already aligned with this RFC:

- curated sphere categories;
- category hierarchy metadata;
- canonical spheres;
- canonical business series.

Additional structures likely needed:

1. curated showcase lamps by category
   - example table: `corp.category_showcase_lamps`
   - fields may include:
     - `category_id`
     - `lamp_id`
     - `position`
     - `is_primary`
     - `source_hash`

2. lamp-to-document selectors
   - can begin as route metadata or a document manifest;
   - may later become a compact index.

3. direct code lookup index
   - may stay inside current tables initially;
   - may later get a route-specific fast resolver.

4. route analytics inventory
   - explicit mapping of family -> leaf route -> executor -> owning tests and replay cases.

Observability model
-------------------

Routing evolution must be measurable.

Every request should emit at least:

- `selected_route_family`
- `selected_route_id`
- `route_stage` (`stage1_general`, `stage2_specialized`, `stage3_optimized`)
- `route_selector_status`
- `route_selector_confidence`
- `route_arg_validation_status`
- `route_fallback_family_count`
- `route_fallback_leaf_count`
- `route_executor_kind`

Recommended counters and histograms:

- `retrieval_route_family_requests_total`
- `retrieval_route_leaf_requests_total`
- `retrieval_route_leaf_errors_total`
- `retrieval_route_leaf_duration_ms`
- `retrieval_route_argument_validation_errors_total`
- `retrieval_route_family_fallback_total`
- `retrieval_route_low_confidence_total`
- `retrieval_route_stage_total`

A route should only be promoted from stage 1 to stage 2, or from stage 2 to stage 3, when observability shows clear benefit.

Error handling and UX
---------------------

The routing UX should remain simple even as internals evolve.

1. unresolved canonical value
   - If the family is clear but a required canonical field is missing or ambiguous, runtime may:
     - apply bounded alias resolution;
     - ask one focused clarification question;
     - or return a bounded failure response.

2. route-local empty result
   - Empty results should close quickly.
   - The system should not re-enter a broad unrelated tool loop.

3. selector uncertainty
   - Low-confidence family selection may still execute if one family clearly dominates.
   - If confidence is too low and multiple families are plausible, runtime may ask a short clarification.

4. executor failure
   - Runtime should return a bounded route-specific message.
   - Failures should be visible in traces with family and route identifiers.

Migration from current route model
----------------------------------

The current route catalog should evolve rather than be replaced all at once.

Near-term mapping:

- `corp_kb.company_common`
  - target family: `company_info`
  - target leafs: `company_general`, `series_description`, later `company_contacts`, `company_certification_info`

- `corp_db.sphere_curated_categories`
  - target family: `sphere_category_mapping`
  - target leaf: `curated_categories_by_sphere`

- `corp_db.portfolio_by_sphere`
  - target family: `portfolio`
  - target leaf: `portfolio_projects_by_sphere`

- `corp_db.category_mountings`
  - target family: `mountings`
  - target leaf: `mountings_by_category`

- `corp_db.catalog_lookup`
  - target family: `catalog`
  - transitional leaf: `catalog_entity_lookup`

- `corp_db.category_lamps` plus future curated example logic
  - target family: `catalog`
  - target leaf: `showcase_lamps_by_category`

- document-domain routes and document selectors
  - target family: `documents`
  - target leaf: `documents_by_lamp_name`

- `corp_db.sku_lookup`
  - target family: `codes_and_sku`
  - target leaf: `sku_codes_lookup`

Implementation considerations
-----------------------------

The implementation should minimize production risk.

1. preserve current route cards during transition;
2. add family metadata explicitly rather than infer it at runtime from scattered heuristics;
3. introduce leaf-route aliases or wrappers before deleting old route identities;
4. keep replay-based validation for known incident prompts;
5. do not promote a route to stage 3 until the stage-2 semantics are stable.

The transition should not require a flag day.

A route may exist in transitional form:

- old route id preserved for compatibility;
- new family and leaf metadata added for selector and observability;
- executor gradually specialized later.

Implementation outline
----------------------

Phase 1: Introduce hierarchical route metadata

- Add `selected_family_id` to selector contracts and observability.
- Add family cards and family-local leaf grouping to route metadata.
- Stop presenting the runtime selector with a flat all-visible leaf list in normal production mode.
- Keep one-call selection as the default: family plus leaf plus args in one response.

Phase 2: Narrow schemas for existing routes

- Reduce `company_info`-like schemas to only fields relevant to that route.
- Reduce sphere, portfolio, mounting, and SKU route schemas to their real arguments.
- Ensure every leaf route uses `additionalProperties: false`.
- Keep compact canonical enums only where the business domain is small.

Phase 3: Materialize missing stage-2 leaf routes

- Add `series_description` under `company_info`.
- Add `documents_by_lamp_name` under `documents`.
- Add `sku_codes_lookup` under `codes_and_sku`.
- Add `showcase_lamps_by_category` under `catalog`.

Phase 4: Align data sources with stage-2 routes

- Define curated source of truth for showcase lamps by category.
- Tighten document selectors for lamp-document lookup.
- Define reverse code lookup behavior and argument modes.

Phase 5: Promote hot routes to stage 3

- Add dedicated executors for the most error-prone and high-traffic routes.
- Keep route contracts stable while optimizing implementation.
- Add replay and latency budgets per optimized route.

Testing approach
----------------

Unit tests

- family selection validation;
- family-to-leaf membership validation;
- route-local schema validation;
- canonical enum injection by route;
- leaf-route fallback boundaries;
- broad series routing to `series_description`;
- document lookup routing to `documents_by_lamp_name`;
- code reverse lookup routing to `sku_codes_lookup`.

Integration tests

- `РЖД` category selection -> `curated_categories_by_sphere`;
- `РЖД` projects -> `portfolio_projects_by_sphere`;
- category mounting question -> `mountings_by_category`;
- lamp passport request -> `documents_by_lamp_name`;
- lamp code request -> `sku_codes_lookup`;
- broad series request -> `series_description`.

Replay and smoke tests

- add goldens for each family and each required new leaf route;
- assert no drift from broad series into catalog entity routes;
- assert no drift from documents into generic company fact answers;
- assert route-local empty closes without unrelated fallback loops.

Manual tests

- `Какие у вас есть серии светильников?`
- `Опиши серию NL Nova`
- `Какие категории подходят для РЖД?`
- `Какие есть реализованные проекты для РЖД?`
- `Какие крепления доступны для категории R500?`
- `Покажи примеры светильников для категории R500`
- `Покажи паспорт на NL Nova`
- `Какой ETM-код у NL Nova?`
- `Что это за модель по коду ...?`

Future-proofing
---------------

This RFC intentionally separates concerns so the system can grow without another routing rewrite.

Future expansions should fit naturally into the hierarchy:

- new leaf routes can be added inside existing families;
- a family can be split only when traffic proves a truly new domain;
- a stage-2 route can become stage 3 without changing the selector contract;
- route-specific scripts can coexist with generic search modes during migration.

The key long-term rule is:

- do not flatten everything back into one selector pool.

Acceptance criteria
-------------------

1. Production route selection uses explicit route families and leaf routes rather than one flat all-visible leaf catalog.
2. The default production path keeps the LLM as the primary selector and does not depend on a brittle deterministic shortlist of exact leaf routes.
3. Every active leaf route exposes a route-local schema with `additionalProperties: false` and only the arguments meaningful for that route.
4. Broad series questions route to `company_info/series_description` or its accepted alias, not to catalog entity lookup.
5. Sphere-driven category questions route to `sphere_category_mapping/curated_categories_by_sphere` with canonical sphere values.
6. Sphere-driven portfolio questions route to `portfolio/portfolio_projects_by_sphere` with canonical sphere values.
7. Category mounting questions route to `mountings/mountings_by_category` with category-scoped arguments.
8. Document questions by lamp name route to `documents/documents_by_lamp_name` or an accepted subtype route.
9. Code and article questions route to `codes_and_sku/sku_codes_lookup` or an accepted subtype route.
10. The catalog family contains a dedicated path for `showcase_lamps_by_category`, backed initially by a clear route contract and later by curated data.
11. Observability records both selected family and selected leaf route on every routed request.
12. The routing architecture supports the three product stages explicitly: broad routes first, specialized leaf routes next, optimized executors last.
