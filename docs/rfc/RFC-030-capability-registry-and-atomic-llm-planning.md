RFC-030 Capability Registry and Atomic LLM Planning
===================================================

Status
------

Proposed

Date
----

2026-08-31

Related RFCs
------------

- RFC-003 defined the structured and hybrid corporate DB search surface.
- RFC-016 separated retrieval completion from LLM answer finalization.
- RFC-018 introduced a unified catalog for table, script, and document execution paths.
- RFC-021 diagnosed excessive hard-coded orchestration and proposed an LLM-led runtime.
- RFC-025 made route cards and typed arguments the center of retrieval.
- RFC-027 introduced business families and leaf routes.
- RFC-028 made the catalog declarative and tried to collapse routing into one decision path.
- RFC-029 split route choice and argument construction into two LLM calls.

Decision summary
----------------

Replace the current production retrieval sequence

```text
Python intent ordering
  -> LLM route choice (Call A)
  -> LLM arguments for the already chosen route (Call B)
  -> route-specific execution
  -> evidence classification
  -> route fallback graph
  -> optional ReAct recovery
  -> answer finalizer
```

with a smaller capability-oriented sequence:

```text
hard security/access gate
  -> one atomic LLM plan: outcome OR capability + typed arguments
  -> one allowlisted deterministic executor/workflow
  -> one normalized result contract
  -> no-tools LLM answer finalizer when needed
```

The planner sees the capability description and its argument contract together. It chooses the capability and fills its arguments in the same structured-output operation. A capability represents a real business operation over a table, search domain, document domain, or reviewed multi-table workflow. It is not a storage-independent intent label and it is not one node in a fallback graph.

Known multi-table questions are implemented as registered deterministic workflows. Corporate retrieval never falls back into the general ReAct loop. General workspace/tool tasks may still use the ReAct agent, but only after the top-level planner explicitly delegates to that separate capability class.

Context and motivation
----------------------

The current system has strong data and a strong model:

- normalized Postgres tables for lamps, documents, codes, categories, mountings, spheres, portfolio, and knowledge chunks;
- structured filters for the normalized lamp fields;
- exact lookups and stage-3 optimized executors;
- hybrid FTS, trigram, and semantic search over `corp.corp_search_docs`;
- compact canonical enums for series, spheres, mounting types, document types, and other stable domains;
- `gpt-5.6-terra` in the verified production path.

Despite this, routing remains the main source of regressions. The 2026-08-31 production verification exposed two representative failures:

1. `LAD LED R500 2Ex` with `flux_lm_min=11540` selected `corp_db.catalog_lookup` / `lamp_exact` instead of `corp_db.lamp_filters`.
2. simple company-fact requests intermittently selected or fell back to `corp_kb.series_description`, causing website, foundation year, address, or contact facts to disappear.

These failures are not evidence that the model cannot understand the questions. They show that the runtime gives different decision stages different fragments of the information and then lets several layers reinterpret the result.

The current implementation is substantial for a 22-visible-route catalog:

- `core/agent.py`: 4,603 lines;
- `core/documents/routing.py`: 2,390 lines;
- `core/documents/route_schema.py`: 1,087 lines;
- `core/documents/routing_policy.py`: 393 lines;
- route YAML and JSON Schema files: about 1,816 lines.

The active selector payload measured on the rebuilt stack is also revealing:

- full internal payload: about 149 KB of JSON;
- compact Call-A payload: about 7.1 KB;
- Call-A messages: about 7.9 KB.

The Call-A prompt is compact because it intentionally excludes argument schemas. That optimization also removes information needed to distinguish routes whose main difference is their argument shape.

Problem statement
-----------------

The current architecture has the wrong unit of routing and too many owners of semantic interpretation.

### 1. A leaf route is often smaller than the real capability

Several routes are alternative modes over the same data domain rather than distinct user capabilities.

Examples:

- `catalog_lookup`, `lamp_filters`, and parts of `category_lamps` all operate on the lamp catalog;
- `company_common` and `series_description` query the same `knowledge_route_id`, source file, and hybrid-search backend;
- document subtype routes all execute the same lamp-document index with a different `document_type`;
- SKU lookup directions execute one code-index capability.

Splitting one data capability into neighboring leaf routes forces the model to classify a storage mode before it can supply the values that reveal which mode is appropriate.

### 2. Route choice and arguments are artificially separated

RFC-029 Call A sees only:

- `route_id`;
- `family_id`;
- title;
- `when_to_use`.

Call B sees the chosen route's argument schema, but cannot change the route.

For the R500 2Ex incident, the most important evidence is structural:

- the user supplied a canonical `series`;
- the user supplied a numeric lower bound `flux_lm_min`;
- `lamp_filters` accepts both fields;
- `catalog_lookup` requires an exact `name`.

