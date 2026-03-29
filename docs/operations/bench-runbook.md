Bench Runbook (Golden Dataset / Runner / Eval)
=============================================

Purpose
-------

This document explains how to:

- run the bench runner (`scripts/bench_run.py`) against Core Agent;
- evaluate results deterministically (`scripts/bench_eval.py`) (see also `docs/operations/bench-eval.md`);
- build/open a local dashboard for results exploration (`docs/operations/bench-dashboard.md`);
- configure pricing (`bench/pricing.json`) so results include `estimated_cost_usd`;
- correlate failures with observability using `request_id`.

Quick Start
-----------

1) Bring up the stack:

```bash
docker compose up -d
```

Optional, but recommended for observability and local port binds:

```bash
docker compose -f victoriametrics/docker-compose.yml up -d
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

2) Run a small subset (calls Core inside the container, no host port required):

```bash
python3 scripts/bench_run.py --docker-exec --limit 5
```

This writes `bench/results/<run_id>.jsonl`.

3) Evaluate:

```bash
python3 scripts/bench_eval.py --results bench/results/<run_id>.jsonl
```

Eval runbook: `docs/operations/bench-eval.md`.

Inputs and Outputs
------------------

### Dataset

- Golden dataset is JSONL: `bench/golden/v1.jsonl`.
- Each line is one independent test case with:
  - `id`, `tags`
  - `question`
  - `golden.checks[]` (deterministic checks)
  - `evidence[]` (where the truth comes from: wiki file / product URL)

### Runner output

- Runner output is JSONL: `bench/results/<run_id>.jsonl` (gitignored).
- Each line includes:
  - `request_id = bench/<run_id>/<case_id>` (key for observability)
  - `duration_ms`, `status`, `answer`
  - `meta` (when Core supports `return_meta=true`): LLM tokens/time/tools used
  - `estimated_cost_usd` (optional, computed by runner)

Runner: How to Run
------------------

### Option A (recommended): `--docker-exec`

Core port is not exposed in default `docker-compose.yml`. Use docker exec mode:

```bash
python3 scripts/bench_run.py --docker-exec
```

Useful flags:

- `--limit N` to run only first N cases
- `--sleep-ms 200` to add a pause between cases
- `--timeout-s 180` to increase timeouts
- `--dataset bench/golden/v1.jsonl` to pick dataset
- `--out bench/results/my_run.jsonl` to choose output path

### Option B: call Core via HTTP

If Core is bound to host (for example via `docker-compose.observability.yml`):

```bash
python3 scripts/bench_run.py --core-url http://127.0.0.1:4000
```

Access Control Notes
--------------------

Bench uses `user_id/chat_id` and calls `POST /api/chat`.

Runner defaults:

- runner tries to auto-detect `admin_id` via `GET /api/admin/access` when `--user-id/--chat-id` are not provided;
- with `--docker-exec`, the call is executed inside the container;
- without `--docker-exec`, the call is made to `--core-url`, and then runner falls back to `ADMIN_USER_ID` env if needed.

If you see `status=access_denied` in results:

- check Core access mode in Admin Panel (Config / Access), or
- check `workspace/_shared/admin_config.json` inside the running stack, or
- ensure `ACCESS_MODE=public` for Core if you want bench to work without allowlisting, or
- run with explicit ids:

```bash
# discover effective admin_id/mode from inside the container
docker exec core sh -lc "curl -sS http://localhost:4000/api/admin/access"

