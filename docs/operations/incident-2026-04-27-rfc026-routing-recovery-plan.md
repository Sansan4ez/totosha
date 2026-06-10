Incident Recovery Plan: 2026-04-27 RFC-026 Runtime Drift and Routing Failures
==========================================================================

Status
------

Drafted from live incident analysis on 2026-04-27.

Scope
-----

This plan addresses the repeated live failures for:

- broad series question: `какие у вас есть серии светильников?`
- sphere recommendation question: `что порекомендуешь для РЖД?`

Observed Root Causes
--------------------

1. Live Postgres schema drift: RFC-026 objects are missing in the running `corp-db` volume.
   - `corp.sphere_curated_categories` does not exist
   - `corp.categories.parent_category_id` does not exist
2. Live `core` / `tools-api` routing behavior still follows the pre-fix broad-series path.
   - broad series questions still route through `corp_db.catalog_lookup`
   - `tools-api` rejects `knowledge_route_id=corp_db.catalog_lookup` with `400 Unknown knowledge_route_id`
3. Runtime drift exists between repository fixes and deployed containers.
   - `docker compose config --services` includes `corp-db-migrator`
   - `docker compose ps -a corp-db-migrator` shows no created container
   - live traces and logs still show the old failure paths

Evidence Anchors
----------------

Trace IDs:

- `5f62c80644ffbdec8b1840533e011c28` — broad series failure
- `3ce9c0e718635591a5342856eec284c7` — RZD recommendation failure
- `123a2cf103bece45d6e75c93d67e7ad0` — RZD portfolio success control case

Key live errors:

- `400: {"detail":"Unknown knowledge_route_id: corp_db.catalog_lookup"}`
- `отношение "corp.sphere_curated_categories" не существует`
- `Корпоративная база временно недоступна`

Control fact:

- `portfolio_by_sphere` for `РЖД` still succeeds, so corp-db is not globally down.

Phase 0 — Freeze and Capture
----------------------------

Goal: preserve proof of the current failure state before remediation.

Commands:

```bash
docker compose ps
docker ps -a --format 'table {{.Names}}\t{{.Status}}'

docker exec corp-db psql -U ${CORP_DB_ADMIN_USER:-postgres} -d ${CORP_DB_NAME:-corp_pg_db} -Atqc "
select
  to_regclass('corp.sphere_curated_categories'),
  exists (
    select 1
    from information_schema.columns
    where table_schema='corp'
      and table_name='categories'
      and column_name='parent_category_id'
  );
"
```

Expected current broken-state result:

- first column empty / null for `corp.sphere_curated_categories`
- second column `f`

Phase 1 — Apply RFC-026 Live DB Migration
-----------------------------------------

Priority: P0.

Goal: restore the schema required by `corp_db.sphere_curated_categories`.

Commands:

```bash
docker compose up -d --build corp-db corp-db-migrator
docker compose ps -a corp-db-migrator
docker logs corp-db-migrator --tail 200
```

Validation:

```bash
docker exec corp-db psql -U ${CORP_DB_ADMIN_USER:-postgres} -d ${CORP_DB_NAME:-corp_pg_db} -Atqc "
select
  to_regclass('corp.sphere_curated_categories'),
  exists (
    select 1
    from information_schema.columns
    where table_schema='corp'
      and table_name='categories'
      and column_name='parent_category_id'
  );
"

python3 scripts/doctor.py
```

Success criteria:

- `corp.sphere_curated_categories` exists
- `parent_category_id` exists
- `doctor.py` no longer reports RFC-026 schema drift
- `corp-db` logs no longer emit `sphere_curated_categories does not exist`

Stop condition:

- if `corp-db-migrator` exits with error, do not continue to application redeploy until migration is fixed.

Phase 2 — Redeploy Live Application Services
--------------------------------------------

Priority: P0/P1.

Goal: ensure running `core` and `tools-api` pick up the fixed routing behavior for broad series questions.

Commands:

```bash
docker compose up -d --build tools-api core
```

If containers are not recreated as expected:

```bash
docker compose rm -sf core tools-api
docker compose up -d --build tools-api core
```