Call A does not see that contrast. Once it picks `catalog_lookup`, Call B cannot correct the choice. A stronger model cannot recover information that the contract deliberately withholds from the decision where it matters.

### 3. Deterministic pre-ordering remains a hidden router

Even when all visible routes fit in the selector budget, `build_route_selector_payload()` computes an `intent_family` through Python keyword logic and orders all cards by that inferred intent. The 2026-08-31 verification commit changed catalog-order presentation to `all_visible_ranked_by_intent` to reduce one regression.

This is a useful local mitigation, but it proves that route order is behaviorally significant. The LLM is not choosing from a neutral registry; it receives a list already shaped by a second classifier.

### 4. The same question is interpreted repeatedly

Company questions currently pass through overlapping mechanisms:

- Python company-fact subtype detection;
- Python facet detection;
- Call-A route selection;
- Call-B query/facet construction;
- a special company query expansion in `_route_execution_args()`;
- company payload relevance helpers;
- generic evidence classification;
- fallback from `company_common` to `series_description` and back.

The current comments correctly describe several of these as narrow exceptions. The accumulated result is still a multi-owner decision system.

### 5. Fallback graphs compensate for over-split capabilities

`company_common` and `series_description` are mutual fallbacks even though they use the same source and executor. Document subtype routes fall back to their broad sibling. Catalog and code routes need cross-family declarations to recover from selection errors.

A fallback edge is appropriate when an external dependency fails over to a genuinely different source. It is not the right way to select another mode of the same table operation.

### 6. Evidence policy is a second semantic router

After the planner has chosen and executed a route, runtime code decides whether the result is `sufficient`, `weak`, `intermediate`, `empty`, or `error`. Route-specific branches can then launch controlled fallbacks or reopen the main agent loop.

This means a successful typed executor is not authoritative about whether it answered its own contract. The orchestration layer interprets business meaning again.

### 7. The retrieval selector is mandatory for non-retrieval messages

The current catalog has no first-class outcomes for:

- small talk;
- questions about the assistant itself;
- out-of-scope questions;
- blocked requests;
- approved workspace/tool tasks.

Consequently, a request such as `Как дела?` still receives a corporate route catalog and must choose one of the database routes. On the measured stack its first candidates begin with application recommendation and catalog lookup. This is a category error, not a route-ranking problem.

### 8. The ReAct loop remains an implicit recovery system

The system prompt says the primary route has already run, then lets the main agent choose from a routing shortlist if bounded fallbacks did not produce sufficient evidence. Guardrails are needed to stop it from browsing raw files, repeating authoritative KB calls, or leaving the selected source.

This is the behavior RFC-021 and RFC-028 intended to remove. The general agent loop should not be a retrieval fallback engine.

Root cause
----------

The root cause is not insufficient model intelligence. It is **semantic authority fragmentation**:

- one layer classifies intent;
- another chooses a route without seeing its full shape;
- another fills arguments but cannot revise the route;
- another rewrites arguments;
- another judges evidence;
- another follows fallback edges;
- another agent may try additional tools;
- a finalizer writes the answer.

Each layer is locally reasonable. Together they create information loss, duplicated interpretation, and nondeterministic seams.

The second root cause is **modeling storage modes as separate semantic routes**. A user does not distinguish `lamp_exact` from `lamp_filters`; the user asks the catalog capability for a lamp or lamps under constraints. Exact, filtered, and hybrid access are execution modes of that capability.

Goals
-----

- Make one component authoritative for semantic planning.
- Let the planner see capability descriptions and typed arguments together.
- Align capabilities with real table/search/workflow boundaries.
- Reduce the visible corporate capability set from many overlapping leaf routes to a smaller set of distinct business operations.
- Keep structured filters, enums, hybrid search, optimized SQL, and read-only security boundaries.
- Represent small talk, out-of-scope requests, blocked requests, clarification, and approved workspace-agent delegation as first-class outcomes.
- Keep multi-table logic in reviewed backend workflows, not in free-form LLM tool loops.
- Make an executor authoritative for its own result status.
- Prevent corporate retrieval from falling into the general ReAct loop.
- Keep final user wording natural and evidence-grounded through a narrow no-tools finalizer call.
- Make new capabilities easy to add through one registry row/spec, one schema, one executor, and tests.
- Net-delete routing-specific Python branches and state.

Non-goals for v1
----------------

- Generating SQL with an LLM.
- Giving the planner arbitrary script paths, tool names, URLs, or table names.
- Removing deterministic access, security, permission, schema, or output validation.
- Removing the general ReAct agent for approved workspace operations.
- Supporting arbitrary unbounded multi-capability plans in the first release.
- Replacing the existing Postgres schema or hybrid-search implementation.
- Migrating all executors in one flag-day change.
- Weakening current golden facts, links, or filter-argument expectations to hide regressions.

