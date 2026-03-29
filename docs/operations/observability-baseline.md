Observability Baseline
======================

Purpose
-------

Document the minimum telemetry assets and runtime checks expected across services.

Baseline Assets
---------------

- Victoria stack root: `victoriametrics/`
- Stack compose: `victoriametrics/docker-compose.yml`
- App overlay compose: `docker-compose.observability.yml`
- OTEL collector config: `victoriametrics/otel-collector-config.yml`
- Alert catalog: `victoriametrics/alerts/minimum-alerts.yaml`
- Executable `vmalert` rules: `victoriametrics/alerts/vmalert-rules.yaml`
- Grafana datasources: `victoriametrics/grafana/provisioning/datasources/datasources.yaml`
- Grafana dashboards: `victoriametrics/grafana/provisioning/dashboards/files/`
- Smoke entrypoint: `victoriametrics/smoke_test.sh`
- Smoke artifacts directory when orchestrated by harness: `victoriametrics/smoke/`

Minimum Expectations
--------------------

- Every HTTP service in the main request path (`core`, `tools-api`, `proxy`, `bot`, `scheduler`) exposes `GET /metrics`.
- Every HTTP service emits:
  - metric `http_server_duration_milliseconds`
  - log line `HTTP request completed`
  - trace span `api.request`
- Catalog retrieval services additionally emit:
  - metric `corp_db_search_duration_milliseconds`
  - metric `corp_db_search_phase_duration_milliseconds`
  - trace spans `tool.corp_db_search`, `corp_db.lamp_filters`, `corp_db.hybrid_primary`, `corp_db.embedding`, `corp_db.token_fallback`, `corp_db.alias_fallback`
- Every instrumented service adds `request_id`, `trace_id`, and `span_id` correlation to logs.
- Traces and logs are exported through the shared OTEL collector when `docker-compose.observability.yml` is applied.
- Metrics are scraped by the OTEL collector from each service `/metrics` endpoint and forwarded to VictoriaMetrics.
- Every service keeps `service.name` stable and aligned with `harness/manifest.yaml`.
- Signal coverage is catalogued in `harness/observability/signals.yaml`.
- `harness/observability/baseline.yaml` is the source of truth for PR label gating, compose files, smoke timeout, and artifact location.
- Generated observability inventories under `docs/generated/` stay in sync with dashboards, alerts, and smoke assets.
- Smoke can be run per service through the installed `observability-harness` skill against `--repo-root .`.

Notes
-----

- The observability overlay binds service ports to `127.0.0.1` only, so smoke and local triage work without widening public exposure.
- Rebuild application services with both compose files: `docker-compose.yml` and `docker-compose.observability.yml`. Rebuilding only the base compose drops OTEL env and breaks request-to-trace correlation.
- Keep repo-specific thresholds and panel details here, but do not move the baseline file paths.
