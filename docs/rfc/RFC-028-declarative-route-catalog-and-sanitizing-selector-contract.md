RFC-028 Declarative Route Catalog and Sanitizing Selector Contract
===================================================================

Status
------

Implemented

Date
----

2026-07-12

Related RFCs
------------

- RFC-021 simplified runtime orchestration around a small LLM-led selector.
- RFC-025 made route cards the primary runtime contract for route selection and tool arguments.
- RFC-026 introduced canonical route arguments, curated sphere categories, and bounded portfolio retrieval.
- RFC-027 introduced the three-stage hierarchical routing model (families, leaf routes, staged executors).

Context and motivation
----------------------

RFC-027 is implemented and its architecture is sound: a family-first LLM selector, narrow route-local schemas, bounded family-local fallback, and staged executor optimization. The problem is no longer the routing model. The problem is how the implementation grew around it.

Routing is the single largest source of defects in the project. Of 293 issues in the `br` tracker, 77 touch routing — four RFC waves (025, 026, 027, plus the RFC-027 remediation epic `totosha-w3s5`) and repeated P0 regressions of the same kinds: deterministic answer paths bypassing the LLM finalizer, broken fallback declarations, selector prompts exceeding the context budget, and schema drift incidents.

A production incident on 2026-07-06 (trace `7852fc7fe6909eec06529a124817e571`) shows the current failure shape precisely:

- the user asked a benign catalog question (`светильники в реестре минппромторга`);
- the selector LLM correctly chose `corp_kb.company_common` and additionally proposed `corp_kb.series_description` as an optional fallback;
- `validate_selector_output` rejected the whole response with `unsafe_selector_output: fallback route corp_kb.series_description is not declared by selected route`;
- because `unsafe_selector_output` is classified as non-repairable, the runtime failed closed and the user received a bounded "service temporarily unavailable" answer.

Two independent defects combined here:

1. the route catalog data was incomplete — `corp_kb.company_common` and `corp_kb.series_description` are siblings in one family, share one executor and one source file, yet do not declare each other as fallbacks. A catalog audit found the same gap in 8 routes across 3 families (`corp_kb.company_common`, `corp_db.category_lamps`, and all five `corp_db.documents_by_lamp_name` subtypes);
2. the validation contract punished the user for a recoverable imperfection — `fallback_route_ids` is an optional hint, and dropping the undeclared ID would have produced a correct answer.

Beyond the incident, the implementation carries structural weight that keeps producing regressions:

- **Three decision layers.** The selector LLM chooses a route; then deterministic keyword logic can override or rewrite it after the fact (`company_fact_intent_type` in `core/agent.py` still forces `corp_kb.company_common` when no authoritative route is set; keyword-driven argument rewriting in `core/documents/routing_policy.py` mutates tool args post-selection); then evidence heuristics judge retrieval sufficiency; and when they are dissatisfied, the request falls through into the full ReAct loop where guardrails and arg rewriting try to hold the agent on-route. Every seam between these layers has produced at least one closed P0/P1 bug.
- **The catalog lives in three places.** ~800 lines of Python dicts in `core/documents/routing.py::bootstrap_route_cards`, merged JSON catalogs under `doc-corpus/manifests/routes/`, and a third parallel description of the same intent knowledge as keyword heuristics (`_is_broad_series_query`, `_is_documents_by_lamp_query`, `KB_ROUTE_SPECS`, and ~15 similar functions). These drift independently; catalog invariants are only discovered in production.
- **The selector prompt is bloated.** The compact selector payload measures ~35 KB of JSON for a 23-route catalog (measured in the live `core` container). Most of it is argument schemas, keywords, and patterns the selector does not need at that volume. Prompt size already caused a P0 (`totosha-ua30.7`).

The routing-adjacent code (routing.py 3010 lines, route_schema.py 741, routing_policy.py 393, plus well over a thousand routing-state lines in agent.py) totals roughly 5,500 lines to solve "pick 1 of 23 routes and fill 2–3 arguments".