Design principles
-----------------

### Capability, not route

A capability is a stable, allowlisted business operation with:

- a clear user-facing purpose;
- one typed input schema;
- one registered executor or workflow;
- declared data sources/table scopes;
- one normalized result contract.

A capability may choose exact, structured, or hybrid access internally. Those are not separate top-level routing decisions unless they expose materially different user semantics.

### One atomic semantic decision

The planner chooses the capability and fills its arguments in the same structured-output operation. It must see the fields and compact enums that determine fit.

### Deterministic execution after planning

After a plan validates, runtime does not reinterpret the user's meaning. It executes the named allowlisted handler with validated arguments.

### Backend workflows own multi-table behavior

A stable multi-table task gets a named workflow capability. The workflow performs joins and bounded subqueries itself. The LLM supplies parameters, not orchestration steps.

### Hard security stays outside the LLM

Access control, prompt-injection detection, blocked command patterns, permissions, path restrictions, DB read-only enforcement, and output sanitization run before or around planning. The LLM may classify benign out-of-scope requests, but it is not the security boundary.

### No hidden fallback router

An executor may use deterministic recovery inside its own capability, such as normalized exact match followed by bounded hybrid match. Runtime does not traverse a graph of unrelated capabilities after execution.

### No-tools finalization

The answer finalizer receives only the user request, normalized capability result, and concise answer policy. It has no tools and cannot reopen retrieval.

Target high-level behavior
--------------------------

### Step 0: deterministic ingress policy

Before any LLM call:

1. enforce access mode and per-session tool permissions;
2. detect blocked/prompt-injection patterns;
3. handle explicit bot/admin commands;
4. reject known destructive or secret-exfiltration requests;
5. normalize transport wrappers without rewriting business meaning.

A hard-blocked request returns the configured blocked response and records a security event. It never reaches the planner or DB.

### Step 1: atomic planner

The planner receives:

- current user message;
- a short dialog digest for follow-ups;
- a compact capability registry;
- each capability's selector-visible typed signature and compact enums;
- the allowed non-retrieval outcomes.

It returns exactly one discriminated action:

```json
{
  "action": "execute_capability",
  "capability_id": "catalog_lamps.search",
  "arguments": {
    "series": "LAD LED R500 2Ex",
    "flux_lm_min": 11540
  }
}
```

or, for example:

```json
{"action": "smalltalk"}
```

```json
{"action": "out_of_scope", "topic": "weather"}
```

```json
{
  "action": "clarify",
  "question": "Уточните, вам нужны проекты для РЖД или категории светильников для РЖД?"
}
```

```json
{
  "action": "delegate_workspace_agent",
  "task_summary": "Inspect the user's repository status"
}
```

The planner cannot return SQL, shell, file paths, executor names, evidence overrides, or arbitrary scripts.

### Step 2: schema validation and canonicalization

Runtime:

- verifies that `capability_id` is active and allowed for the session;
- validates arguments against that capability's JSON Schema;
- applies locked/default arguments;
- resolves declared canonical aliases and enums;
- rejects unknown fields;
- permits at most one schema-local repair call if structured output is invalid.

Canonicalization may normalize an explicit alias such as `R500 2Ex` to `LAD LED R500 2Ex`. It must not infer a different business capability.

### Step 3: deterministic capability execution

The registered executor runs once. It may contain bounded deterministic substeps within its contract.

Examples:

- catalog search: exact match, structured filter query, or bounded hybrid retrieval depending on validated arguments;
- knowledge search: source-scoped hybrid search using the original query and selected domain/facets;
- document lookup: one bounded batch query for the requested names and document type;
- recommendation workflow: sphere/category resolution, lamp ranking, and portfolio enrichment across reviewed tables.

### Step 4: normalized result contract

Every capability returns:

```json
{
  "status": "success",
  "capability_id": "catalog_lamps.search",
  "data": [],
  "facts": [],
  "links": [],
  "citations": [],
  "clarification": null,
  "diagnostics": {
    "execution_mode": "structured_filters",
    "row_count": 3
  }
}
```

Allowed statuses are:

- `success` — the executor completed its declared contract and returned answerable data;
- `empty` — no matching data exists under the validated request;
- `needs_clarification` — the capability is correct, but a required business value is ambiguous or absent;
- `error` — execution failed.

The executor owns this status. The agent layer does not run a second route-specific relevance classifier.

### Step 5: response

- `blocked`, `smalltalk`, and simple `out_of_scope` outcomes use reviewed concise templates and do not call the DB.
- `clarify` returns the focused planner/executor clarification.
- `success`, `empty`, and recoverable `error` normally go to a no-tools finalizer LLM.
- The finalizer cannot call tools or change the capability result. It only writes the user-facing response.
- If the finalizer is unavailable, runtime uses a bounded deterministic renderer over the normalized result contract.

