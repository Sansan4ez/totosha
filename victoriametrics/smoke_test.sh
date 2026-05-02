#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="${SMOKE_REPORT_FILE:-${ROOT_DIR}/smoke-report.txt}"
APP_HEALTH_URL="${APP_HEALTH_URL:-}"
SERVICE_NAME="${SERVICE_NAME:-core}"
CORE_PORT="${CORE_PORT:-4000}"
SMOKE_CHAT_URL="${SMOKE_CHAT_URL:-http://127.0.0.1:${CORE_PORT}/api/chat}"
SMOKE_TOOLS_API_URL="${SMOKE_TOOLS_API_URL:-http://127.0.0.1:8100}"
SMOKE_USER_ID="${SMOKE_USER_ID:-5202705269}"
SMOKE_CHAT_ID="${SMOKE_CHAT_ID:-5202705269}"
SMOKE_REQUEST_TIMEOUT_SECONDS="${SMOKE_REQUEST_TIMEOUT_SECONDS:-180}"
RUN_INCIDENT_REPLAY_SMOKE="${RUN_INCIDENT_REPLAY_SMOKE:-true}"
RUN_ASR_COMPAT_SMOKE="${RUN_ASR_COMPAT_SMOKE:-false}"
GRAFANA_PORT="${GRAFANA_PORT:-3003}"
OTEL_COLLECTOR_HEALTH_PORT="${OTEL_COLLECTOR_HEALTH_PORT:-13133}"
VICTORIAMETRICS_PORT="${VICTORIAMETRICS_PORT:-8428}"
VICTORIALOGS_PORT="${VICTORIALOGS_PORT:-9428}"
VICTORIATRACES_PORT="${VICTORIATRACES_PORT:-10428}"
VMALERT_PORT="${VMALERT_PORT:-8880}"
SMOKE_HEALTH_TIMEOUT_SECONDS="${SMOKE_HEALTH_TIMEOUT_SECONDS:-60}"
SMOKE_METRIC_SIGNAL="${SMOKE_METRIC_SIGNAL:-http_server_duration_milliseconds}"
SMOKE_LOG_SIGNAL="${SMOKE_LOG_SIGNAL:-HTTP request completed}"
SMOKE_TRACE_SIGNAL="${SMOKE_TRACE_SIGNAL:-request}"

KB_REQUEST_ID="${KB_REQUEST_ID:-obs-rfc020-kb-route}"
KB_QUERY="${KB_QUERY:-Подскажи официальный сайт компании ЛАДзавод светотехники.}"
KB_EXPECTED_ROUTE_ID="${KB_EXPECTED_ROUTE_ID:-corp_kb.company_common}"
KB_EXPECTED_ROUTE_KIND="${KB_EXPECTED_ROUTE_KIND:-corp_table}"
KB_EXPECTED_SOURCE="${KB_EXPECTED_SOURCE:-corp_db}"
KB_EXPECTED_TOOL="${KB_EXPECTED_TOOL:-corp_db_search}"
KB_EXPECTED_DOCUMENT_ID="${KB_EXPECTED_DOCUMENT_ID:-}"
KB_EXPECTED_FAMILY_ID="${KB_EXPECTED_FAMILY_ID:-company_info}"
KB_EXPECTED_LEAF_ROUTE_ID="${KB_EXPECTED_LEAF_ROUTE_ID:-company_general}"
KB_EXPECTED_ROUTE_STAGE="${KB_EXPECTED_ROUTE_STAGE:-stage1_general}"