# force runner to use that id
python3 scripts/bench_run.py --docker-exec --user-id <admin_id> --chat-id <admin_id>
```

Pricing: How to Add Prices
--------------------------

Pricing file: `bench/pricing.json`.

Schema (v1):

```json
{
  "default": { "prompt_per_1m_usd": 0.0, "cached_input_per_1m_usd": 0.0, "completion_per_1m_usd": 0.0 },
  "models": [
    { "match": "gpt-4o-mini", "prompt_per_1m_usd": 0.0, "cached_input_per_1m_usd": 0.0, "completion_per_1m_usd": 0.0 }
  ]
}
```

How matching works:

- runner takes the model name from `result.meta.llm_models[-1]` (or falls back to `result.meta.model`);
- it finds the first entry where `entry.match` is a substring of the model name;
- if none matched, `default` is used.

Example:

```json
{
  "default": { "prompt_per_1m_usd": 0.0, "cached_input_per_1m_usd": 0.0, "completion_per_1m_usd": 0.0 },
  "models": [
    { "match": "my-llm-prod", "prompt_per_1m_usd": 2.0, "cached_input_per_1m_usd": 0.2, "completion_per_1m_usd": 6.0 }
  ]
}
```

Notes:

- prices are now specified in USD per 1M tokens;
- if provider returns `usage.prompt_tokens_details.cached_tokens`, runner prices those tokens with `cached_input_per_1m_usd`;
- if cached token details are absent, runner treats all prompt tokens as regular input;
- runner still understands legacy `*_per_1k_usd` fields and converts them automatically;
- `bench_run.py` writes `estimated_cost_usd` into results JSONL at run time, but `bench_eval.py` and `bench_dashboard_build.py` recompute cost from current `bench/pricing.json` when `meta.llm_usage` is present, so pricing fixes apply to old runs without rerunning the agent;
- `estimated_cost_usd` is only computed when Core returns token usage in `meta.llm_usage`.
- some OpenAI-compatible backends may omit `usage`; then cost stays `null` even if pricing is configured.

Eval: Checks and Tuning
-----------------------

Eval reads `golden.checks[]` and applies them to the answer text.

Supported check types (v1):

- `contains_all`: all substrings must exist (case-insensitive)
- `contains_any`: at least one substring must exist
- `regex`: Python regex, IGNORECASE + MULTILINE
- `number`: extract numbers from answer and match `value ± tolerance`

Example check:

```json
{ "type": "number", "value": 18.3, "tolerance": 0.2 }
```

If a case is too ambiguous:

- adapt the question to a specific entity (exact product/series code),
- make checks reflect the deterministic part (e.g. “must contain URL” or “must contain 2006”),
- keep evidence in `evidence[]` so the case is maintainable.

For deeper guidance on adding/tuning checks and generating reports, see `docs/operations/bench-eval.md`.

Observability: Debugging Failures
---------------------------------

When a case fails, `bench_eval.py` prints `request_id`.

Recommended workflow:

1) Find the failing `request_id` in the results JSONL.
2) Search logs/traces by `request_id`:
   - Core emits `HTTP request completed` with `request_id`, `trace_id`, `span_id`.
3) Inspect where time/error happened:
   - Core agent loop
   - Proxy `/v1/chat/completions` latency
   - Tools-api `corp_db_search` latency/errors
4) Apply a fix:
   - prompt/skill routing
   - DB data/seed/indexes
   - tool timeouts or error handling
5) Re-run only the failing subset (`--limit` or a smaller dataset copy) and compare.

RFC-004 Catalog Retrieval Smoke
-------------------------------

Use the retrieval subset added for RFC-003 and RFC-004 when validating catalog latency and filter routing.

1. Build a temporary dataset with the retrieval cases:

```bash
SMOKE_DATASET="$(mktemp /tmp/rfc004-smoke.XXXXXX.jsonl)"
python3 - "$SMOKE_DATASET" <<'PY'
import sys
from pathlib import Path
ids = {
    "tech-016-retrieval-r500-12-by-power-voltage",
    "tech-017-retrieval-nova30-by-cri-climate-class",
    "tech-018-retrieval-r500-9-60-by-angle-size-weight",
    "tech-019-retrieval-ex-by-marking",
}
src = Path("bench/golden/v1.jsonl")
dst = Path(sys.argv[1])
rows = [line for line in src.read_text(encoding="utf-8").splitlines() if line and line.split('\"id\":\"', 1)[1].split('\"', 1)[0] in ids]
dst.write_text("\n".join(rows) + "\n", encoding="utf-8")
print(dst)
PY
```

2. Run the subset against `core`:

```bash
python3 scripts/bench_run.py --docker-exec --dataset "$SMOKE_DATASET" --timeout-s 180
```

3. Evaluate and summarize latency:

```bash
python3 scripts/bench_eval.py --dataset "$SMOKE_DATASET" --results bench/results/<run_id>.jsonl
python3 - <<'PY'
import json, statistics
from pathlib import Path
path = Path("bench/results/<run_id>.jsonl")
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
durations = [row["duration_ms"] for row in rows if row.get("status") == "ok"]
print({"pass_rate": sum(row.get("status") == "ok" for row in rows) / len(rows), "p50_ms": statistics.median(durations), "p95_ms": max(durations)})
PY
```

4. Correlate the slowest case by `request_id` in Victoria:

```bash
curl -fsS -X POST 'http://127.0.0.1:9428/select/logsql/query' \
  -d 'query=_time:1h request_id:bench/<run_id>/<case_id>' \
  -d 'limit=20'
```

5. Classify upstream LLM quota failures separately from search regressions:

- If the run fails before the first tool call and logs show `usage_limit_reached`, `model_cooldown`, or HTTP `429` from the proxy/LLM path, mark the smoke as `blocked_by_llm_quota` and rerun later.
- Do not treat those cases as `corp_db` regressions unless the same `request_id` also shows `corp_db_search` transport or application errors.
- When in doubt, inspect the trace by `request_id`: a quota issue fails in `core` or proxy before `tool.corp_db_search`; a search regression reaches `tools-api /corp-db/search` and usually has spans such as `corp_db.lamp_filters`, `corp_db.hybrid_primary`, or `corp_db.token_fallback`.

Acceptance target for RFC-004:

- pass rate `1.0` on the retrieval smoke subset
- `tools-api POST /corp-db/search` p95 below `3000 ms`
- explicit filter cases show `corp_db.lamp_filters` without `corp_db.embedding`

Baseline used for comparison:

- before RFC-004, `POST /api/chat` and `POST /corp-db/search` clipped at `10000 ms` in VictoriaMetrics
- warm `hybrid_search` on filter-heavy queries could take `7.6s .. 15.5s`
- after rollout, the same validation should show unclipped route histograms and a fast-path dominated phase profile

Operator sign-off checklist:

1. Save the printed `SMOKE_DATASET` path and `run_id` from the run output.
2. Reuse the same `SMOKE_DATASET` in both `bench_run.py` and `bench_eval.py`.
3. Confirm that any failed cases are not explained by upstream LLM `429` / `usage_limit_reached` / `model_cooldown`.
4. Attach the eval summary plus one Victoria screenshot or query result showing the slowest `request_id`.
