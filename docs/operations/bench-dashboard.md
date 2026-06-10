Bench Dashboard (Static HTML + JS)
=================================

Purpose
-------

This is a lightweight dashboard for exploring bench runs:

- pass/fail/missing overview
- latency/tokens/cost metrics
- tag breakdown
- case-level drilldown (question/answer/golden/checks/evidence/meta)

It is a static page powered by plain HTML + JS + ECharts and runs from any static server (for example `python3 -m http.server`).

ECharts is vendored into the repository (`bench/dashboard/vendor/echarts.min.js`) so the dashboard works in environments where public CDNs are blocked.

Build Data (JSON)
-----------------

The dashboard expects JSON reports in `bench/reports/`:

- `bench/reports/index.json`
- `bench/reports/<run_id>.json`
- `bench/reports/latest.json`

Generate them from `bench/results/*.jsonl`:

```bash
python3 bench/bench_dashboard_build.py
```

Run the UI
----------

1) Start a static server from the repo root:

```bash
python3 -m http.server 8000
```

2) Open:

- `http://127.0.0.1:8000/bench/dashboard/`

If `bench/reports/index.json` is missing, the UI shows a fallback that allows loading a single per-run report JSON via file picker.

Notes
-----

- Make sure you open the dashboard URL with trailing slash (`.../bench/dashboard/`). Some setups treat `.../bench/dashboard` as a file path, which breaks relative fetch paths.
- The dashboard reads files from the same host it is served from. If you access it via SSH tunnel, run `python3 bench/bench_dashboard_build.py` and `python3 -m http.server` on the remote machine (where `bench/reports/` exists), then forward that port to your local browser.