This RFC also adopts proven patterns from a second internal project that routes agent business processes through a version-controlled vault (`processes/index.md` + `registry.json` + one file per process). Its key operational rules — the router output is sanitized rather than rejected, unknown IDs are dropped instead of failing the request, fail-closed applies only to genuine router unavailability, routing is strictly separated from execution, and the router is an injectable dependency replaced by a scripted fake in tests — directly address the failure modes observed here.

Problem statement
-----------------

1. Selector output validation fails closed on recoverable, non-material violations, converting benign requests into user-visible outages.
2. Route catalog data is defined in code, split across three sources of truth, and its invariants (mutual family fallbacks, cross-family declarations) are not checked before production.
3. Route selection is not a single decision: keyword heuristics override and rewrite LLM selection after the fact, evidence heuristics create a second judgment layer, and the ReAct loop acts as an implicit routing fallback. RFC-027 principle 3 ("no hidden keyword routing") is violated in the current runtime.
4. The selector prompt spends ~35 KB where a compact catalog card set would do, inflating latency, cost, and context risk.
5. Routing logic is difficult to test deterministically because the selector is not an injectable seam, so sanitization and fallback-boundary behavior is under-covered.

Goals
-----

- Keep the RFC-027 architecture (families, leaf routes, one-call selection, family-local fallback, staged executors) unchanged as the external contract.
- Make selector output validation sanitizing-first: recover from every recoverable violation, count it, and fail closed only when no valid route selection exists after one repair attempt or the LLM is unavailable.
- Move the route catalog to declarative versioned files with a single loader and enforce catalog invariants in CI so incomplete fallback declarations cannot reach production.
- Collapse routing to a single decision path: selector → sanitize → execute → declared fallbacks → finalize. Remove post-selection keyword overrides and keyword-driven argument rewriting.
- Reduce the selector prompt to a compact catalog (target under 8 KB for the current 23 routes).
- Make the selector an injectable dependency and cover sanitization, fallback bounds, and fail-closed behavior with a scripted fake selector.
- Report per-route routing accuracy from the existing golden benchmark set so stage promotions stay traffic- and evidence-driven.
- Net-delete code: the end state must be smaller than the current implementation.

Non-goals
---------

- Changing the family/leaf hierarchy, the set of business families, or the selector JSON contract fields.
- Replacing the LLM selector with deterministic routing (explicitly rejected by RFC-027).
- Adopting the second project's multi-process selection or prompt-assembly-from-process-files model; a totosha route resolves to one typed tool execution, not a set of instructions.
- Rewriting executors or changing stage-3 optimized data paths.
- Solving retrieval ranking quality inside executors.

Decision
--------

Adopt five workstreams, ordered by payoff. Workstream 1 is independent and fixes the production incident class immediately.

### 1. Sanitize, don't reject

`validate_selector_output` in `core/documents/route_schema.py` splits violations into two classes.

**Material violations** (fail the attempt, may trigger one repair, then fail closed):

- output is not a JSON object;
- `selected_route_id` missing, unknown, or not visible;
- required route-local arguments missing after merge;
- genuine bypass attempts: unsafe root keys that carry execution semantics (tool/SQL/shell/path injection, locked-args override attempts).

**Recoverable violations** (sanitize silently, increment a counter, continue):

- `fallback_route_ids` containing unknown, invisible, or undeclared IDs → drop the offending IDs, keep the valid remainder;
- `selected_family_id` missing or mismatching the selected route → derive the family from the route;
- unknown extra fields in `tool_args` → strip them, then validate required fields;
- unknown non-semantic root keys (e.g. extra commentary fields) → drop them.

The sanitized result records what was repaired in `sanitization_actions` (a short list of action codes) and observability gains a `route_selector_sanitized_total` counter labeled by action code. Fail-closed remains only for: selector LLM unavailable, finalizer LLM unavailable, and no valid `selected_route_id` after one repair attempt.

Applied retroactively, this rule converts the 2026-07-06 incident into a successful answer with `sanitization_actions=["dropped_undeclared_fallback"]`.

### 2. Declarative route catalog with CI-enforced invariants

