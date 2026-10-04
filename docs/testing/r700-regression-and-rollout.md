# R700 search incident regression and rollout

Status: regression contract and rollout procedure recorded; production acceptance is **not
claimed** by this change. The running `core` and `tools-api` containers were built from images
whose IDs do not identify the current source revision, and the checked-in route tests currently
have two R700-series routing failures (details below). Do not use those containers as evidence
that the current source is deployed, and do not promote a production release until the gates in
this document pass.

## Incident baseline

The fixed historical evidence window is 2026-10-02T21:00:00Z through 2026-10-03T21:00:00Z
(2026-10-03 Moscow time): 52,827 VictoriaLogs records, seven chat traces, VictoriaMetrics,
and read-only SQL. Four of five relevant requests in the 20:59–21:02 Moscow-time chain ended
negatively despite HTTP 200 responses. The traces were:

| Intent | Trace |
|---|---|
| list five R700 models | `251fab7cd2ff2030a465591e6afff0a3` |
| describe R700 series | `2fb4d105a143b53c30bbcb61b5a39798` |
| R700 PROM models | `e3ef36e33c36eda77a887bf01a3b0a72` |
| projects/examples for PROM | `1fbf3e5f6ccb3c52a35ac09775799730` |
| contextual portfolio follow-up, “тогда с LAD LED R700” | `027c5c521863917005a155471a8d0a24` |

At investigation time, read-only SQL showed 709 lamps, 108 R700 names, 24 R700+PROM names,
zero exact rows named `R700`, `LAD LED R700`, or `LAD LED R700 PROM`, and 228 projects. The
140 projects reachable through category→sphere are category/sphere examples only, **not proof of
direct R700 model application**. These are incident observations, not fixed test constants.

## Regression contract

Replay the sequence in an isolated web session, preserving conversation context between turns:

1. `пока штук 5 светильнbков из серии r700` → list models (`corp_db.series_models`), canonical
   series `LAD LED R700`, `limit=5`.
2. `серия r700` → series knowledge (`corp_kb.series_description`), with evidence scoped to R700.
3. `светильники LAD LED R700 PROM` → `series_models`, canonical R700 plus PROM subfamily; all
   returned rows must be PROM and carry series evidence.
4. `объекты с LAD LED R700 PROM` → portfolio examples; results must identify provenance as
   `category_sphere_example` unless a real direct application relation is present.
5. `тогда с LAD LED R700` → retain portfolio intent, replace the entity/subfamily as requested,
   and do not repeat the prior business-empty search.

For every turn record selector choice, validated arguments/schema, executor result rows/status,
provenance/evidence, final answer, HTTP status, request ID, attempts, and end-to-end latency.
HTTP 200 or a keyword in the answer is never sufficient by itself. Catalog results must contain
at least the requested number of real matching rows where the fixture/data has them. Empty,
unknown-series, and unresolved-exact-model outcomes must be reported distinctly and honestly.

Deterministic regression data must include real-form SKUs, canonical series mappings, PROM/ST/HT,
R7000, unknown/empty series, exact SKU, and code lookup. Assert exclusions as well as inclusions:
PROM-only cannot include ST/HT; R700 cannot match R7000; exact model and code lookup must retain
their specialized paths. Keep production counts out of assertions.

## Local/CI verification

Run focused suites from a clean checkout in CI (the host Python environment may not have the
service dependencies installed):

```bash
# Core, in the built test image / CI environment
cd core && python -m unittest -q tests.test_routing_catalog tests.test_corp_db_tool

# Tools API, in its dependency environment
cd tools-api && python -m unittest discover -s tests -p 'test_corp_db.py' -q

# Existing bench contracts
python3 -m unittest -q \
  bench.tests.test_algorithmic_eval \
  bench.tests.test_routing_eval \
  bench.tests.test_run_modes
```

Source-aligned verification on 2026-10-04 (feature branch, before deployment):
`python3 -m unittest -q tests.test_routing_catalog tests.test_corp_db_tool` in `core/`
passed 69 tests after correcting the comparison-vs-model selector boundary in
`core/documents/routing.py`. `docker run --rm -v "$PWD/tools-api:/app" -w /app
--entrypoint python totosha-tools-api -m unittest discover -s tests -p test_corp_db.py -q`
passed 64 tests after restoring `category_id` in the empty portfolio response and fixing the
PROM-only fake connection. This uses the current mounted source with image dependencies, NOT the
running production container. Bench contract unit tests passed (24 tests). These results do not
establish CI, repeated-run LLM quality, source-aligned production deployment, or a five-turn
production smoke.

For LLM routing stability, use the existing RFC-030/repeated-run evaluation harness and freeze
provider/model, prompt/config revision, dataset version, temperature/sampling parameters, and
container build SHA. Run the held-out chain and negative cases repeatedly (minimum 10 runs per
case); report selection accuracy, argument validity/constraint preservation, evidence quality,
answer factuality, business-empty/attempts, p50/p95 latency, and failure rate separately. Gate on
zero PROM/ST/HT/R7000 or provenance violations and zero unsupported direct-application claims;
require all deterministic expected routes/arguments on every run. Attach machine-readable raw
results and a summary. Do not claim a repeated-run pass without the pinned configuration and
artifacts.

## Safe production rollout, smoke, and rollback

1. **Preflight:** run the CI gates above and repeated-run report; review diffs; freeze deployment
   SHA, image IDs, schema/data snapshot marker, and known-good image IDs. If any hard gate fails,
   stop before production.
2. **Deploy:** use the repository's normal guarded rollout, rebuilding the affected services from
   the reviewed SHA (at minimum `core`, `tools-api`, and any changed DB/migrator image). Record
   `docker compose ps`, health endpoints, image IDs, build SHA, and timestamps. Do not apply a DB
   migration unless the release explicitly includes and reviews one.
3. **Isolated smoke:** use a dedicated authorized test account and new isolated web session; do
   not reuse customer history. Send the five turns above sequentially and attach a fresh unique
   `request_id` to each HTTP request. Capture request/response metadata with secrets and personal
   data redacted. Assert selected route, schema-valid args, returned rows and evidence, truthful
   final answer, no repeated identical business-empty, closed trace/reason, and no direct-use claim
   from category/sphere-only evidence.
4. **Correlate:** for each request ID, verify API logs and traces, business status/reason, route and
   fallback attempts, evidence/provenance, and per-phase latency. Check dashboards/counters before
   and after the smoke; distinguish business-empty from transport success. Save the baseline/fixed
   comparison with image/config/data revision, attempts, business-empty count, evidence grade,
   and latency. Do not place request IDs, query text, user IDs, or trace IDs in metric labels.
5. **Promote only** after every assertion succeeds and evidence is reviewed. Preserve the smoke
   report and linked trace/log references in the release record.
6. **Rollback:** if any hard assertion, health check, or error/latency guardrail fails, stop
   promotion and restore the previously recorded known-good images/config using the normal compose
   rollback procedure; revert only the implicated migration if its reviewed rollback is safe.
   Recheck health and run a known-good catalog + portfolio smoke. Keep failed release artifacts
   for diagnosis; do not repeat the test against user sessions.

No production request was sent as part of this report: the locally running service images are not
source-aligned, and the checked-in selector test failure means the preconditions for safe rollout
are unmet. Production trace evidence, fixed-vs-baseline latency, and the RFC-030 repeated-run
artifact remain release/acceptance blockers rather than fabricated results.
