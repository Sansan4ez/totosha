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

`docker compose up -d` now starts a one-shot `corp-db-migrator` service after
`corp-db` becomes healthy. `tools-api` waits for this service to complete
successfully before it starts serving corp-db traffic.

Operator verification
---------------------

```bash
docker compose ps
docker compose logs --tail 100 corp-db-migrator
python3 scripts/doctor.py
```

Expected signals:

- `corp-db-migrator` exits with code `0`
- `doctor.py` reports passing RFC-026 schema checks
- `corp.sphere_curated_categories` row count matches `db/spheres.json`

Remediation for existing volumes
--------------------------------

If `doctor.py` reports missing RFC-026 schema objects or curated rows:

```bash
docker compose up -d --build corp-db corp-db-migrator tools-api
docker compose logs -f corp-db-migrator
python3 scripts/doctor.py
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