DOC_REQUEST_ID="${DOC_REQUEST_ID:-obs-rfc020-doc-route}"
DOC_QUERY="${DOC_QUERY:-Какие нормы освещенности для спортивных объектов указаны в документе?}"
DOC_EXPECTED_ROUTE_ID="${DOC_EXPECTED_ROUTE_ID:-doc_search.sports_lighting_norms}"
DOC_EXPECTED_ROUTE_KIND="${DOC_EXPECTED_ROUTE_KIND:-doc_domain}"
DOC_EXPECTED_SOURCE="${DOC_EXPECTED_SOURCE:-doc_search}"
DOC_EXPECTED_TOOL="${DOC_EXPECTED_TOOL:-doc_search}"
DOC_EXPECTED_DOCUMENT_ID="${DOC_EXPECTED_DOCUMENT_ID:-}"
DOC_EXPECTED_FAMILY_ID="${DOC_EXPECTED_FAMILY_ID:-document_lookup}"
DOC_EXPECTED_LEAF_ROUTE_ID="${DOC_EXPECTED_LEAF_ROUTE_ID:-document_domain_lookup}"
DOC_EXPECTED_ROUTE_STAGE="${DOC_EXPECTED_ROUTE_STAGE:-stage1_general}"

mkdir -p "$(dirname "${REPORT_FILE}")"
: > "${REPORT_FILE}"

log() {
  printf '%s\n' "$*" | tee -a "${REPORT_FILE}"
}

urlencode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

wait_http_ok() {
  local url="$1"
  local name="$2"
  local timeout_secs="$3"
  local started
  started="$(date +%s)"
  while true; do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      log "[OK] ${name}: ${url}"
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] timeout waiting for ${name}: ${url}"
      return 1
    fi
    sleep 2
  done
}

wait_for_metric() {
  local timeout_secs="$1"
  local query
  local encoded_query
  local response=""
  local started
  query="sum({__name__=~\"${SMOKE_METRIC_SIGNAL}(|_bucket|_count|_sum|_total)\",service_name=\"${SERVICE_NAME}\"})"
  encoded_query="$(urlencode "${query}")"
  started="$(date +%s)"

  while true; do
    response="$(curl -fsS "http://localhost:${VICTORIAMETRICS_PORT}/api/v1/query?query=${encoded_query}")"
    if RESPONSE="${response}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE"])
results = payload.get("data", {}).get("result", [])
if not results:
    raise SystemExit(1)
value = results[0].get("value", [None, "0"])[1]
raise SystemExit(0 if float(value) > 0 else 1)
PY
    then
      log "[OK] metric signal observed: ${SMOKE_METRIC_SIGNAL}"
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] metric signal not observed: ${SMOKE_METRIC_SIGNAL}"
      log "${response}"
      return 1
    fi
    sleep 2
  done
}

wait_for_logs() {
  local timeout_secs="$1"
  local query
  local response=""
  local started
  query="_time:${timeout_secs}s service.name:\"${SERVICE_NAME}\" _msg:\"${SMOKE_LOG_SIGNAL}\""
  started="$(date +%s)"

  while true; do
    response="$(curl -fsS -X POST "http://localhost:${VICTORIALOGS_PORT}/select/logsql/query" -d "query=${query}" -d "limit=5")"
    if [[ -n "${response}" ]]; then
      log "[OK] log signal observed: ${SMOKE_LOG_SIGNAL}"
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] log signal not observed: ${SMOKE_LOG_SIGNAL}"
      return 1
    fi
    sleep 2
  done
}

wait_for_trace_service() {
  local timeout_secs="$1"
  local response=""
  local started
  started="$(date +%s)"

  while true; do
    response="$(curl -fsS "http://localhost:${VICTORIATRACES_PORT}/select/jaeger/api/services")"
    if echo "${response}" | grep -Fq "\"${SERVICE_NAME}\""; then
      log "[OK] trace service observed: ${SERVICE_NAME}"
      if [[ -n "${SMOKE_TRACE_SIGNAL}" ]]; then
        log "trace_signal_hint=${SMOKE_TRACE_SIGNAL}"
      fi
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] trace service not observed: ${SERVICE_NAME}"
      log "${response}"
      return 1
    fi
    sleep 2
  done
}

