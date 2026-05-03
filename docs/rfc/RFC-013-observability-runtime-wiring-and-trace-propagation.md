# RFC-013: Observability Runtime Wiring And Trace Propagation

Status
------

Implemented

Date
----

2026-04-08

Last updated
------------

2026-05-03

Implementation note
-------------------

This RFC is now implemented in the repository/runtime. The core outcomes are visible in the base OTEL wiring, cross-service `traceparent` and `X-Request-Id` propagation, structured `HTTP request completed` correlation logs, and Victoria smoke validation artifacts. The body below is kept as the original proposal/problem statement for historical context.

Summary
-------

The Victoria/OTEL stack is running, but the current application deployment is only partially wired into it.

Today:

- metrics are present because `otel-collector` scrapes `/metrics` endpoints directly;
- historical OTLP logs/traces exist in Victoria from earlier runs;
- current `bot`, `core`, `proxy`, `tools-api`, and `scheduler` containers are started without `OTEL_*` environment variables from `docker-compose.observability.yml`;
- current cross-service calls propagate only `X-Request-Id`, not `traceparent`.

As a result, the operator sees a misleading split-brain state:

- dashboards and healthchecks look alive;
- service stdout shows `trace_id=- span_id=-` for current requests;
- current requests are not exportable as end-to-end traces/logs in Victoria;
- request correlation is incomplete and relies on ad hoc `request_id`.

Problem Statement
-----------------

The repository already contains the intended observability topology:

- `victoriametrics`, `victorialogs`, `victoriatraces`, `otel-collector`, `grafana`, `vmalert`;
- OTEL-enabled service code in `bot`, `core`, `proxy`, `tools-api`, `scheduler`;
- `docker-compose.observability.yml` with the required `OTEL_*` env wiring.

However, the runtime currently uses `docker compose up -d --build` on the base compose only. This starts services without the OTEL exporter configuration.

Observed on 2026-04-08:

- `otel-collector` health endpoint is up on `http://localhost:13133/`;
- VictoriaMetrics query for `http_server_requests_total{service="core"}` returns fresh data;
- `core`, `bot`, `proxy` containers do not have `OTEL_EXPORTER_OTLP_ENDPOINT` in env;
- recent request ids from the Telegram incident are absent in VictoriaLogs;
- current stdout logs from live services show `trace_id=- span_id=-`;
- only old OTLP log entries are visible in VictoriaLogs.

Root Causes
-----------

### 1. Deployment gap: observability override exists but is not part of the default runtime

`docker-compose.observability.yml` contains the correct OTEL settings, but the active containers were started from the base compose alone.

This means:

- `setup_observability()` runs without `OTLP_ENDPOINT`;
- tracer provider and OTLP log exporter are not initialized;
- log filter cannot attach valid trace/span ids for current requests.

### 2. Metrics work through a different path, hiding the failure

`otel-collector` scrapes `/metrics` from service endpoints through its Prometheus receiver.

So metrics remain healthy even when:

- OTLP logs are not exported;
- OTLP traces are not exported;
- distributed tracing is effectively disabled.

This made the stack look healthy while current request-level observability was broken.

### 3. Trace propagation is incomplete even if OTEL is enabled

Current inter-service calls pass `X-Request-Id`, but not `traceparent`.

Examples:

- `bot/api.py` -> `core /api/chat`
- `core/agent.py` -> `proxy /v1/chat/completions`
- `core/tools/corp_db.py` -> `tools-api /corp-db/search`
- `core/tools/__init__.py` -> tools-api discovery/load paths

This means even a corrected OTEL deployment would still produce fragmented traces across services.

### 4. `cli-proxy-api` is outside the current observability contract

`cli-proxy-api` is a critical hop in the LLM chain:

- `core` -> `proxy` -> `cli-proxy-api` -> provider

But it has no project-level OTEL integration, no shared request-id convention, and no guaranteed correlation fields in downstream logs/metrics.

Goals
-----

- Make current requests appear in VictoriaLogs and VictoriaTraces after every normal deployment.
- Ensure `bot`, `core`, `proxy`, `tools-api`, `scheduler` always start with OTEL exporter config in production and local operator flows.
- Propagate `traceparent` and `tracestate` end-to-end across internal HTTP hops.
- Keep `X-Request-Id` as an operator-friendly correlation id, but stop relying on it as the only linkage.
- Add explicit smoke coverage that validates fresh metrics, fresh logs, and fresh traces from a synthetic request.
- Ensure observability is sufficient to debug routing and retrieval incidents, not just transport incidents.

Non-Goals
---------

- Replacing Victoria stack.
- Replacing `cli-proxy-api`.
- Reworking all logging formats beyond what is needed for trace linkage.

Target State
------------

### Deployment

