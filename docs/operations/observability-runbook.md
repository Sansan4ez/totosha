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

2. Start the application stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.observability.yml up -d
```

3. Run harness smoke orchestration:

```bash
Use the installed `observability-harness` skill to run smoke against `--repo-root .`.
```

Fixed Triage Order
------------------

1. Service `health_url`
2. Application logs
3. OTEL collector health
4. VictoriaTraces
5. VictoriaLogs
6. VictoriaMetrics
7. Grafana dashboards and alert state

Notes
-----

- Keep the triage order fixed so agents and humans debug the same way.