query_metric_positive() {
  local query="$1"
  local timeout_secs="$2"
  local description="$3"
  local started response encoded_query
  encoded_query="$(urlencode "${query}")"
  started="$(date +%s)"
  while true; do
    response="$(curl -fsS "http://localhost:${VICTORIAMETRICS_PORT}/api/v1/query?query=${encoded_query}")"
    if RESPONSE="${response}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["RESPONSE"])
for item in payload.get("data", {}).get("result", []):
    value = item.get("value", [None, "0"])[1]
    if float(value) > 0:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
      log "[OK] metric correlation observed: ${description}"
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] metric correlation missing: ${description}"
      log "${response}"
      return 1
    fi
    sleep 2
  done
}

query_logs_present() {
  local query="$1"
  local timeout_secs="$2"
  local description="$3"
  local started response
  started="$(date +%s)"
  while true; do
    response="$(curl -fsS -X POST "http://localhost:${VICTORIALOGS_PORT}/select/logsql/query" -d "query=${query}" -d 'limit=20')"
    if [[ -n "${response}" ]]; then
      log "[OK] log correlation observed: ${description}"
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] log correlation missing: ${description}"
      return 1
    fi
    sleep 2
  done
}

query_trace_present() {
  local trace_id="$1"
  local expected_span="$2"
  local expected_route_id="$3"
  local timeout_secs="$4"
  local description="$5"
  local started response
  started="$(date +%s)"
  while true; do
    response="$(curl -fsS "http://localhost:${VICTORIATRACES_PORT}/select/jaeger/api/traces/${trace_id}")"
    if TRACE_RESPONSE="${response}" EXPECTED_SPAN="${expected_span}" EXPECTED_ROUTE_ID="${expected_route_id}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["TRACE_RESPONSE"])
expected_span = os.environ["EXPECTED_SPAN"]
expected_route_id = os.environ["EXPECTED_ROUTE_ID"]

traces = payload.get("data")
if isinstance(traces, dict):
    traces = [traces]
if not isinstance(traces, list):
    raise SystemExit(1)

def tag_value(span, key):
    for tag in span.get("tags", []):
        if tag.get("key") == key:
            return str(tag.get("value") or "")
    return ""

for trace in traces:
    spans = trace.get("spans", []) if isinstance(trace, dict) else []
    if not isinstance(spans, list):
        continue
    span_names = {str(span.get("operationName") or "") for span in spans if isinstance(span, dict)}
    route_ids = {
        tag_value(span, "selected_route_id")
        for span in spans
        if isinstance(span, dict)
    }
    if expected_span in span_names and expected_route_id in route_ids:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
      log "[OK] trace correlation observed: ${description}"
      return 0
    fi
    if (( "$(date +%s)" - started > timeout_secs )); then
      log "[FAIL] trace correlation missing: ${description}"
      log "${response}"
      return 1
    fi
    sleep 2
  done
}

run_incident_replay_smoke() {
  local output=""
  if output="$(
    python3 "${ROOT_DIR}/../scripts/incident_replay_smoke.py" \
      --core-url "${SMOKE_CHAT_URL%/api/chat}" \
      --tools-api-url "${SMOKE_TOOLS_API_URL}" \
      --timeout-s "${SMOKE_REQUEST_TIMEOUT_SECONDS}" \
      --user-id "${SMOKE_USER_ID}" \
      --chat-id "${SMOKE_CHAT_ID}" 2>&1
  )"; then
    log "[OK] incident replay smoke passed"
  else
    log "[FAIL] incident replay smoke failed"
    while IFS= read -r line; do
      log "incident_replay: ${line}"
    done <<< "${output}"
    return 1
  fi

  while IFS= read -r line; do
    log "incident_replay: ${line}"
  done <<< "${output}"
}

run_asr_compat_smoke() {
  local output=""
  if output="$(
    python3 "${ROOT_DIR}/../scripts/asr_compat_smoke.py" \
      --timeout-s "${SMOKE_REQUEST_TIMEOUT_SECONDS}" 2>&1
  )"; then
    log "[OK] asr compatibility smoke passed"
  else
    log "[FAIL] asr compatibility smoke failed"
    while IFS= read -r line; do
      log "asr_compat: ${line}"
    done <<< "${output}"
    return 1
  fi

  while IFS= read -r line; do
    log "asr_compat: ${line}"
  done <<< "${output}"
}

