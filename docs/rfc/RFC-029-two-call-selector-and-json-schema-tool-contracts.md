RFC-029 Two-Call Selector and JSON-Schema Tool Contracts
=========================================================

Status
------

Proposed

Date
----

2026-07-13

Related RFCs
------------

- RFC-025 made route cards the primary runtime contract for route selection and tool arguments.
- RFC-026 introduced canonical route arguments and curated sphere categories.
- RFC-027 introduced the three-stage hierarchical routing model (families, leaf routes, staged executors) and rejected deterministic routing in favor of a single LLM-led selector call.
- RFC-028 made the route catalog declarative, made selector output sanitizing instead of rejecting, and decided (workstream 4) that keywords and patterns should leave the selector prompt entirely, staying in the catalog files only for humans and tests.

This RFC keeps every RFC-027/028 external contract (families, leaf routes, one route resolves to one typed tool execution, declarative catalog, sanitizing validation, bounded fallback) unchanged. It narrows one thing RFC-028 did not fully finish, and splits one oversized decision into two smaller ones. It does not reopen RFC-028's non-goal: a route still resolves to exactly one typed tool execution, not a set of assembled process instructions.

Context and motivation
-----------------------

RFC-028 workstream 4 decided: "Keywords, patterns, retry policies, observability labels, and executor internals leave the prompt entirely; they remain in the catalog files for humans, tests, and (keywords/patterns) potential future ranking." That decision was not fully carried out. `_compact_selector_route_card` (`core/documents/routing.py:2083-2165`) still ships `keywords` (up to 16) and `patterns` (up to 8) per route into the selector prompt today. The catalog has 23 routes, comfortably under `SELECTOR_ROUTE_LIMIT` (60), so this is not a size accident — it is unfinished workstream-4 cleanup.

Two incidents from 2026-07-13 show the cost of shipping keywords to the selector alongside a route's typed contract, and of resolving one route's arguments in the same call that resolves which route to use:

1. **Certificate query, wrong route** (bench case `sales-001-certificates-links`). The query names three different lamp series and asks for three different certificate links. `corp_db.certificate_by_lamp_name`'s card carries `keywords: ["сертификат", "сертификаты", ...]` and an `argument_schema` of `{name: string}` (one name). The selector chose it anyway, with reasoning that translates to "the certificate route matches best; the full wording is passed through for processing" — the keyword match outweighed the schema's single-name shape, and the route's own `name: string` field cannot represent three names. The request only succeeded after this session added a cross-family fallback edge to `corp_kb.company_common`; the selector's first choice was still wrong.
2. **Street-pole query, hallucinated argument** (trace `010ab7c4fd2846a9a3025a77e9b12d3c`, "покажи светильник на столб на высотку 4 метра"). The selector picked `corp_db.lamp_filters` and filled `mounting_type: "консольное"` — a value the user never stated — because `lamp_filters`'s `argument_hints.mounting_type` invites free-text extraction in the same call that has to decide the route is even relevant. The structured filter then legitimately returned empty, and the user got a flat "can't help."

Both incidents share one shape: **one LLM call is asked to both classify intent among 23 routes (using keyword/pattern signal) and fill that route's typed arguments (inventing values when the query underspecifies them)**. Keyword signal correctly belongs to classification; it has no business being visible at the point arguments are filled, and argument-filling has no business happening in the same turn as the 23-way classification.

A third, adjacent finding (same day, `tools-api/src/routes/corp_db.py`): `application_recommendation`'s sphere resolution (`APPLICATION_PROFILES`, `_resolve_application`, `_synonym_application_score`) re-implements free-text query understanding in Python — alias lists, a hand-rolled Russian suffix stemmer (`_application_stem`), substring scoring — entirely inside the executor, duplicating semantic work the selector LLM already did to pick the route in the first place. This is why a query for "светильник на столб для дачи" ranked a 1000 W industrial floodlight first: the executor's scoring function had no branch differentiating compact/residential from heavy-duty for the new `street_road_lighting` profile, and even after adding one, matching "дача"/"компактный" required discovering which Russian stems the hand-rolled stemmer actually produces for 4-letter words — fragile, untestable-by-inspection, and orthogonal to routing. RFC-028 explicitly put executor internals out of scope for itself; this RFC treats it as the same underlying defect (semantic understanding pushed into the wrong layer) and proposes the same fix (a typed, selector-fillable argument) rather than an executor rewrite.

Problem statement
-----------------