Validation:

```bash
docker compose ps core tools-api
docker logs core --tail 100
docker logs tools-api --tail 100
```

Success criteria:

- live broad series requests no longer produce `Unknown knowledge_route_id: corp_db.catalog_lookup`
- live `core` no longer routes broad series requests through the broken pre-fix path

Phase 3 — Functional Verification Against the Incident Cases
------------------------------------------------------------

Priority: P1.

Required smoke prompts:

1. `какие у вас есть серии светильников?`
2. `что порекомендуешь для РЖД?`
3. `Какие есть реализованные проекты для РЖД?`

Response-level success criteria:

- series query must not fall back to `Сейчас у меня нет подтверждённого списка серий...`
- RZD recommendation must not fall back to `корпоративная база временно недоступна`
- RZD portfolio query must remain successful

Log-level success criteria:

- no `Unknown knowledge_route_id: corp_db.catalog_lookup`
- no `отношение "corp.sphere_curated_categories" не существует`
- no `tool_status=error` for `selected_route_id=corp_db.sphere_curated_categories`

Metric checks:

```bash
curl -gs 'http://127.0.0.1:8428/api/v1/query' \
  --data-urlencode 'query=sum by (status) (increase(http_server_duration_milliseconds_count{service_name="tools-api",route="/corp-db/search"}[30m]))'

curl -gs 'http://127.0.0.1:8428/api/v1/query' \
  --data-urlencode 'query=sum by (kind,status) (increase(corp_db_search_duration_milliseconds_count[30m]))'

curl -gs 'http://127.0.0.1:8428/api/v1/query' \
  --data-urlencode 'query=sum by (tool_name,selected_route_id,tool_status) (increase(tool_executions_total{tool_name="corp_db_search"}[30m]))'
```

Metric success criteria:

- no fresh `sphere_curated_categories:error`
- no fresh `Unknown knowledge_route_id`-driven `400` path for the series request
- no fresh `lamp_exact/http_error` tied to the broad-series incident path

Phase 4 — Trace-Based Confirmation
----------------------------------

Priority: P1.

For each new smoke request, capture the returned trace ID and verify that the repaired path is visible in VictoriaTraces.

Expected repaired behaviors:

- series query no longer shows `tool.corp_db_search` with `http.status_code=400` on the old path
- RZD recommendation shows successful `corp_db.sphere_curated_categories` retrieval
- RZD portfolio still shows successful `corp_db.portfolio_by_sphere`

Phase 5 — Prevent Recurrence
----------------------------

Priority: P2.

Hardening actions:

1. Make `corp-db-migrator` an explicit deploy-stage requirement for live upgrades.
2. Treat RFC-026 schema drift as a deploy-blocking condition.
3. Require post-deploy verification with:
   - `python3 scripts/doctor.py`
   - `python3 scripts/incident_replay_smoke.py`
   - targeted chat smokes for broad series and RZD recommendation
4. Expose runtime version/build visibility for deployed services:
   - git SHA
   - build time
   - routing catalog version
   - schema version / RFC-026 applied indicator

Temporary Mitigation If Full Recovery Is Delayed
------------------------------------------------

If full deploy cannot be completed quickly:

1. disable or guard `sphere_curated_categories` when RFC-026 schema is absent, returning a bounded operator-safe explanation instead of a DB-backed recommendation attempt;
2. avoid sending broad series queries through `corp_db.catalog_lookup` until the fixed runtime is deployed.

Definition of Done
------------------

The incident is considered resolved only when all of the following are true:

1. `python3 scripts/doctor.py` reports no RFC-026 schema drift.
2. `corp-db` logs no longer contain `corp.sphere_curated_categories does not exist`.
3. broad series requests no longer trigger `Unknown knowledge_route_id: corp_db.catalog_lookup`.
4. `что порекомендуешь для РЖД?` returns a grounded recommendation rather than a degraded DB-unavailable fallback.
5. `Какие есть реализованные проекты для РЖД?` still succeeds.
6. Post-fix metrics for the validation window show no fresh `sphere_curated_categories:error` events.