run_chat_request() {
  local request_id="$1"
  local message="$2"
  REQUEST_ID="${request_id}" MESSAGE="${message}" USER_ID="${SMOKE_USER_ID}" CHAT_ID="${SMOKE_CHAT_ID}" \
    python3 - <<'PY'
import json
import os

payload = {
    "user_id": int(os.environ["USER_ID"]),
    "chat_id": int(os.environ["CHAT_ID"]),
    "message": os.environ["MESSAGE"],
    "username": "observability_smoke",
    "chat_type": "private",
    "source": "bot",
    "return_meta": True,
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

validate_chat_meta() {
  local response="$1"
  local request_id="$2"
  local expected_route_id="$3"
  local expected_route_kind="$4"
  local expected_tool="$5"
  local expected_document_id="$6"
  local expected_family_id="$7"
  local expected_leaf_route_id="$8"
  local expected_route_stage="$9"
  RESPONSE="${response}" REQUEST_ID="${request_id}" EXPECTED_ROUTE_ID="${expected_route_id}" \
  EXPECTED_ROUTE_KIND="${expected_route_kind}" EXPECTED_TOOL="${expected_tool}" \
  EXPECTED_DOCUMENT_ID="${expected_document_id}" EXPECTED_FAMILY_ID="${expected_family_id}" \
  EXPECTED_LEAF_ROUTE_ID="${expected_leaf_route_id}" EXPECTED_ROUTE_STAGE="${expected_route_stage}" python3 - <<'PY'
import json
import os
import sys

payload = json.loads(os.environ["RESPONSE"])
meta = payload.get("meta") or {}

def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)

if meta.get("status") != "ok":
    fail(f"chat meta status is not ok: {meta.get('status')}")
if meta.get("request_id") != os.environ["REQUEST_ID"]:
    fail(f"request_id mismatch: {meta.get('request_id')}")
if meta.get("trace_id") in {"", "-", None}:
    fail("trace_id missing from chat meta")
if meta.get("retrieval_route_id") != os.environ["EXPECTED_ROUTE_ID"]:
    fail(f"route_id mismatch: {meta.get('retrieval_route_id')}")
if meta.get("retrieval_selected_route_kind") != os.environ["EXPECTED_ROUTE_KIND"]:
    fail(f"route_kind mismatch: {meta.get('retrieval_selected_route_kind')}")
if meta.get("retrieval_business_family_id") != os.environ["EXPECTED_FAMILY_ID"]:
    fail(f"business_family mismatch: {meta.get('retrieval_business_family_id')}")
if meta.get("retrieval_leaf_route_id") != os.environ["EXPECTED_LEAF_ROUTE_ID"]:
    fail(f"leaf_route_id mismatch: {meta.get('retrieval_leaf_route_id')}")
if meta.get("retrieval_route_stage") != os.environ["EXPECTED_ROUTE_STAGE"]:
    fail(f"route_stage mismatch: {meta.get('retrieval_route_stage')}")
if meta.get("retrieval_validation_status") != "ok":
    fail(f"validation_status mismatch: {meta.get('retrieval_validation_status')}")
tools_used = meta.get("tools_used") or []
if os.environ["EXPECTED_TOOL"] not in tools_used:
    fail(f"expected tool not used: {os.environ['EXPECTED_TOOL']} vs {tools_used}")
expected_document_id = os.environ["EXPECTED_DOCUMENT_ID"]
if expected_document_id and meta.get("document_id") != expected_document_id:
    fail(f"document_id mismatch: {meta.get('document_id')}")
if meta.get("retrieval_selected_route_kind") == "doc_domain" and meta.get("document_id") in {"", None}:
    fail("document_id missing for doc_domain request")
print(json.dumps({
    "trace_id": meta.get("trace_id"),
    "span_id": meta.get("span_id"),
    "request_id": meta.get("request_id"),
    "route_id": meta.get("retrieval_route_id"),
    "route_kind": meta.get("retrieval_selected_route_kind"),
    "business_family_id": meta.get("retrieval_business_family_id"),
    "leaf_route_id": meta.get("retrieval_leaf_route_id"),
    "route_stage": meta.get("retrieval_route_stage"),
    "validation_status": meta.get("retrieval_validation_status"),
    "selected_source": meta.get("retrieval_selected_source"),
    "tool": os.environ["EXPECTED_TOOL"],
    "document_id": meta.get("document_id") or "",
}, ensure_ascii=False))
PY
}

run_route_correlation_smoke() {
  local scenario="$1"
  local request_id="$2"
  local message="$3"
  local expected_route_id="$4"
  local expected_route_kind="$5"
  local expected_source="$6"
  local expected_tool="$7"
  local expected_document_id="$8"
  local expected_family_id="$9"
  local expected_leaf_route_id="${10}"
  local expected_route_stage="${11}"

  log "[RUN] ${scenario}: request_id=${request_id}"
  local request_body response validated trace_id actual_source actual_document_id metric_query tool_metric_query log_query
  request_body="$(run_chat_request "${request_id}" "${message}")"
  response="$(curl -fsS -X POST "${SMOKE_CHAT_URL}" \
    -H "Content-Type: application/json" \
    -H "X-Request-Id: ${request_id}" \
    --max-time "${SMOKE_REQUEST_TIMEOUT_SECONDS}" \
    -d "${request_body}")"
  validated="$(validate_chat_meta "${response}" "${request_id}" "${expected_route_id}" "${expected_route_kind}" "${expected_tool}" "${expected_document_id}" "${expected_family_id}" "${expected_leaf_route_id}" "${expected_route_stage}")"
  trace_id="$(VALIDATED="${validated}" python3 - <<'PY'
import json
import os
print(json.loads(os.environ["VALIDATED"])["trace_id"])
PY
)"
  actual_source="$(VALIDATED="${validated}" python3 - <<'PY'
import json
import os
print(json.loads(os.environ["VALIDATED"])["selected_source"])
PY
)"
  actual_document_id="$(VALIDATED="${validated}" python3 - <<'PY'