1. Keyword/pattern signal, meant only for classification, still reaches the selector at argument-filling time because classification and argument-filling are the same LLM call — RFC-028 workstream 4 decided to remove keywords/patterns from the prompt but the removal was not completed.
2. One call filling both `selected_route_id` and that route's `tool_args` lets a strong topical (keyword) match for the route override a poor structural fit (argument shape) for the query, and lets the model invent argument values instead of leaving them unset.
3. Routes whose real-world queries can name more than one entity (certificates, documents by lamp name) have single-value argument schemas (`name: string`), so a materially correct route choice still produces an empty result for multi-entity queries; today's fix for this is cross-family fallback wiring, which is recovery-after-failure rather than a schema that models the actual shape of the request.
4. At least one executor (`application_recommendation`) re-implements free-text semantic matching in Python (alias lists, a custom stemmer) to compensate for a routing/argument layer that did not carry a structured field for the distinction the executor needs — duplicating the selector's own job and doing it less reliably.
5. Route argument schemas are embedded in YAML route cards, hand-typed alongside prose fields (`title`, `summary`, `keywords`). YAML's implicit typing (unquoted `yes`/`no`/`on`/`off` as booleans, ambiguous numeric-looking strings, no native `additionalProperties`/`enum` semantics) is the wrong format for the one field in a route card that is validated and executed, not just read by a human.

Goals
-----

- Keep RFC-027's family/leaf-route hierarchy, single-route-resolves-to-one-typed-tool-execution contract, and RFC-028's declarative catalog, sanitizing validation, and bounded fallback pipeline unchanged.
- Actually finish RFC-028 workstream 4: keywords and patterns leave the selector prompt at classification time too, not only at argument time.
- Split the one existing selector call into two narrower, purpose-built calls: **route selection** (which route, from a keyword-free classification card) and **argument construction** (fill exactly that route's own JSON Schema, nothing else visible).
- Give routes whose real queries can name multiple entities an array-shaped argument (bounded length) instead of relying on fallback recovery to paper over a single-value schema.
- Replace free-text semantic matching inside executors with one additional selector-fillable, enum-typed argument field per executor that needs it, populated live from the database where the value set is closed (spheres, categories) — no new Python string-matching heuristics.
- Store every route's argument schema as a standalone JSON Schema file, validated with a standard validator both when building the LLM tool-call contract and when checking its output before execution.
- Net-simpler runtime: this RFC should delete more matching/scoring code (stemmer, alias scorer, keyword-driven argument extraction) than it adds (one extra small LLM call, JSON Schema files).

Non-goals
---------

- Changing the family/leaf hierarchy or introducing multi-route/multi-process composition. A resolved route still executes exactly one typed tool call (or, where the schema is array-shaped, one typed tool call over a bounded batch) — RFC-028's rejection of process-file assembly stands.
- Rewriting `application_recommendation` or any other executor's ranking/business logic beyond adding the one new selector-fillable argument field and reading it where the old heuristic used to guess.
- Changing the sanitizing-validation contract, fallback bounds, or fail-closed rules from RFC-028; the two-call split happens entirely inside the existing "selector LLM" step of RFC-028's single decision path.
- A new prompt-assembly-from-files mechanism; the classification card format from RFC-028 workstream 2 (`routes/index.md`, `families.yaml`, per-route YAML) is kept for human-facing fields (`title`, `summary`, `when_to_use`) — only the argument-schema fragment moves to JSON.
- Changing which model/provider is used; both calls use the same `call_llm` seam RFC-027/028 already established, just with two distinct `purpose` values and two distinct, narrower payloads.

Decision
--------

### 1. Finish RFC-028 workstream 4: keyword-free classification card

`_compact_selector_route_card` stops emitting `keywords` and `patterns` (currently `core/documents/routing.py:2083-2165`, the `keywords`/`patterns` fields at what are today lines ~2138-2139). The fields keep existing in the route's YAML file for humans and for the existing `_ordered_routes_for_degraded_selection` fallback path (used only when the LLM selector is unavailable), but never serialize into the selector-visible payload. The route card gains one new human-authored field, `when_to_use` (already anticipated by RFC-028 workstream 4 but not enforced): one to two sentences, in the same "when to select / why it applies" shape already used by `family_summary`. This is a data-only, low-risk change: no call-shape change, no schema change, verifiable purely by re-running the golden bench set and comparing routing accuracy before/after.

### 2. Split the selector call in two

**Call A — route selection** (`purpose="route_selector"`, unchanged from RFC-027/028 in spirit, narrowed in payload):

- Input: user message, dialog digest, sphere context, and the classification card set from workstream 1 above (`route_id`, `family_id`, `title`, `when_to_use` — no `keywords`, `patterns`, or `argument_schema`).
- Output (unchanged shape from RFC-028, still sanitized the same way): `selected_route_id`, `selected_family_id`, `fallback_route_ids` (validated against the declared catalog exactly as today).
- This call never sees any route's argument schema and therefore cannot invent argument values; RFC-028's sanitizing rules for `fallback_route_ids` and family mismatch are unchanged.

**Call B — argument construction** (new `purpose="route_argument_builder"`):

- Input: user message, dialog digest, and **only** the selected route's own JSON Schema (workstream 4 below) as the tool-calling contract (native structured output / strict JSON schema, so the model is constrained to that route's own properties and cannot emit fields another route would accept).
- Output: the route's `tool_args`, merged with `locked_args`/`executor_args_template` exactly as today, then validated against the same JSON Schema before execution (defense in depth: a schema violation here is a Call-B-local repair-or-fail-closed exactly like RFC-028's existing repair path, not a whole-catalog re-selection).
- If Call A's chosen route needs no selector-fillable arguments (a fully `locked_args` route), Call B is skipped entirely — no added latency for the routes that do not need it.

