# Bench Module

This directory contains the complete bench module: dataset, runner, evaluator, dashboard builder, pricing config, dashboard assets, and generated artifacts.

## Layout

- `bench/bench_run.py`: runs the golden dataset against Core and writes JSONL results.
- `bench/bench_eval.py`: evaluates results against deterministic checks.
- `bench/bench_dashboard_build.py`: builds static JSON reports for the dashboard.
- `bench/bench_lib.py`: shared stdlib-only helpers.
- `bench/golden/v1.jsonl`: golden dataset (product/company facts, tool-payload algorithmic checks).
- `bench/golden/rfc028-routing-baseline.jsonl`: routing-only smoke dataset, one case per RFC-028 leaf route.
- `bench/golden/incident-pfit7.jsonl`: incident-replay regression cases.
- `bench/pricing.json`: model pricing used for cost estimation.
- `bench/results/`: run outputs, gitignored.
- `bench/reports/`: generated reports for dashboard and eval, gitignored.
- `bench/dashboard/`: static UI assets.

## Algorithm

1. `bench/bench_run.py` reads a golden JSONL dataset (`bench/golden/v1.jsonl` by default).
2. For each case it clears the session, sends the question to Core (or calls a tool directly in `direct_tool` mode), and writes one JSONL result row with `request_id`, `answer`, `status`, latency, and optional meta.
3. `bench/bench_eval.py` reads the dataset plus a results file and scores each case per its `validation.mode` (see below) — deterministic checks against tool-call artifacts and routing metadata, not the LLM's final prose.
4. `bench/bench_dashboard_build.py` converts one or more results files into static JSON reports for `bench/dashboard/`.

## What Bench Verifies

Bench is deliberately not an LLM-answer-quality eval. Each case declares a `validation.mode`:

- `algorithmic`: asserts on the structured payload of a tool call (`corp_db_search` results, `filters`, `status`, ...) via `validation.checks[]` against `validation.artifact_selector`. This is how retrieval/search correctness across corp-db `kind`s (`hybrid_search`, `lamp_filters`, `lamp_documents_index`, `lamp_code_lookup`, `sphere_categories`, ...) is checked without touching the final answer text.
- `routing_only`: asserts only on routing metadata (`meta.retrieval_leaf_route_id`, `intent`, `selected_source`, `guardrail_hits`, `forbid_tools`, ...) — used by `rfc028-routing-baseline.jsonl` to check the selector picks the correct route for a family of questions, independent of what the agent eventually says.
- `hybrid` / `legacy_text`: combine algorithmic/routing checks with text assertions on the answer (`contains_any`, `regex`, `number`) for cases where the final wording still matters (e.g. must include a URL or a specific number).

### Route id convention (RFC-028)

`routing.route_id` in golden cases must be expressed in the **leaf-slug** form that `meta.retrieval_leaf_route_id` actually emits at runtime (e.g. `company_general`, `catalog_filters_by_category`), not the dotted `family.leaf` `route_id` used in the `core/routes/*/*.yaml` catalog (e.g. `corp_kb.company_common`, `corp_db.lamp_filters`). The two diverge because `meta.retrieval_route_id` collapses siblings that share one physical KB scope (all `corp_kb.*` routes report `corp_kb.company_common` there), so `bench_lib.routing_accuracy_summary` prefers the leaf slug to disambiguate. Golden routing cases also carry `routing.route_id_dotted` alongside `route_id` purely for human traceability back to the catalog file. If `core/documents/routing.py::ROUTE_BUSINESS_METADATA` changes a route's `leaf_route_id`, or a new route is added, update the corresponding golden `route_id` value(s) to match — `docker exec core sh -lc "curl ... /api/chat"` with `return_meta=true` against a live stack is the fastest way to read the current leaf slug back.

Default paths are resolved relative to the repository root, so the module works even if it is launched from another current working directory.

## Usage

Run a small subset:

```bash
python3 bench/bench_run.py --docker-exec --limit 5
```

Evaluate a run:

```bash
python3 bench/bench_eval.py --results bench/results/<run_id>.jsonl
```

Build dashboard data:

```bash
python3 bench/bench_dashboard_build.py
python3 -m http.server 8000
# open http://127.0.0.1:8000/bench/dashboard/
```

## Default Behavior

- Without `--limit`, `bench/bench_run.py` runs the full dataset from `bench/golden/v1.jsonl`.
- With `--limit N`, it runs only the first `N` cases from that dataset.
- With `--dataset <path>`, it runs exactly the cases from the provided JSONL file.
- `bench/bench_eval.py` compares results against the dataset passed via `--dataset`.
- If eval is run against the full dataset after a smoke run that used only a subset, the remaining cases are reported as `missing_result`.

## Order of Use

1. Bring up the stack.
2. Run `bench/bench_run.py` on the full dataset or a smoke subset.
3. Inspect pass rate with `bench/bench_eval.py`.
4. If needed, generate dashboard reports and inspect failures by `request_id`.

Detailed operations guidance lives in:

- `docs/operations/bench-runbook.md`
- `docs/operations/bench-eval.md`
- `docs/operations/bench-dashboard.md`