Normal operator startup uses a single documented command that always includes observability wiring, for example:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --build
```

Alternative acceptable outcome:

- merge the OTEL env wiring into the base compose for services that must always be observable.

### Propagation

Every internal HTTP client injects:

- `traceparent`
- `tracestate` when present
- `X-Request-Id`

Every HTTP server extracts:

- W3C trace context from headers
- `X-Request-Id` for operator correlation

### Verification

A synthetic request must yield:

- one visible request in metrics;
- fresh log records in VictoriaLogs with non-empty `trace_id`;
- at least one end-to-end trace visible in VictoriaTraces/Jaeger API;
- matching `trace_id` across `bot`, `core`, and `proxy` for the same request.
- enough correlated fields to reconstruct routing decisions for one `company_fact` request and one `corp_db` tool call.

Proposed Changes
----------------

### A. Fix deployment wiring

Choose one of:

1. Make `docker-compose.observability.yml` mandatory in all documented deploy/restart flows.
2. Merge the OTEL env block into base `docker-compose.yml` for core services.

Recommendation:

- keep Victoria stack as a separate compose;
- move service-side `OTEL_*` env into base `docker-compose.yml`;
- keep only stack containers in the observability compose.

This removes the easiest operator mistake: starting app services without OTEL exporter config.

### B. Add trace context propagation for internal HTTP clients

Use OpenTelemetry propagation on every internal client request.

Required call sites:

- `bot/api.py`
- `core/agent.py`
- `core/tools/corp_db.py`
- `core/tools/__init__.py`
- any other internal HTTP client touching `core`, `proxy`, `tools-api`, `scheduler`

Implementation pattern:

```python
from opentelemetry.propagate import inject

headers = {}
inject(headers)
headers["X-Request-Id"] = request_id
```

### C. Keep request id, but define its role clearly

`X-Request-Id` stays for:

- operator grep;
- benchmark case correlation;
- manual incident triage.

But documentation must state:

- `request_id` is not a replacement for distributed tracing;
- trace linkage must rely on `traceparent`.

### D. Add observability smoke for fresh telemetry

Current smoke proves that infrastructure is alive.

It must additionally prove that the application is exporting fresh telemetry now.

Add smoke steps:

1. Generate a synthetic request with a fixed `X-Request-Id`.
2. Query VictoriaMetrics for a counter increment.
3. Query VictoriaLogs for that `request_id`.
4. Query VictoriaTraces/Jaeger API for a recent trace from the target service.
5. Fail if logs/traces are absent or have empty trace ids.

Recommended synthetic requests:

1. health-style lightweight request for transport validation;
2. one real `POST /api/chat` company-fact request such as `Подскажи контакты компании.` to validate:
   - `bot -> core` propagation;
   - `core -> tools-api` propagation;
   - routing metadata visibility;
   - tool-span visibility for `corp_db_search`.

### E. Bring `cli-proxy-api` into the observability boundary

Minimum acceptable scope:

- ensure `proxy` logs request id and upstream duration for `cli-proxy-api` calls;
- document `cli-proxy-api` as an uninstrumented boundary;
- include it in incident runbooks.

Preferred scope:

- add request-id forwarding to `cli-proxy-api`;
- if supported, add OTEL instrumentation or at least structured correlation logging around upstream requests.

Acceptance Criteria
-------------------

1. Fresh deployments of `bot`, `core`, `proxy`, `tools-api`, `scheduler` contain `OTEL_EXPORTER_OTLP_ENDPOINT` in container env.
2. A new `POST /api/chat` request produces non-empty `trace_id` and `span_id` in service logs.
3. The same request can be found in VictoriaLogs by `request_id`.
4. The same request produces at least one trace in VictoriaTraces.
5. Cross-service logs for the same request share one `trace_id` across `bot`, `core`, and `proxy`.
6. Operator docs no longer instruct startup flows that omit observability wiring.
7. For a synthetic company-fact request, operators can see correlated routing fields such as selected source, route id, and guardrail hits in the exported logs for the same request.

Rollout Plan
------------

1. Update compose/runtime wiring.
2. Add `traceparent` propagation to internal clients.
3. Add smoke checks for fresh telemetry.
4. Validate with one synthetic Telegram-equivalent request.
5. Update operations runbook.

Risks
-----

- If OTEL is enabled without propagation, operators may still see fragmented traces and assume the problem is solved.
- If only logs are fixed but traces are not, cross-service incident debugging remains expensive.
- If only compose docs are updated and not the base runtime, the system will regress on the next ad hoc restart.

Open Questions
--------------

- Should service-side OTEL env be merged permanently into base compose, or should startup be centralized into a wrapper/Make target?
- Can `cli-proxy-api` be instrumented directly, or should it remain an explicitly uninstrumented external boundary with request-id-only correlation?
