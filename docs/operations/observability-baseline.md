Observability Baseline
======================

Purpose
-------

Document the minimum telemetry assets and runtime checks expected across services.

Baseline Assets
---------------

- Victoria stack root: `victoriametrics/`
- Stack compose: `victoriametrics/docker-compose.yml`
- OTEL collector config: `victoriametrics/otel-collector-config.yml`
- Alert catalog: `victoriametrics/alerts/minimum-alerts.yaml`
- Executable `vmalert` rules: `victoriametrics/alerts/vmalert-rules.yaml`
- Grafana datasources: `victoriametrics/grafana/provisioning/datasources/datasources.yaml`
- Grafana dashboards: `victoriametrics/grafana/provisioning/dashboards/files/`
- Smoke entrypoint: `victoriametrics/smoke_test.sh`
- Smoke artifacts directory when orchestrated by harness: `victoriametrics/smoke/`

Minimum Expectations
--------------------

- Every HTTP service exports traces, metrics, and logs through the shared OTEL collector.
- Every service keeps `service.name` stable and aligned with `harness/manifest.yaml`.
- Signal coverage is catalogued in `harness/observability/signals.yaml`.
- `harness/observability/baseline.yaml` is the source of truth for PR label gating, compose files, smoke timeout, and artifact location.
- Generated observability inventories under `docs/generated/` stay in sync with dashboards, alerts, and smoke assets.
- Smoke can be run per service through the installed `observability-harness` skill against `--repo-root .`.

Notes
-----

- Keep repo-specific thresholds and panel details here, but do not move the baseline file paths.
