# Bench Module

This directory contains the complete bench module: dataset, runner, evaluator, dashboard builder, pricing config, dashboard assets, and generated artifacts.

## Layout

- `bench/bench_run.py`: runs the golden dataset against Core and writes JSONL results.
- `bench/bench_eval.py`: evaluates results against deterministic checks.
- `bench/bench_dashboard_build.py`: builds static JSON reports for the dashboard.
- `bench/bench_lib.py`: shared stdlib-only helpers.
- `bench/golden/v1.jsonl`: golden dataset.
- `bench/pricing.json`: model pricing used for cost estimation.
- `bench/results/`: run outputs, gitignored.
- `bench/reports/`: generated reports for dashboard and eval, gitignored.
- `bench/dashboard/`: static UI assets.

## Algorithm

1. `bench/bench_run.py` reads `bench/golden/v1.jsonl`.
2. For each case it clears the session, sends the question to Core, and writes one JSONL result row with `request_id`, `answer`, `status`, latency, and optional meta.
3. `bench/bench_eval.py` reads the dataset plus a results file and applies deterministic checks from `golden.checks[]`.
4. `bench/bench_dashboard_build.py` converts one or more results files into static JSON reports for `bench/dashboard/`.

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