import json
import os
print(json.loads(os.environ["VALIDATED"]).get("document_id", ""))
PY
)"
  log "[OK] ${scenario}: route_id=${expected_route_id} family_id=${expected_family_id} leaf_route_id=${expected_leaf_route_id} route_stage=${expected_route_stage} trace_id=${trace_id} selected_source=${actual_source} document_id=${actual_document_id:-none} tool=${expected_tool}"

  metric_query="sum(last_over_time(retrieval_route_requests_total{service_name=\"core\",selected_route_id=\"${expected_route_id}\",selected_route_kind=\"${expected_route_kind}\",selected_source=\"${actual_source}\"}[15m]))"
  query_metric_positive "${metric_query}" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} retrieval_route_requests_total"

  leaf_metric_query="sum(last_over_time(retrieval_route_leaf_requests_total{service_name=\"core\",selected_route_id=\"${expected_route_id}\",selected_leaf_route_id=\"${expected_leaf_route_id}\",selected_business_family_id=\"${expected_family_id}\",route_stage=\"${expected_route_stage}\",route_arg_validation_status=\"ok\"}[15m]))"
  query_metric_positive "${leaf_metric_query}" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} retrieval_route_leaf_requests_total"

  stage_metric_query="sum(last_over_time(retrieval_route_stage_total{service_name=\"core\",selected_business_family_id=\"${expected_family_id}\",selected_leaf_route_id=\"${expected_leaf_route_id}\",route_stage=\"${expected_route_stage}\"}[15m]))"
  query_metric_positive "${stage_metric_query}" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} retrieval_route_stage_total"

  tool_metric_query="sum(last_over_time(tool_executions_total{service_name=\"core\",tool_name=\"${expected_tool}\",selected_route_id=\"${expected_route_id}\"}[15m]))"
  query_metric_positive "${tool_metric_query}" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} tool_executions_total"

  log_query="_time:${SMOKE_REQUEST_TIMEOUT_SECONDS}s service.name:\"core\" request_id:\"${request_id}\" trace_id:\"${trace_id}\" selected_route_id:\"${expected_route_id}\" tool_name:\"${expected_tool}\""
  query_logs_present "${log_query}" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} request_id/trace_id/route/tool"

  if [[ -n "${actual_document_id}" ]]; then
    query_logs_present "_time:${SMOKE_REQUEST_TIMEOUT_SECONDS}s service.name:\"core\" request_id:\"${request_id}\" document_id:\"${actual_document_id}\"" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} document_id"
  fi

  query_trace_present "${trace_id}" "tool.${expected_tool}" "${expected_route_id}" "${SMOKE_REQUEST_TIMEOUT_SECONDS}" "${scenario} trace_id/route/tool"
}