Capability registry
-------------------

### Source layout

Proposed source-of-truth layout:

```text
core/capabilities/
  registry.yaml
  index.md
  company_knowledge/
    search.yaml
    search.schema.json
    search.result.schema.json
  catalog_lamps/
    search.yaml
    search.schema.json
    search.result.schema.json
  workflows/
    application_recommendation.yaml
    application_recommendation.schema.json
    application_recommendation.result.schema.json
```

`registry.yaml` is the compact machine index. Each capability file contains the reviewed details.

### Capability contract

Required fields:

```yaml
capability_id: catalog_lamps.search
kind: table_query
title: Catalog lamp search
when_to_use: >-
  Find one or more lamp models by exact name, canonical series, structured
  technical filters, category, or an approximate product description.
examples:
  positive:
    - "Покажи LAD LED R500 2Ex от 11540 лм"
    - "Найди NL Nova 120"
    - "Светильники IP65 до 100 Вт"
  negative:
    - "Чем серия R500 отличается от R700?"
data_sources:
  tables:
    - corp.catalog_lamps
    - corp.catalog_series_families
  search_index:
    - corp.corp_search_docs
executor_ref: tools_api.corp_db.catalog_lamps_search
schema_ref: search.schema.json
result_schema_ref: search.result.schema.json
answer_policy: product_facts
security_class: corporate_read_only
```

Optional fields:

- `docs_ref` — human/operator documentation;
- `implementation_ref` — registered handler or workflow module;
- `canonical_catalogs` — enum sources refreshed at build/runtime;
- `latency_budget_ms`;
- `owner`;
- `deprecation_aliases` for old route IDs;
- `availability` by session type;
- `hybrid_search_policy`;
- `result_examples`.

`executor_ref` is resolved through an internal allowlist. It is not an arbitrary import path or script path supplied by the LLM.

### What the planner sees

The planner sees only:

- `capability_id`;
- title;
- short `when_to_use`;
- a small number of positive/negative examples;
- a compact argument signature;
- compact enums that materially affect choice.

It does not see:

- SQL;
- filesystem paths;
- implementation code;
- fallback graphs;
- observability labels;
- retry internals;
- raw table credentials;
- result-ranking internals.

The capability and argument contract are still presented together. For providers with reliable function calling, each capability is exposed as one function and the model chooses exactly one function with arguments. Otherwise runtime compiles the registry into one discriminated-union JSON Schema.

Initial capability map
----------------------

The first implementation should deliberately consolidate current routes. The exact final names are subject to implementation review, but the target shape is:

| Capability | Primary data | Replaces or absorbs |
|---|---|---|
| `company_knowledge.search` | `knowledge_chunks`, `corp_search_docs` | `company_common`, `series_description`, `lighting_norms`, `luxnet` as one source-scoped search capability with a compact `domain` enum |
| `catalog_lamps.search` | `catalog_lamps`, `categories`, `catalog_series_families`, hybrid index | exact catalog lookup, lamp filters, category lamp listing, representative examples as modes/fields of one catalog capability where semantics overlap |
| `catalog_documents.lookup` | `catalog_lamp_documents`, `catalog_lamps` | broad and subtype document routes using `names[]` and optional `document_type` |
| `catalog_codes.lookup` | `etm_oracl_catalog_sku`, `catalog_lamps` | forward and reverse SKU/ETM/ORACL/article routes |
| `mountings.lookup` | `mounting_types`, `category_mountings` | available mounting options and named compatibility checks using optional typed fields |
| `sphere_categories.lookup` | `spheres`, `sphere_curated_categories`, `categories` | curated category-by-sphere lookup; diagnostics-only full mapping remains hidden from planner |
| `portfolio.search` | `portfolio`, `spheres`, hybrid index | named object and sphere portfolio lookup, distinguished by arguments rather than neighboring routes |
| `application_recommendation.run` | reviewed multi-table workflow | current recommendation script over spheres, curated categories, lamps, and portfolio |
| `document_corpus.search` | concrete indexed document domains | explicit search inside known documents; not a generic corporate fallback |
| `workspace_agent.delegate` | session-permitted non-corporate tools | explicit entry into the existing ReAct agent for repository/sandbox work, never a corporate retrieval fallback |

This map reduces semantic choices while preserving specialized executors behind the capability boundary.

### Example: catalog capability

