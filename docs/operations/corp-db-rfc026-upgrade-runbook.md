Corp DB RFC-026 Upgrade Runbook
===============================

Purpose
-------

RFC-026 added two live requirements for corp-db consumers:

- `corp.sphere_curated_categories`
- `corp.categories.parent_category_id`

Fresh databases get these objects from `db/init.sql`. Existing persistent volumes
need the idempotent live migrator to apply the same upgrade and seed the curated
sphere/category edges from `db/spheres.json`.

Automatic path
--------------

```bash
export BUILD_GIT_SHA=$(git rev-parse --short HEAD)
export BUILD_TIME=$(date -u +%FT%TZ)
docker compose up -d
```

This starts a one-shot `corp-db-migrator` service after `corp-db` becomes healthy.
`tools-api` waits for this service to complete successfully before it starts serving corp-db traffic.

Operator verification
---------------------

```bash
docker compose ps
docker compose logs --tail 100 corp-db-migrator
curl -fsS http://127.0.0.1:8100/health | jq
curl -fsS http://127.0.0.1:4000/health | jq
python3 scripts/doctor.py
```

Expected signals:

- `corp-db-migrator` exits with code `0`
- `tools-api /health` reports `corp_db_rfc026.applied=true`
- `core /health` reports the expected `build.git_sha` / `build.build_time`
- `doctor.py` reports passing RFC-026 schema checks
- `corp.sphere_curated_categories` row count matches `db/spheres.json`

Remediation for existing volumes
--------------------------------

If `doctor.py` reports missing RFC-026 schema objects or curated rows:

```bash
export BUILD_GIT_SHA=$(git rev-parse --short HEAD)
export BUILD_TIME=$(date -u +%FT%TZ)
docker compose up -d --build corp-db corp-db-migrator tools-api core
docker compose logs -f corp-db-migrator
curl -fsS http://127.0.0.1:8100/health | jq
python3 scripts/doctor.py
python3 scripts/incident_replay_smoke.py --docker-exec
```

If you need to rerun only the live migration:

```bash
docker compose up -d corp-db-migrator
docker compose logs --tail 100 corp-db-migrator
```

Failure modes
-------------

- `corp-db-migrator` cannot connect to Postgres: verify `corp-db` is healthy and the
  `corp_db_rw_dsn` secret matches the live database.
- `doctor.py` shows missing curated rows: inspect `db/spheres.json`, rerun the
  migrator, then recheck.
- `doctor.py` shows missing parent links: inspect `db/categories.json`, rerun the
  migrator, then recheck.
