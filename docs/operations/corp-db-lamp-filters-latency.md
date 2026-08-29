Canonical-series lamp_filters Latency Evidence
==============================================

Purpose
-------

Use this operator benchmark after a canonical-series SQL or mapping change. It measures
direct-tool HTTP latency for both Ex routes and records a bounded PostgreSQL plan summary:

- `LAD LED R500 2Ex`, `flux_lm_min=11540`
- `LAD LED R320 Ex`, `flux_lm_min=11540`

This is an on-demand production-like check, not a shared-service CI gate. The script retains
aggregate statistics only; it does not retain raw samples, user text, `user_id`, headers, DSNs,
or secrets.

Prerequisites
-------------

- Run from the repository root on the Docker Compose host.
- `tools-api` and `corp-db` containers must be healthy.
- The baseline and current runs must use comparable stack resources and dataset contents.
- Build metadata should be set when rebuilding the measured stack:

```bash
export BUILD_GIT_SHA=$(git rev-parse HEAD)
export BUILD_TIME=$(date -u +%FT%TZ)
docker compose up -d --build corp-db corp-db-migrator tools-api
```

Canonical command
-----------------

The following single command captures baseline/current artifacts and enforces both budgets.
Use the pre-change commit for the baseline run, then restore the target commit and run the
current half. Do not commit large raw samples; the script never writes them.

```bash
mkdir -p docs/operations/evidence

python3 scripts/corp_db_lamp_filters_latency.py run \
  --label baseline \
  --schema-git-sha "$(git rev-parse HEAD)" \
  --output docs/operations/evidence/canonical-series-lamp-filters-baseline.json \
  --warmups 5 --measured 30

# Deploy the target canonical mapping/view, preserving the same dataset and resource limits.

python3 scripts/corp_db_lamp_filters_latency.py run \
  --label current \
  --schema-git-sha "$(git rev-parse HEAD)" \
  --output docs/operations/evidence/canonical-series-lamp-filters-current.json \
  --warmups 5 --measured 30

python3 scripts/corp_db_lamp_filters_latency.py compare \
  --baseline docs/operations/evidence/canonical-series-lamp-filters-baseline.json \
  --current docs/operations/evidence/canonical-series-lamp-filters-current.json \
  --output docs/operations/evidence/canonical-series-lamp-filters-report.md
```

What is measured
----------------

The timed loop runs inside the already-running `tools-api` container and sends HTTP POSTs to
`http://127.0.0.1:8100/corp-db/search`. Docker process startup is outside every sample. Each
case has at least five untimed warmups and thirty measured requests. The artifact records:

- HTTP and application success/error counts and HTTP success rate;
- sample count, median, nearest-rank p95, and max latency;
- repository SHA, schema SHA, UTC timestamp, service build metadata, and container image IDs;
- PostgreSQL version, database size, and relevant table row counts;
- `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` summary for canonical series + flux SQL.

Pass/fail contract
------------------

`compare` exits non-zero unless every canonical route case satisfies all conditions:

1. baseline and current each contain at least 5 warmups and 30 measured requests;
2. all measured requests have HTTP success and successful/empty application status;
3. current p95 is strictly below `500 ms`;
4. current p95 is at most `baseline p95 * 1.20`.

If the comparison fails, do not close the latency acceptance criterion. Create a separate
performance bug and attach the aggregate artifacts plus EXPLAIN summaries for diagnosis.

Saved evidence
--------------

The evidence for `totosha-7fuc.5` is stored in:

- `docs/operations/evidence/canonical-series-lamp-filters-baseline.json`
- `docs/operations/evidence/canonical-series-lamp-filters-current.json`
- `docs/operations/evidence/canonical-series-lamp-filters-report.md`

These artifacts are the evidence link for `totosha-6y9m.1#8`.
