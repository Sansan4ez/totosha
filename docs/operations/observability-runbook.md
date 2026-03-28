Observability Runbook
=====================

Purpose
-------

This is the operational entrypoint for observability triage and smoke execution.

Startup
-------

1. Start the observability stack:

```bash
docker compose -f victoriametrics/docker-compose.yml up -d
```

2. Start the application stack with observability overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

3. Run harness smoke orchestration:

```bash
Use the installed `observability-harness` skill to run smoke against `--repo-root .`.
```

Quick Checks
------------

1. `curl -fsS http://127.0.0.1:4000/health`
2. `curl -fsS http://127.0.0.1:4000/metrics | head`
3. `curl -fsS http://127.0.0.1:13133/`
4. `curl -fsS http://127.0.0.1:8428/api/v1/targets`
5. `curl -fsS http://127.0.0.1:10428/select/jaeger/api/services`
6. `curl -fsS http://127.0.0.1:3003/api/health`

Fixed Triage Order
------------------

1. Service `health_url`
2. Service `/metrics`
3. Application logs for `HTTP request completed` with `request_id`, `trace_id`, `span_id`
4. OTEL collector health
5. VictoriaMetrics target status and metric presence
6. VictoriaTraces service list / trace search
7. VictoriaLogs search by `service.name` and `request_id`
8. Grafana dashboards and alert state

Notes
-----

- Keep the triage order fixed so agents and humans debug the same way.
