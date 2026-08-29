Canonical-series lamp_filters latency evidence
===============================================

**Result: PASS**

- Baseline: `docs/operations/evidence/canonical-series-lamp-filters-baseline.json`
- Current: `docs/operations/evidence/canonical-series-lamp-filters-current.json`
- Budget: current p95 `< 500 ms` and `<= baseline * 1.20`
- Minimum sampling: 5 warmups + 30 measured requests per case

| Case | Run | HTTP success | Samples | Median | p95 | Max | Budget result |
|---|---|---:|---:|---:|---:|---:|---|
| r320_ex | baseline | 100.0% | 30 | 143.411 ms | 153.737 ms | 157.207 ms | reference |
| r320_ex | current | 100.0% | 30 | 126.984 ms | 182.612 ms | 186.813 ms | PASS (<500 ms; <= 184.484 ms) |
| r500_2ex | baseline | 100.0% | 30 | 130.284 ms | 227.035 ms | 235.930 ms | reference |
| r500_2ex | current | 100.0% | 30 | 135.289 ms | 196.606 ms | 315.743 ms | PASS (<500 ms; <= 272.442 ms) |

The JSON artifacts contain aggregate latency, HTTP/application errors, dataset size,
build/container metadata, and bounded EXPLAIN summaries. Raw samples, user text, user_id,
DSNs, authorization headers, and secrets are intentionally not retained.