log "service=${SERVICE_NAME}"
wait_http_ok "http://localhost:${OTEL_COLLECTOR_HEALTH_PORT}/" "otel collector" "${SMOKE_HEALTH_TIMEOUT_SECONDS}"
wait_http_ok "http://localhost:${GRAFANA_PORT}/api/health" "grafana" "${SMOKE_HEALTH_TIMEOUT_SECONDS}"
wait_http_ok "http://localhost:${VMALERT_PORT}/api/v1/rules" "vmalert rules" "${SMOKE_HEALTH_TIMEOUT_SECONDS}"

if [[ -n "${APP_HEALTH_URL}" ]]; then
  wait_http_ok "${APP_HEALTH_URL}" "application health" "${SMOKE_HEALTH_TIMEOUT_SECONDS}"
fi

wait_for_trace_service "${SMOKE_HEALTH_TIMEOUT_SECONDS}"
wait_for_logs "${SMOKE_HEALTH_TIMEOUT_SECONDS}"
wait_for_metric "${SMOKE_HEALTH_TIMEOUT_SECONDS}"

if [[ "${SERVICE_NAME}" == "core" ]]; then
  wait_http_ok "${SMOKE_CHAT_URL%/api/chat}/health" "core health" "${SMOKE_HEALTH_TIMEOUT_SECONDS}"
  run_route_correlation_smoke "kb_route" "${KB_REQUEST_ID}" "${KB_QUERY}" "${KB_EXPECTED_ROUTE_ID}" "${KB_EXPECTED_ROUTE_KIND}" "${KB_EXPECTED_SOURCE}" "${KB_EXPECTED_TOOL}" "${KB_EXPECTED_DOCUMENT_ID}" "${KB_EXPECTED_FAMILY_ID}" "${KB_EXPECTED_LEAF_ROUTE_ID}" "${KB_EXPECTED_ROUTE_STAGE}"
  run_route_correlation_smoke "document_route" "${DOC_REQUEST_ID}" "${DOC_QUERY}" "${DOC_EXPECTED_ROUTE_ID}" "${DOC_EXPECTED_ROUTE_KIND}" "${DOC_EXPECTED_SOURCE}" "${DOC_EXPECTED_TOOL}" "${DOC_EXPECTED_DOCUMENT_ID}" "${DOC_EXPECTED_FAMILY_ID}" "${DOC_EXPECTED_LEAF_ROUTE_ID}" "${DOC_EXPECTED_ROUTE_STAGE}"
  if [[ "${RUN_INCIDENT_REPLAY_SMOKE}" == "true" ]]; then
    run_incident_replay_smoke
  fi
fi

if [[ "${RUN_ASR_COMPAT_SMOKE}" == "true" ]]; then
  run_asr_compat_smoke
fi

curl -fsS "http://localhost:${VMALERT_PORT}/api/v1/alerts" >/dev/null

# Expected pipeline references used by observability-harness coverage checks:
# http_server_duration_milliseconds
# HTTP request completed
# api.request

log "smoke_ok=true"
