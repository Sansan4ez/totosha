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

2. Start the application stack on the default supported path:

```bash
docker compose up -d
```

This starts `core`, `bot`, `proxy`, `tools-api`, `scheduler`, and `corp-db-worker` with OTEL exporter wiring by default.

3. If you need localhost app ports for direct smoke or curl-based triage, apply the port-binding overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

When rebuilding services, keep the base app command as the default:

```bash
docker compose up -d --build core tools-api proxy bot scheduler
```

If you also need host-local app ports after a rebuild, re-apply the overlay once:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d core tools-api proxy bot scheduler
```

4. Run harness smoke orchestration:

```bash
Use the installed `observability-harness` skill to run smoke against `--repo-root .`.
```

The shared smoke now includes the `totosha-pfit.7` replay layer on the `core` path:

- `bench/golden/incident-pfit7.jsonl` direct-tool replays for the three incident questions
- RFC-026 live schema drift checks from `scripts/doctor.py`
- `/api/chat` route assertions for the broad series questions

Run it directly when you need a focused post-remediation check:

```bash
python3 scripts/incident_replay_smoke.py
```

For RFC-020 correlation smoke on the local stack, the `core` service smoke now sends two fresh requests:

1. KB route query for `corp_kb.company_common`
2. Document-domain query for `doc_search.sports_lighting_norms`

The smoke fails unless each request is visible in:

- VictoriaMetrics via `retrieval_route_requests_total` and `tool_executions_total`
- VictoriaLogs via one fresh `request_id` carrying `trace_id`, `selected_route_id`, and `tool_name`
- VictoriaTraces via the exact `trace_id` returned by `core /api/chat`

Quick Checks
------------

1. `curl -fsS http://127.0.0.1:4000/health`
2. `curl -fsS http://127.0.0.1:4000/metrics | head`
3. `curl -fsS http://127.0.0.1:13133/`
4. `curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=up'`
5. `curl -fsS http://127.0.0.1:10428/select/jaeger/api/services`
6. `curl -fsS http://127.0.0.1:3003/api/health`

Note: `http://127.0.0.1:8428/api/v1/targets` may stay empty in this topology. Prometheus scraping is executed by the OTEL collector, and VictoriaMetrics receives the exported series rather than scraping app targets directly.

Fixed Triage Order
------------------

1. Service `health_url`
2. Service `/metrics`
3. Application logs for `HTTP request completed` with `request_id`, `trace_id`, `span_id`, `selected_route_id`, and `tool_name`
4. OTEL collector health
5. VictoriaMetrics `up` status and metric presence
6. VictoriaTraces service list / trace search
7. VictoriaLogs search by `service.name` and `request_id`
8. Grafana dashboards and alert state

For metric-side health, use these two checks together:

```bash
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=up'
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=sum%20by%20(service_name)(http_server_duration_milliseconds_count)'
```

Expected result: `up{service_name="core|tools-api|proxy|scheduler|bot"}` converges to `1`, and request counters are present for the services that already served traffic.

For retrieval correlation, use these checks after a fresh routed request:

```bash
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=sum%20by%20%28selected_route_id%2Cselected_route_kind%2Cselected_source%29%20%28increase%28retrieval_route_requests_total%7Bservice_name%3D%22core%22%7D%5B15m%5D%29%29'
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=sum%20by%20%28tool_name%2Cselected_route_id%29%20%28increase%28tool_executions_total%7Bservice_name%3D%22core%22%7D%5B15m%5D%29%29'
```

Expected result: the fresh request increments the expected `selected_route_id` and `tool_name`.

ASR compatibility smoke
-----------------------

Use this when the incident path involves `proxy -> cli-proxy-api /transcribe`.

```bash
CLIPROXY_MGMT_KEY=... python3 scripts/asr_compat_smoke.py
```

What it checks:

- live `POST /transcribe` through project `proxy`
- `cli-proxy-api /v0/management/transcribe-health`
- `backend_mode=chatgpt_compat`
- challenge/error-rate windows for the last 5m and 30m
- degraded credential count

If you want the shared smoke harness to include it in one pass:

```bash
RUN_ASR_COMPAT_SMOKE=true CLIPROXY_MGMT_KEY=... ./victoriametrics/smoke_test.sh
```

