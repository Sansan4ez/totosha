Bench Eval (Golden Dataset Scoring)
==================================

Purpose
-------

This document explains how to evaluate bench runs produced by `bench/bench_run.py` against the golden dataset (`bench/golden/v1.jsonl`), how checks work, and how to tune cases to stay deterministic and maintainable.

Prereqs
-------

- Results JSONL: `bench/results/<run_id>.jsonl`
- Golden dataset JSONL: `bench/golden/v1.jsonl`

Run
---

Print summary (JSON to stdout) and list failures:

```bash
python3 bench/bench_eval.py --results bench/results/<run_id>.jsonl
```

Write a Markdown report and a JSON summary:

```bash
python3 bench/bench_eval.py \
  --results bench/results/<run_id>.jsonl \
  --report bench/reports/<run_id>.md \
  --json-out bench/reports/<run_id>.json
```

Useful flags:

- `--dataset bench/golden/v1.jsonl` to override the dataset file
- `--show-fails 50` to print more failing cases to stdout

Outputs
-------

`bench/bench_eval.py` prints a summary JSON with:

- `pass_rate`, `pass`, `fail`, `missing_results`, `non_ok`
- `duration_ms_avg`, `duration_ms_p50`, `duration_ms_p95`
- `tokens_prompt`, `tokens_completion`, `tokens_total` (when `meta.llm_usage` exists)
- `estimated_cost_usd_total` (when `estimated_cost_usd` exists)
- tag-level pass rates (`tags`)

If `--report` is provided, the Markdown report also includes `request_id` per failure so you can jump to observability quickly.

How Scoring Works
-----------------

Each dataset line is a JSON object. The evaluator reads:

- `case.golden.checks[]`: list of deterministic checks
- `result.answer`: agent answer text from results JSONL
- `result.status`: non-`ok` is always a failure (e.g. `access_denied`, `timeout`)

Check Types (v1)
----------------

Supported check types in `golden.checks[]`:

- `contains_all`: all substrings must exist (case-insensitive)
- `contains_any`: at least one substring must exist
- `regex`: Python regex (IGNORECASE + MULTILINE)
- `number`: answer must contain a number `value ± tolerance` (tolerance can be `0`)

Examples:

```json
{ "type": "contains_any", "value": ["ladzavod.ru", "ЛАДзавод"] }
```

```json
{ "type": "regex", "pattern": "основан(а)?\\s+в\\s+2006" }
```

```json
{ "type": "number", "value": 2006, "tolerance": 0 }
```

Tuning the Golden Dataset
-------------------------

Guidelines that keep evaluation stable:

- Prefer checks for facts that are truly deterministic (years, URLs, names, cities).
- If the question is ambiguous, adapt the question to a concrete entity that exists in your current DB/wiki state.
- Keep checks minimal: validate the key fact, not the exact wording.
- Always keep `evidence[]` pointing to the source of truth (file path or URL) so the case can be updated when data changes.

Debugging Failures with Observability
-------------------------------------

Workflow:

1. Find the failing case in the report or in results JSONL.
2. Copy its `request_id` (format: `bench/<run_id>/<case_id>`).
3. Search logs/traces by `request_id`. Core emits request completion logs with `request_id`, `trace_id`, `span_id`.
4. Identify the failure mode (common ones: access control `access_denied`, proxy latency/timeouts, tool routing mismatch, corp-db/tool API errors).
5. Apply a fix (prompt/skills/tools/DB), then re-run bench and compare summaries.

See also: `docs/operations/observability-runbook.md`.
