Observability Baseline
======================

Purpose
-------

Document the minimum telemetry assets and runtime checks expected across services.

Baseline Assets
---------------

- Victoria stack root: `victoriametrics/`
- Stack compose: `victoriametrics/docker-compose.yml`
- Base app compose: `docker-compose.yml`
- Optional localhost port overlay: `docker-compose.observability.yml`
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
- Core retrieval orchestration additionally emits:
  - metric `retrieval_route_requests_total`
  - metric `retrieval_route_family_requests_total`
  - metric `retrieval_route_leaf_requests_total`
  - metric `retrieval_route_leaf_errors_total`
  - metric `retrieval_route_leaf_duration_milliseconds`
  - metric `retrieval_route_argument_validation_errors_total`
  - metric `retrieval_route_family_fallback_total`
  - metric `retrieval_route_stage_total`
  - metric `retrieval_route_duration_milliseconds`
  - metric `tool_executions_total`
  - metric `tool_execution_duration_milliseconds`
  - metric `retrieval_guardrail_blocks_total`
- Catalog retrieval services additionally emit:
  - metric `corp_db_search_duration_milliseconds`
  - metric `corp_db_search_phase_duration_milliseconds`
  - trace spans `tool.corp_db_search`, `corp_db.lamp_filters`, `corp_db.hybrid_primary`, `corp_db.embedding`, `corp_db.token_fallback`, `corp_db.alias_fallback`
- Every instrumented service adds `request_id`, `trace_id`, and `span_id` correlation to logs.
- Route-aware retrieval logs and spans also expose `selected_route_id`, `selected_route_family`, `selected_business_family_id`, `selected_leaf_route_id`, `route_stage`, `route_arg_validation_status`, `used_fallback_scope`, `selected_route_kind`, `selected_source`, `knowledge_route_id`, `document_id`, `tool_name`, and `tool_status`.
- Traces and logs are exported through the shared OTEL collector by default from the base app compose. `docker-compose.observability.yml` only adds localhost port bindings for local smoke and triage.
- Metrics are scraped by the OTEL collector from each service `/metrics` endpoint and forwarded to VictoriaMetrics.
- Every service keeps `service.name` stable and aligned with `harness/manifest.yaml`.
- Signal coverage is catalogued in `harness/observability/signals.yaml`.
- `harness/observability/baseline.yaml` is the source of truth for PR label gating, compose files, smoke timeout, and artifact location.
- Generated observability inventories under `docs/generated/` stay in sync with dashboards, alerts, and smoke assets.
- Smoke can be run per service through the installed `observability-harness` skill against `--repo-root .`.
- `core` smoke must prove one KB-route request and one document-domain request across Victoria Metrics, Logs, and Traces using fresh telemetry only.

Notes
-----

- The observability overlay binds service ports to `127.0.0.1` only, so smoke and local triage work without widening public exposure.
- Start the Victoria stack before the app stack so `otel-collector` is present on `agent-net`.
- The default supported app startup path is `docker compose up -d --build`, because the base compose now carries the required `OTEL_*` wiring for the main request path.
- Use `docker-compose.observability.yml` only when you need host-local access to app ports for smoke, curl-based triage, or local operator workflows.
- Metric-side runtime health should be checked via VictoriaMetrics queries such as `query=up` and request counters. `api/v1/targets` may remain empty because scraping is performed by the OTEL collector, not by VictoriaMetrics itself.
- Keep repo-specific thresholds and panel details here, but do not move the baseline file paths.