Corp DB Latency Triage
----------------------

Use this workflow for slow catalog retrieval and empty `corp_db_search` errors.

1. Reproduce the request with a fixed `X-Request-Id`.

```bash
curl -fsS -X POST http://127.0.0.1:4000/api/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Request-Id: obs-rfc4-core-2' \
  -d '{"message":"Подбери светильник мощностью 709 Вт, с номинальным напряжением 220 В, рабочим диапазоном 154-308 В и гарантией 5 лет. Назови модель.","user_id":5202705269,"chat_id":5202705269,"return_meta":true}'
```

2. Find the request in VictoriaLogs.

```bash
curl -fsS -X POST 'http://127.0.0.1:9428/select/logsql/query' \
  -d 'query=_time:1h request_id:obs-rfc4-core-2' \
  -d 'limit=20'
```

Expected result: one `request_id` across `core`, `tools-api`, and `proxy` with the same `trace_id`. For routed requests, the same log record set should expose `selected_route_id`, `selected_route_kind`, `selected_source`, and `tool_name`.

3. Open the corresponding trace in VictoriaTraces or Jaeger API.

```bash
curl -fsS 'http://127.0.0.1:10428/select/jaeger/api/services'
curl -fsS 'http://127.0.0.1:10428/select/jaeger/api/traces/<trace_id>'
```

Look for spans:

- `tool.corp_db_search`
- `tool.doc_search`
- `corp_db.lamp_filters`
- `corp_db.hybrid_primary`
- `corp_db.embedding`
- `corp_db.token_fallback`
- `corp_db.alias_fallback`

For RFC-020 correlation, confirm span tags include:

- `selected_route_id`
- `selected_route_family`
- `selected_route_kind`
- `tool_name`
- `knowledge_route_id` or `document_id`

Interpretation:

- `lamp_filters` without `embedding` or `token_fallback` means the fast path worked.
- `embedding` means semantic fallback was required.
- `token_fallback` or `alias_fallback` on explicit lamp filters is a sign that routing regressed.

4. Check route-level latency in VictoriaMetrics.

```bash
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=histogram_quantile%280.95%2C%20sum%20by%20%28le%2Cservice_name%2Croute%2Cmethod%2Cstatus%29%20%28rate%28http_server_duration_milliseconds_bucket%7Bservice_name%3D~%22core%7Ctools-api%22%2Croute%3D~%22%2Fapi%2Fchat%7C%2Fcorp-db%2Fsearch%22%7D%5B15m%5D%29%29%29'
```

5. Attribute time inside `corp_db_search`.

```bash
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=histogram_quantile%280.95%2C%20sum%20by%20%28le%2Ckind%2Cprofile%2Cstatus%29%20%28rate%28corp_db_search_duration_milliseconds_bucket%5B15m%5D%29%29%29'
curl -fsS 'http://127.0.0.1:8428/api/v1/query?query=increase%28corp_db_search_phase_duration_milliseconds_count%5B15m%5D%29'
```

Reference acceptance after RFC-004 rollout:

- `tools-api POST /corp-db/search` p95 around `2.4s`
- `corp_db_search_duration_milliseconds{kind="hybrid_search",profile="entity_resolver"}` p95 around `975 ms`
- `corp_db_search_duration_milliseconds{kind="lamp_filters",profile="candidate_generation"}` p95 around `487.5 ms`

6. Interpret transport errors from `core`.

`core` now returns exception class and timeout budget, for example:

```text
corp_db_search error: TimeoutError: request timed out; timeout_budget={connect:5.0s,read:40.0s,total:45.0s}
```

If the error message is empty or lacks the budget, first verify the running container actually includes the updated build.

Notes
-----

- Proxy-specific user-path alerts now track:
  - `ProxyUserPathHigh5xxRatio`
  - `ProxyUserPathHighP95Latency`
- Grafana now includes dedicated panels for:
  - `Incident Route Traffic`
  - `Proxy User Path p95`
  - `Proxy User Path 5xx Ratio`
- Keep the triage order fixed so agents and humans debug the same way.
- `docker-compose.observability.yml` is now a port-binding overlay only. Losing the overlay no longer drops OTEL env, but it does remove the localhost service bindings used by several manual smoke commands.