A single catalog capability can use a schema such as:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "query": {"type": "string", "maxLength": 500},
    "name": {"type": "string", "maxLength": 240},
    "series": {"type": "string", "enum": ["LAD LED R500", "LAD LED R500 2Ex", "NL Nova"]},
    "category": {"type": "string", "maxLength": 160},
    "ip": {"type": "string", "maxLength": 8},
    "power_w_min": {"type": "integer", "minimum": 1, "maximum": 2000},
    "power_w_max": {"type": "integer", "minimum": 1, "maximum": 2000},
    "flux_lm_min": {"type": "integer", "minimum": 1, "maximum": 500000},
    "flux_lm_max": {"type": "integer", "minimum": 1, "maximum": 500000},
    "limit": {"type": "integer", "minimum": 1, "maximum": 10}
  }
}
```

The backend selects execution mode deterministically:

- exact `name` with no filters -> exact lookup;
- any structured filter -> structured filter query;
- approximate `query` without sufficient exact fields -> hybrid search;
- category plus `examples_only=true` -> optimized showcase path.

For the R500 2Ex incident, there is no competition between `catalog_lookup` and `lamp_filters`. The planner chooses `catalog_lamps.search` and supplies `series` plus `flux_lm_min`; the executor naturally uses the structured-filter path.

### Example: company knowledge capability

`company_knowledge.search` uses one source-scoped hybrid capability with arguments such as:

- `domain`: `company_common|lighting_norms|luxnet`;
- `query`: the user's natural question or a concise LLM-produced retrieval query;
- `facets`: compact optional enum list;
- `series`: optional canonical series enum where relevant.

`series_description` is not a separate capability from company common knowledge when both use the same source file and backend. Series is an argument/facet of the capability.

If natural conversational wording performs poorly in hybrid search, fix search normalization, indexing, or ranking in the executor. Do not introduce another Python router-side query rewrite for individual fact subtypes.

Multi-table and complex questions
---------------------------------

### Known repeated complex task

Create one workflow capability.

Example:

```text
application_recommendation.run
  -> resolve sphere/application profile
  -> fetch curated categories
  -> expand executable categories
  -> rank catalog lamps
  -> fetch bounded portfolio evidence
  -> return one normalized result