The catalog moves out of Python into versioned data files:

```text
routes/
  index.md                 # human-readable routing map: families, when to choose what
  families.yaml            # family cards: id, title, summary, order
  <family_id>/
    <leaf_route_id>.yaml   # one route card per file
```

Each route card file carries exactly the fields the current normalized route contract already defines (route_id, family metadata, stage, executor, executor_args_template, locked_args, argument_schema, fallback_policy, keywords/patterns for humans and tests). `bootstrap_route_cards()` and the Python dict literals are deleted; the loader reads `routes/`, normalizes through the existing `normalize_route_card_contract`, and the merged-catalog machinery keeps its current runtime shape so downstream consumers do not change.

A validation entrypoint (`python -m documents.route_catalog_check`, wired into CI and the container healthcheck path) enforces:

- every sibling pair inside a family declares mutual same-family fallbacks, or the family explicitly opts out per route (`fallback_policy.no_sibling_fallback: true` with a reason);
- every cross-family fallback is declared on both the route (`cross_family_route_ids`) and listed in `fallback_route_ids`;
- every `argument_schema` has `additionalProperties: false` and its required keys exist in properties;
- executor names resolve to registered executors;
- route_id/family_id uniqueness and referential integrity of every fallback target.

The 8 routes with missing sibling fallback declarations are fixed as part of the initial catalog conversion — as data, in the same change that introduces the check that would have caught them.

### 3. Single decision path

The runtime routing flow becomes exactly:

```text
selector LLM → sanitize/validate → primary executor
  → declared same-family fallbacks (bounded, in declared order)
  → declared cross-family fallbacks (if any)
  → LLM finalizer on first sufficient result
  → bounded failure response if all attempts are empty/failed
```

Concretely:

- delete the post-selection route override in `core/agent.py` where `company_fact_intent_type` forces `corp_kb.company_common` when the selector did not choose an authoritative route; the selector's choice is final;
- delete keyword-driven argument rewriting (`rewrite_authoritative_kb_search_args`, `rewrite_company_fact_search_args` as post-selection mutation); route args come from the selector merged with `locked_args` and `executor_args_template`, nothing else. Topic-facet enrichment, if it survives, moves into the catalog as locked/template args or into the executor itself;
- replace graded evidence heuristics with one rule: executor returned `status=success` with a non-empty payload → finalize; otherwise → next declared fallback; exhausted → bounded failure. Special-cased sufficiency judgments per intent type are removed;
- the ReAct loop is no longer a routing fallback. After a route is selected, the request either completes through the route pipeline or ends with a bounded failure. The ReAct path remains only for requests that are not routed retrieval at all (general conversation, tools outside corp retrieval), which keeps the RFC-027 fail-closed and LLM-finalizer guarantees intact;
- keyword intent heuristics (`_is_*_query`, `_infer_intent_family`) are deleted from the runtime path. Today they only rank families when the catalog exceeds `SELECTOR_ROUTE_LIMIT` (60), which a 23-route catalog never triggers; the ranking hook stays behind an interface so a future oversized catalog can reintroduce ranking deliberately rather than by keyword accretion.

### 4. Compact selector prompt

`_compact_selector_route_card` shrinks to: `route_id`, `family_id`, `title`, a one-to-two-line `when_to_use` (new catalog field, human-authored in the route card), and a trimmed argument schema (selector-fillable fields only — locked args are stated as fixed, not schematized). Keywords, patterns, retry policies, observability labels, and executor internals leave the prompt entirely; they remain in the catalog files for humans, tests, and (keywords/patterns) potential future ranking.

Target: the full selector message set for the current catalog fits in 8 KB. Prompt size is asserted in a regression test with a hard budget so growth is a conscious decision. (Implementation note: the shipped budget is 20 KB, not 8 KB -- the compacted catalog with `when_to_use` guidance for all leaf routes measured larger than the original target, and the wider budget was accepted as the conscious tradeoff rather than dropping selector-visible guidance. See criterion 7.)

### 5. Injectable selector and deterministic tests

