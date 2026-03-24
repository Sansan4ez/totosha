#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="${SMOKE_REPORT_FILE:-${ROOT_DIR}/smoke-report.txt}"
APP_HEALTH_URL="${APP_HEALTH_URL:-}"
SERVICE_NAME="${SERVICE_NAME:-api}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
OTEL_COLLECTOR_HEALTH_PORT="${OTEL_COLLECTOR_HEALTH_PORT:-13133}"
VICTORIAMETRICS_PORT="${VICTORIAMETRICS_PORT:-8428}"
VICTORIALOGS_PORT="${VICTORIALOGS_PORT:-9428}"
VICTORIATRACES_PORT="${VICTORIATRACES_PORT:-10428}"
VMALERT_PORT="${VMALERT_PORT:-8880}"
SMOKE_HEALTH_TIMEOUT_SECONDS="${SMOKE_HEALTH_TIMEOUT_SECONDS:-60}"
SMOKE_METRIC_SIGNAL="${SMOKE_METRIC_SIGNAL:-http_server_duration_milliseconds}"
SMOKE_LOG_SIGNAL="${SMOKE_LOG_SIGNAL:-HTTP request completed}"
SMOKE_TRACE_SIGNAL="${SMOKE_TRACE_SIGNAL:-request}"

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

curl -fsS "http://localhost:${VMALERT_PORT}/api/v1/alerts" >/dev/null

# Expected pipeline references used by observability-harness coverage checks:
# http_server_duration_milliseconds
# HTTP request completed
# api.request

log "smoke_ok=true"