```

The planner only supplies typed parameters such as `application_key`, `context_profile`, protection requirements, and limits.

### New complex task

Add a capability only when the execution semantics are genuinely new.

Decision rule:

1. If the existing capability and schema already express the request, add an example and regression test; do not add a new capability.
2. If the same table capability needs another filter field, extend its schema and executor.
3. If the request requires a stable join/workflow over several sources, add a reviewed workflow capability and handler.
4. If the request needs a new source of truth, add a new capability owned by that source.
5. If the request is out of product scope, add or refine an out-of-scope example/policy, not a DB route.

This avoids turning every production wording into another leaf route or Python keyword branch.

### Arbitrary compound requests

V1 keeps one planner action per turn. If a user asks several independent questions, the planner either:

- chooses an existing workflow capability that covers the compound business task; or
- asks the user to split or prioritize the request.

A bounded `actions[1..3]` plan may be evaluated later, but it should not be introduced until traffic shows that one-action planning is insufficient. This keeps execution and error semantics simple.

Non-retrieval outcomes
----------------------

The planner contract includes explicit non-DB outcomes.

| User request | Outcome | DB/tool calls |
|---|---|---:|
| `Как дела?` | `smalltalk` | 0 |
| `Кто ты и чем можешь помочь?` | `self_description` | 0 |
| `Какая погода в Москве?` | `out_of_scope` | 0 |
| `Удали все данные из БД` | deterministic security/permission block | 0 |
| ambiguous corporate ask | `clarify` | 0 |
| approved repository/sandbox task | `delegate_workspace_agent` | only session-allowed general tools after delegation |

Small talk and out-of-scope responses should be concise reviewed templates. The planner identifies the benign category; security validators handle dangerous requests before planning.

LLM decomposition decision
--------------------------

The system should not create four independent long-lived agents for routing, arguments, DB execution, and answer writing.

### Recommended stages

1. **Planner LLM call**
   - isolated compact context;
   - capability choice and arguments together;
   - no general tools;
   - strict structured output;
   - one repair maximum.

2. **Deterministic executor/workflow**
   - no LLM for known SQL/filter/join behavior;
   - typed input and result schemas;
   - read-only and bounded.

3. **Finalizer LLM call**
   - isolated context containing only the user request, normalized result, and answer policy;
   - no tools;
   - no route catalog;
   - no ability to reopen retrieval.

4. **General ReAct agent**
   - separate capability used only for approved workspace/tool tasks;
   - never entered because corporate retrieval was empty or weak.

### Why not separate route and argument agents

The R500 2Ex failure demonstrates the cost: route choice needs the argument shape to judge the route correctly. Separating them removes useful information and prevents correction.

### Why not an LLM DB-query agent

The allowed tables, joins, filters, and hybrid modes are known. An LLM-generated SQL or free-form query plan adds risk without adding useful flexibility. The LLM should fill typed business parameters; backend code should execute them.

### Why keep a separate finalizer call

Answer synthesis and capability selection need different context:

- planning needs compact capability contracts;
- finalization needs evidence and style policy;
- combining them would either expose broad tools after evidence is ready or force evidence into the planner context.

A finalizer is a stateless no-tools LLM call, not another autonomous agent.

Security model
--------------

The proposal preserves the existing layered security model.

### Before planning

- access mode and allowlist checks;
- bot/core prompt-injection checks;
- blocked patterns;
- message size/rate limits;
- explicit command handling.

### At planning validation

- action and capability allowlist;
- JSON Schema validation;
- locked args applied last;
- no arbitrary executor/script/path/tool fields;
- capability availability filtered by session type;
- maximum string, array, numeric, and plan-size bounds.

### At execution

- read-only DB credentials;
- parameterized SQL only;
- fixed executor registry;
- bounded limits/timeouts;
- no planner-provided SQL or shell;
- workflow-specific resource budgets.

### At output

- normalized result schema;
- source/citation preservation;
- secret and encoded-output sanitizer;
- finalizer has no tools and cannot expose hidden implementation fields.

Fallback and error policy
-------------------------

### Allowed internal fallback

A capability may perform bounded deterministic recovery inside its own data contract.

Examples:

- normalized exact name -> exact prefix/series match -> bounded hybrid candidate search;
- canonical enum match -> approved alias resolution;
- lexical hybrid result -> semantic fallback inside the same source scope;
- multi-name document batch where one name is absent but others succeed.

These are executor implementation details and appear as `diagnostics.execution_strategy`, not new semantic route choices.

### Disallowed global fallback

Runtime does not automatically switch from one business capability to another after `empty` or `error`.

- `empty` -> answer no data or ask a capability-local clarification;
- `needs_clarification` -> ask exactly that question;
- `error` -> bounded service error;
- suspected planner mismatch -> log for replay; do not launch a hidden route graph.

A future one-time replan may be evaluated only with explicit telemetry proving it improves quality without recreating the current architecture.

Observability
-------------

Canonical fields become:

- `planner_action`;
- `capability_id`;
- `capability_version`;
- `planner_model`;
- `planner_latency_ms`;
- `planner_prompt_chars`;
- `planner_repair_status`;
- `capability_arg_validation_status`;
- `capability_arg_keys`;
- `executor_ref`;
- `executor_strategy` (`exact|structured|hybrid|workflow|direct`);
- `table_scopes`;
- `result_status`;
- `result_row_count`;
- `finalizer_mode`;
- `finalizer_latency_ms`;
- `db_call_count`;
- `workspace_agent_delegated`.

Fields such as `selected_family_id`, fallback route counts, fallback scope, route-stage, evidence grade, and guardrail attempts become migration-only compatibility telemetry and are deleted after cutover.

Required dashboards/reports:

- per-capability selection accuracy;
- first-pass argument validity;
- result-status distribution;
- planner and finalizer p50/p95;
- zero-DB compliance for non-retrieval outcomes;
- capability confusion matrix;
- repeated-run stability for production-agent cases;
- cost per capability and per completed answer.

Registry lifecycle
------------------

### Build and validation

CI validates:

- unique capability IDs;
- valid input and result JSON Schemas;
- executor references resolve to the allowlist;
- table/search scopes are declared;
- enum sources exist and remain below configured prompt budgets;
- every capability has positive and negative examples;
- every capability has unit, integration, and benchmark ownership metadata;
- no planner-visible arbitrary paths or executor internals;
- compiled planner contract stays within the prompt-size budget.

### Adding support for a new request

The operator classifies the failure before changing the registry:

| Failure type | Correct change |
|---|---|
| existing capability selected, argument missing | improve capability schema/hints/example or canonical enum |
| wrong capability selected despite schema fit | improve compact `when_to_use` and contrastive examples |
| existing executor cannot express requested filter | add field and backend support to that capability |
| stable multi-table task | add workflow capability and deterministic handler |
| poor hybrid result | fix index/search/ranking in executor |
| out-of-scope request hit DB | add/clarify non-retrieval outcome examples |
| malicious request reached planner | fix deterministic ingress policy |

Do not add Python keyword branches as the default response to traffic.

Migration plan
--------------

### Phase 0: baseline and shadow artifacts

1. Freeze the current production-agent, RFC-028, Ex/2Ex, and direct-tool gates.
2. Add repeated-run stability reporting, not only one-run accuracy.
3. Generate an inventory mapping every current route to tables, executor modes, schema fields, fallback edges, and golden cases.
4. Record current planner/finalizer latency, tokens, and cost.

### Phase 1: capability registry in shadow mode

1. Add `core/capabilities/` and registry validation.
2. Define the initial consolidated capability set.
3. Compile it into an atomic planner contract.
4. Run the new planner in shadow mode beside the existing router without executing it.
5. Compare capability choice and arguments against current goldens and real traces.

### Phase 2: first low-risk capabilities

Migrate capabilities with clear table contracts first:

- catalog documents;
- codes/SKU;
- mountings;
- sphere curated categories.

Expose both:

- new `capability_id`;
- compatibility `legacy_route_id` derived from validated arguments/result mode.

This allows current strict route goldens to stay active during migration.

### Phase 3: catalog consolidation

1. Introduce `catalog_lamps.search` over exact, structured, category, and hybrid modes.
2. Make execution mode deterministic from validated arguments.
3. Remove route competition between `catalog_lookup` and `lamp_filters`.
4. Verify the complete Ex/2Ex incident dataset and all technical filter cases.

### Phase 4: knowledge consolidation

1. Introduce `company_knowledge.search` with `domain`, `facets`, `query`, and optional `series`.
2. Remove `company_common` <-> `series_description` fallback semantics.
3. Remove company subtype query rewriting from agent orchestration.
4. Improve hybrid search/index behavior for natural questions where necessary.
5. Verify repeated company-fact runs, not one lucky 26-case run.

### Phase 5: workflows and finalization

1. Register application recommendation and other stable multi-table flows as workflow capabilities.
2. Normalize result contracts.
3. Route successful results directly to a no-tools finalizer.
4. Remove corporate retrieval entry into the ReAct loop.
5. Keep ReAct only behind explicit `delegate_workspace_agent`.

### Phase 6: remove compatibility architecture

After full gate success:

- delete Python intent pre-ordering from production planning;
- delete route/argument split calls;
- delete fallback graph traversal;
- delete route-specific evidence classifiers from agent orchestration;
- delete company-fact subtype/query rewriting used for routing;
- delete routing shortlist injection into the general agent prompt;
- delete migration-only route telemetry;
- retain declarative schemas, executor validation, security, and benchmark aliases only as long as consumers require them.

Rollout and rollback
--------------------

Use a runtime mode boundary:

- `routing_v2=current_routes`;
- `routing_v3=capability_planner_shadow`;
- `routing_v3=capability_planner_canary`;
- `routing_v3=capability_planner_primary`.

Canary by admin/test users first. Every request records both old route prediction and new capability prediction while shadow mode is active.

Rollback changes only the planner mode. Executors remain the same reviewed APIs during early phases, so rollback does not require a DB migration.

Testing approach
----------------

### Unit tests

- registry and schema validation;
- capability/action allowlist;
- planner output validation and one repair limit;
- canonical enum injection;
- non-retrieval outcomes produce zero DB calls;
- exact/structured/hybrid executor mode selection;
- normalized result contracts;
- finalizer cannot call tools;
- workspace-agent delegation is explicit and permission-filtered.

### Deterministic contract tests

- every capability executes directly with fixed arguments and fake dependencies;
- all normalized lamp filter fields remain supported;
- workflow capabilities query only declared tables/handlers;
- security blocks occur before planner/executor invocation.

### Planner tests with fake LLM

- scripted atomic capability + arguments;
- invalid capability;
- unknown args;
- locked arg override;
- repair success/failure;
- smalltalk/out-of-scope/clarify/delegate outcomes.

### Production E2E

Required cases include:

- `LAD LED R500 2Ex` with `flux_lm_min=11540` -> `catalog_lamps.search`, structured strategy, canonical series and numeric filter;
- exact model facts -> same capability, exact strategy;
- approximate product ask -> same capability, hybrid strategy;
- company website/year/address/contacts -> `company_knowledge.search`, no series fallback;
- series comparison -> `company_knowledge.search` with series-aware arguments;
- certificates for several series -> `catalog_documents.lookup` with bounded `names[]`;
- application recommendation -> one workflow capability;
- `Как дела?` -> smalltalk and zero DB calls;
- weather -> out-of-scope and zero DB calls;
- destructive DB request -> deterministic block and zero planner/DB calls;
- approved git/repository task -> explicit workspace-agent delegation.

### Stability gate

A single passing run is insufficient for stochastic production E2E.

Before primary rollout:

- RFC-028/compatibility routing baseline: 100%;
- Ex/2Ex runtime replay: 100%;
- production-agent suite: 100% in at least three consecutive full runs on the pinned model;
- no variation of company-fact failures between runs;
- configured and provider-reported model pins match;
- no weakening of facts, links, or filter arguments;
- zero DB calls for every non-retrieval benchmark case.

Performance and cost budgets
----------------------------

The capability planner should replace Call A + Call B, not add a third call.

Initial budgets:

- planner calls per corporate request: 1 normally, 2 only after invalid structured output;
- planner prompt: target <= 20 KB for the initial consolidated registry;
- finalizer calls: 1 for retrieved answers, 0 for reviewed direct outcomes;
- no general agent-loop call for corporate retrieval;
- planner p95 no worse than current Call A + Call B aggregate p95;
- total production-agent p95 and tokens no worse than the verified pre-migration baseline, with a target improvement from removing fallback and ReAct iterations.

Alternatives considered
-----------------------

### Continue patching route descriptions and order

Rejected as the primary strategy. It can improve individual cases, but leaves split semantic authority, schema information loss, fallback graphs, and non-retrieval misclassification intact.

### Keep two LLM calls but let Call B reselect the route

Rejected. This creates negotiation or looping between two planners and makes ownership less clear. One atomic typed choice is simpler.

### One full ReAct agent with all tools and the whole registry

Rejected for corporate retrieval. It increases context, permits route drift after evidence is sufficient, requires more guardrails, and makes cost/latency less bounded. ReAct remains useful for open-ended workspace tasks after explicit delegation.

### Fully deterministic keyword classifier

Rejected. It recreates the current accumulation of language-specific branches and will not generalize to new phrasing. Deterministic code validates and executes; the LLM performs semantic mapping.

### Four specialized autonomous agents

Rejected for v1. Independent router, argument, DB, and answer agents duplicate context and create handoff errors. The selected design uses two narrow stateless LLM calls around a deterministic executor, not four autonomous agents.

Risks and mitigations
---------------------

### Consolidated schemas become too large

Mitigations:

- consolidate only semantically overlapping modes;
- use compact signatures for the planner, full schemas for runtime validation;
- include compact enums only where useful;
- keep large free-text domains out of enums;
- enforce prompt budgets in CI.

### A broad capability hides executor complexity

Mitigations:

- keep executor strategy explicit in diagnostics;
- maintain focused direct-tool tests per strategy;
- split a capability only when user semantics and input contract are genuinely different, not merely because SQL paths differ.

### One wrong capability no longer has automatic cross-family fallback

This is intentional. Hidden fallback masks planner errors and creates incorrect answers. Use replay evidence to improve the planner contract; use clarification for ambiguity; allow deterministic recovery only inside the selected capability.

### Compatibility route IDs change

During migration, emit both `capability_id` and a derived `legacy_route_id`. Version the benchmark contract only after the new architecture is accepted and all factual/argument assertions remain strict.

Acceptance criteria
-------------------

1. Production corporate planning uses one atomic structured-output call that chooses a capability and supplies its arguments together.
2. The planner sees the selector-visible argument shape and compact enums of each candidate capability.
3. Route choice and argument construction are no longer separate LLM calls in the primary capability-planner path.
4. The initial visible capability set is consolidated around real table/search/workflow boundaries and contains materially fewer overlapping choices than the current 22 visible routes.
5. R500 2Ex plus `flux_lm_min=11540` selects one catalog capability and executes its structured-filter strategy with the canonical series and numeric bound.
6. Company facts and series knowledge no longer depend on mutually falling back leaf routes over the same source file.
7. Runtime contains no production Python keyword classifier that reorders or overrides the capability planner's semantic choice.
8. Agent orchestration does not rewrite capability arguments after validation except declared canonicalization and locked/default args.
9. Every capability has one registered executor/workflow and one normalized result schema.
10. The executor's `success|empty|needs_clarification|error` status is authoritative; agent orchestration does not apply a second route-specific evidence grader.
11. Corporate retrieval never enters the general ReAct loop after capability execution.
12. The answer finalizer has no tools and cannot reopen retrieval.
13. Small talk, self-description, out-of-scope, clarification, blocked request, and workspace-agent delegation are explicit top-level outcomes.
14. Small talk, weather, and blocked destructive DB requests execute zero corporate DB calls; hard-blocked requests execute zero planner calls as well.
15. Stable multi-table tasks execute through registered bounded workflow capabilities rather than LLM-generated tool sequences.
16. Capability schemas preserve structured filters and compact canonical enums; hybrid search remains available for approximate or similarity-oriented requests.
17. New request support follows the registry lifecycle: example/schema/executor/workflow/policy changes are chosen by failure type instead of defaulting to Python keyword patches.
18. Current deterministic and factual goldens are not weakened; compatibility route IDs remain available during migration.
19. RFC-028 baseline, Ex/2Ex runtime replay, and production-agent gates pass 100%, with the production-agent suite passing at least three consecutive full pinned-model runs.
20. Routing-related Python and runtime state are net-reduced after compatibility cleanup, with removed split-call, fallback-graph, evidence-grading, and retrieval-ReAct machinery documented in the final migration report.