This keeps RFC-028's single decision path (`selector → sanitize → execute → declared fallbacks → finalize`) exactly as documented; "selector" is now two narrow sub-steps instead of one wide one, which is a refinement of workstream 3 ("single decision path"), not a reopening of it — there is still exactly one place arguments come from (Call B, merged with locked args), so RFC-028's "no code path overrides or rewrites the selector's arguments" acceptance criterion is preserved verbatim.

### 3. Array-shaped arguments where the domain is naturally multi-entity

`corp_db.certificate_by_lamp_name`, `corp_db.documents_by_lamp_name`, and their sibling document-subtype routes change `name: string` to `names: array<string>` (`minItems: 1`, `maxItems: 5` — five is generous headroom over every observed real query). The executor issues one query per name (parallel, bounded by the same array length) or a single `ANY($1)` query, whichever the executor already prefers; either way this is a same-shape extension of the existing SQL, not new retrieval logic. This removes the need for `corp_kb.company_common` to serve as a cross-family safety net for the common case of "certificates for N models in one message" — the safety net stays declared (RFC-028's sibling/cross-family fallback invariant still applies to the case a name genuinely does not resolve), but it stops being the primary mechanism for a request shape the schema can now represent directly.

### 4. JSON Schema files for argument contracts, YAML/Markdown for everything human-facing

Each route's argument schema moves out of the YAML route card into a standalone file:

```text
core/routes/<family_id>/<leaf_route_id>.yaml       # title, when_to_use, executor, locked_args, fallback_policy (human-authored, prose-heavy)
core/routes/<family_id>/<leaf_route_id>.schema.json # argument_schema only (machine-validated, executed)
```

The YAML file keeps a `schema_ref` pointing at its JSON file; the existing catalog loader reads both and merges them into the same in-memory route-card shape consumers already use, so `normalize_route_card_contract` and every downstream reader (executors, bench, observability) is unaffected. Only the boundary between "prose a human wrote" and "a contract a program executes" moves.

Reasoning for JSON over YAML for this one fragment only: `argument_schema` is exactly a JSON Schema object already (`type`, `properties`, `enum`, `required`, `additionalProperties`) — today it is YAML-encoded JSON Schema, which buys nothing and costs YAML's implicit-typing footguns (`no`/`yes`/`on`/`off` as booleans, bareword ambiguity, `-` list-item indentation errors silently reshaping a schema) on the one artifact where a silent type error is a security-relevant validation bug, not a formatting nit. Every LLM provider's structured-output/tool-calling contract is JSON Schema natively; keeping the file JSON removes a translation step between "what's on disk" and "what's sent to the model," and a standard `jsonschema` validator can check every file in CI with no custom YAML-to-schema normalization. Everything that stays prose (`title`, `when_to_use`, `family_summary`) stays exactly where it is today, because YAML has no disadvantage there.

### 5. One new selector-fillable field replaces `application_recommendation`'s free-text scoring

`corp_db.application_recommendation`'s schema gains one new enum property, `context_profile: ["residential_compact", "standard", "heavy_duty"]`, filled by Call B from the same query text a human reads (e.g. "дача", "компактный" → `residential_compact`; "трасса", "магистраль" → `heavy_duty`; otherwise `standard`). `tools-api`'s `_application_score_lamp` reads this field directly for its power-band scoring instead of re-deriving it from `_application_text_contains_any`/stemmed-term matching against the raw query inside the executor. `APPLICATION_PROFILES`'s `aliases`-based `_synonym_application_score` free-text matching is replaced the same way: `application_key` itself becomes a selector-fillable enum (`enum` populated at catalog-build time from `corp.spheres`/existing profile keys, refreshed the same way `canonical_series_names()` already refreshes the `name` enum for catalog routes), so Call B — which already reads the whole query in context — picks the sphere/profile directly instead of a Python scorer re-guessing it from keywords and stems. `_application_stem`, `_synonym_application_score`, and `_direct_application_score`'s free-text half are deleted; `_resolve_application_categories`'s DB-side category/fallback logic (the sphere→categories resolution, curated-category-with-zero-stock fallback) is untouched — that part was never guessing user intent, only looking up already-resolved data.

Migration
---------

No flag day; each workstream ships and is bench-verified independently, in this order:

1. Workstream 4 (JSON Schema files) ships first and is purely mechanical: a converter script extracts each route's `argument_schema` into its own `.schema.json`, asserts byte-for-byte equivalence of the merged in-memory catalog before/after (same technique RFC-028 workstream 2 used for its YAML conversion), then the loader is switched. No selector or executor behavior changes in this step.
2. Workstream 1 (strip keywords/patterns from the classification card, add `when_to_use`) ships next, verified by golden-set routing accuracy (bench `routing_only`/`algorithmic` modes) showing no regression versus the pre-change baseline captured the same day.
3. Workstream 2 (split Call A/Call B) ships behind the existing injectable-selector seam from RFC-028 workstream 5: a scripted fake for each call lets the split be tested deterministically before it takes live traffic. Golden-set replay must show routing accuracy and per-route argument-validity at or above the single-call baseline; latency budget (Call A + Call B, sequential) is checked against the current single-call P95 with a documented acceptable delta.
4. Workstream 3 (array-shaped document arguments) ships per affected route, each verified by its own bench regression case (the existing `sales-001-certificates-links` case becomes the regression lock for the certificate route specifically).
5. Workstream 5 (`context_profile`/`application_key` as selector-fillable enums, stemmer/alias-scorer deletion) ships last, gated on workstreams 2 and 4 both being live (it needs Call B's isolated argument-filling and the enum living in a JSON Schema `enum` list refreshed from the DB). The existing `street_road_lighting` power-band scoring becomes a straight lookup on `context_profile` instead of text matching.

Observability
-------------

- `route_selector_a_latency_ms` / `route_selector_b_latency_ms` split out from today's single `route_selector_latency_ms`, so the two-call cost is visible per stage, not just in aggregate.
- `route_argument_builder_status` (valid / repaired / fail_closed) alongside the existing `route_selector_status`, using the same sanitizing-vs-reject classification RFC-028 defined, scoped to Call B only.
- `application_recommendation` gains `context_profile` and `application_key` as observability labels (mirrors `knowledge_route_id` today), so the resolution path is visible in traces without reading tool output.
- Bench per-route accuracy (RFC-028 workstream 5) gains a second column: argument-validity rate (Call B output passing its JSON Schema on first attempt, no repair), so argument-construction quality is tracked as its own signal distinct from route-choice accuracy.

Testing approach
----------------

Unit tests

- classification card serialization: `keywords`/`patterns` fields are absent from the Call A payload for every route in the live catalog (regression-locks workstream 1 so it cannot silently drift back, the way RFC-028 workstream 4 did).
- JSON Schema files: every route's `.schema.json` validates as a legal JSON Schema (`additionalProperties: false`, required keys present in properties) — same invariant RFC-028's `route_catalog_check` already enforces, just checked against the new file location.
- scripted fake for Call A and a separate scripted fake for Call B, covering: route selected with no fillable arguments (Call B skipped), argument schema violation on Call B output (repair-then-fail-closed, scoped to Call B only, Call A's route choice is not re-run), array-argument routes with 1, 3 (typical), and 5 (max) names.
- `application_recommendation` context_profile: each of the three enum values produces the expected power-band scoring branch, replacing today's stemmed-keyword-matching unit tests.

Integration tests

- full pipeline replay of the 2026-07-13 `010ab7c4fd2846a9a3025a77e9b12d3c` (street pole) and `sales-001-certificates-links` (multi-model certificates) cases, both expected to resolve correctly without invoking cross-family fallback.
- golden-set run before/after each migration step (per RFC-028's own testing discipline) with routing accuracy and the new argument-validity metric both reported.

Acceptance criteria
--------------------

1. The Call A (route selection) payload contains no `keywords` or `patterns` field for any route in the live catalog.
2. Route selection and argument construction are two distinct LLM calls with two distinct, narrower payloads; Call B never receives another route's schema.
3. `corp_db.certificate_by_lamp_name` and `corp_db.documents_by_lamp_name` (and document subtypes) accept `names: array<string>` (1-5 items); the `sales-001-certificates-links` bench case passes without exercising cross-family fallback.
4. Every route's `argument_schema` lives in a standalone `.schema.json` file validated by a standard JSON Schema validator in CI; no route card YAML file contains an `argument_schema` key after migration.
5. `_application_stem` and `_synonym_application_score`'s free-text matching are deleted; `application_key` and `context_profile` are selector-fillable enum arguments, not Python-side text-matching outcomes.
6. No routing accuracy regression and no argument-validity regression on the golden bench set at any migration step, per RFC-028's existing replay discipline.
7. Net line count across `core/documents/routing.py` + `tools-api/src/routes/corp_db.py` decreases (stemmer/alias-scorer/keyword-serialization deletions outweigh the JSON Schema loader and second-call plumbing additions).