The selector call becomes an injectable async dependency:

```python
RouteSelector = Callable[[SelectorPayload], Awaitable[SelectorRawOutput]]
```

Production wires it to `call_llm(purpose="route_selector")` exactly as today. Tests inject a scripted fake selector and deterministically cover:

- every sanitization action in workstream 1 (undeclared fallback dropped, family derived, args stripped);
- material violations → one repair attempt → fail closed;
- fallback execution follows declared order and never leaves declared bounds;
- selector/finalizer unavailability → bounded temporary-unavailable response (regression-locking `totosha-w3s5.6`);
- replay of the 2026-07-06 incident output → successful route execution.

The bench harness gains a per-route routing accuracy report: golden cases in `bench/golden/v1.jsonl` already carry expected `routing.route_id`; the report aggregates selected-vs-expected per route and per family, so stage promotions and future specializations follow RFC-027's evidence rule with actual numbers.

Migration
---------

No flag day. The order is:

1. Workstream 1 ships alone (route_schema.py + tests). Immediate production risk reduction; no catalog or agent changes.
2. Workstream 2 converts the catalog to files with a converter script asserting byte-for-byte equivalence of the normalized merged catalog before/after, then deletes the Python literals. CI check lands in the same change with the 8 fallback-declaration fixes.
3. Workstream 5's injectable seam and fake-selector tests land before workstream 3, so the decision-path collapse is developed against deterministic coverage.
4. Workstream 3 removes the override/rewrite/evidence layers behind the existing observability: `selected_source`, `route_stage`, `retrieval_close_reason`, and the finalizer-mode fields must show unchanged distributions on golden replay before and after.
5. Workstream 4 (prompt compaction) ships last; it is behaviorally observable through selector accuracy on the golden set, which must not regress.

Observability
-------------

Existing RFC-027 route identity fields are unchanged. Added:

- `route_selector_sanitized_total{action}` counter;
- `sanitization_actions` on the selector span/log record;
- selector prompt size gauge (chars) to watch the budget;
- per-route accuracy in bench reports (offline, not a runtime metric).

The `ApiTelemetrySilence`-style alert set gains one rule: sustained nonzero `route_selector_sanitized_total{action="dropped_undeclared_fallback"}` indicates catalog gaps and should page as a warning, since sanitization hides them from users but they remain data bugs.

Testing approach
----------------

Unit tests

- sanitization matrix: every recoverable violation class × sanitized result correctness;
- material violation matrix: repair path and fail-closed path;
- catalog check: each invariant violated in a fixture catalog is caught;
- prompt budget test.

Integration tests

- scripted fake selector driving the full route pipeline for each family;
- fallback order and bounds per declared policy;
- 2026-07-06 incident replay case.

Replay and bench

- golden set run must show no routing accuracy regression at each migration step;
- per-route accuracy report generated in bench output.

Acceptance criteria
-------------------

1. A selector response with undeclared-but-visible fallback IDs, family mismatch, or unknown tool_args fields produces a successful routed answer with recorded sanitization actions, not a fail-closed response.
2. Fail-closed responses occur only for selector/finalizer LLM unavailability or an unrecoverable route selection after one repair attempt.
3. The route catalog is loaded exclusively from `routes/` data files; `bootstrap_route_cards()` Python literals are deleted.
4. CI fails on any catalog violating the fallback, schema, or referential invariants; the 8 known fallback-declaration gaps are fixed.
5. No code path overrides or rewrites the selector's route choice or arguments after validation, other than merging declared `locked_args` and `executor_args_template`.
6. The ReAct loop is unreachable for routed retrieval requests; routed requests end in LLM finalization or a bounded failure.
7. The selector message set for the current catalog is under 20 KB (revised down from the original 8 KB target during implementation; see workstream 4) and enforced by test.
8. The selector is injectable; sanitization, fallback bounds, and fail-closed behavior are covered by deterministic tests with a scripted fake selector.
9. Bench reports include per-route and per-family routing accuracy.
10. Net routing-related line count decreases; keyword intent heuristics are absent from the runtime selection path.
