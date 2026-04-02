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

When rebuilding services, keep the same compose pair:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --build core tools-api proxy
```

If you rebuild only `docker-compose.yml`, OTEL env vars disappear from recreated containers and logs fall back to `trace_id=-`.

3. Run harness smoke orchestration:

```bash
Use the installed `observability-harness` skill to run smoke against `--repo-root .`.
```

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
3. Application logs for `HTTP request completed` with `request_id`, `trace_id`, `span_id`
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

Expected result: one `request_id` across `core`, `tools-api`, and `proxy` with the same `trace_id`.

3. Open the corresponding trace in VictoriaTraces or Jaeger API.

```bash
curl -fsS 'http://127.0.0.1:10428/select/jaeger/api/services'
```

Look for spans:

- `tool.corp_db_search`
- `corp_db.lamp_filters`
- `corp_db.hybrid_primary`
- `corp_db.embedding`
- `corp_db.token_fallback`
- `corp_db.alias_fallback`

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

- Keep the triage order fixed so agents and humans debug the same way.
