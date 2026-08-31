# Production benchmark audit — 2026-08-31

## Scope

- Deployed Core `/api/chat`, `execution_mode=runtime`.
- Configured and provider-reported model: `gpt-5.6-terra`.
- Independent sessions (`/api/clear` before every agent case).
- Deterministic data-plane suite: 47 `direct_tool` cases, no LLM.
- Production-agent suite: 26 representative business and incident questions.
- Routing baseline: 22 route-card cases.

## Results

| Layer | Result | Latency p50 / p95 | Tokens | Estimated cost |
|---|---:|---:|---:|---:|
| Fast unit/contract tests | 122/122 passed | — | 0 | $0 |
| Deterministic direct-tool data plane | 47/47 passed | 114 / 606 ms | 0 | $0 |
| Production-agent answers | 22/26 passed (84.62%) | 10335 / 15523 ms | 261724 | $0.76191 |
| Production routing baseline | 19/22 passed (86.36%) | 6735 / 14850 ms | 162918 | $0.47028 |

## Production-agent failures

1. `sales-001-certificates-links`: route was correct, but the answer did not provide the requested direct certificate links; it asked for exact modifications.
2. `tech-001-tempered-glass`: selected `catalog_filters_by_category` instead of `series_description`, then said the data did not state which series use tempered glass.
3. `tech-002-r500-vs-r700`: selected exact `catalog_entity_lookup` for two series as one name instead of `series_description`; returned empty.
4. `tech-027-application-stadium-projectors`: models were recommended correctly, but the requested portfolio link was absent because portfolio evidence did not reach the answer.

The Ex/2Ex incident pair passed 2/2, including canonical `LAD LED R500 2Ex`, `flux_lm_min=11540`, and the R320 module-number counterexample.

## Routing baseline failures

- `documents_by_lamp_name` -> `company_general`
- `passport_by_lamp_name` -> `company_general`
- `mounting_compatibility_by_series` -> `mountings_by_category`

The third result may indicate an overlap/wording issue in the golden route contract: the question asks which mountings are available for a series, which the selected `category_mountings` route answers correctly. The two document mismatches are real route-selection regressions even though the argument builder produced document-shaped arguments.

## Benchmark audit findings

- The previous default `v1` score was not a full-agent score: 47/50 cases bypassed the router, ReAct loop, and final LLM answer.
- `routing.route_id` mismatches previously appeared only in aggregate statistics and did not fail individual cases. The evaluator now enforces them for agent-chat runs.
- Missing expected `routing.intent` previously passed silently. It now fails loudly.
- Production runs can now pin both configured model and provider-reported model.
- Docker-exec HTTP status is now captured instead of treating any successful curl process as HTTP 200.
- Two direct-tool golden checks incorrectly asserted against truncated `preview` while the fact existed in `content`; they now use the full structured field.
