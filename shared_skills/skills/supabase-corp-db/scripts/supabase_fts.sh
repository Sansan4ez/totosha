#!/usr/bin/env bash
set -euo pipefail

# RPC wrapper for ru_fts() with safe URL encoding.
# Usage:
#   SUPABASE_KEY=... ./supabase_fts.sh portfolio category_name "нефтегазовый комплекс" \
#     "id,name,url,image" "name DESC" 5 0

BASE_URL="${SUPABASE_REST_URL:-https://api.llm-studio.pro/rest/v1}"
KEY="${SUPABASE_KEY:-}"

if [[ -z "${KEY}" ]]; then
  echo "ERROR: SUPABASE_KEY is not set" >&2
  exit 1
fi

# Refuse service_role keys by default (public bot safety).
if command -v python3 >/dev/null 2>&1; then
  python3 - "${KEY}" <<'PY'
import base64, json, os, sys
tok = sys.argv[1]
if os.getenv("ALLOW_SUPABASE_SERVICE_ROLE") == "1":
  raise SystemExit(0)
parts = tok.split(".")
if len(parts) < 2:
  raise SystemExit(0)
payload = parts[1] + "=" * (-len(parts[1]) % 4)
try:
  data = base64.urlsafe_b64decode(payload.encode("utf-8"))
  obj = json.loads(data.decode("utf-8"))
  if obj.get("role") == "service_role":
    print("ERROR: Refusing to use a service_role key. Use anon key in SUPABASE_KEY instead.", file=sys.stderr)
    raise SystemExit(2)
except Exception:
  pass
PY
fi

TABLE="${1:-}"; COL="${2:-}"; QUERY="${3:-}"
SELECT_COLS="${4:-id,name,url}"; ORDER_BY="${5:-}"; LIMIT_ROWS="${6:-5}"; OFFSET_ROWS="${7:-0}"

if [[ -z "${TABLE}" || -z "${COL}" || -z "${QUERY}" ]]; then
  echo "Usage: $0 <table> <search_column> <search_query> [select_cols] [order_by] [limit_rows] [offset_rows]" >&2
  exit 1
fi

# python for URL encoding (available in this environment)
enc() {
  python3 - "$1" <<'PY'
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=''))
PY
}

p_table_name="$(enc "$TABLE")"
p_search_column="$(enc "$COL")"
p_search_query="$(enc "$QUERY")"
p_select_columns="$(enc "$SELECT_COLS")"

QS="p_table_name=${p_table_name}&p_search_column=${p_search_column}&p_search_query=${p_search_query}&p_select_columns=${p_select_columns}&p_limit_rows=${LIMIT_ROWS}&p_offset_rows=${OFFSET_ROWS}"

if [[ -n "${ORDER_BY}" ]]; then
  p_order_by="$(python3 - "${ORDER_BY}" <<'PY'
import sys, urllib.parse
# order_by must keep commas/underscores; spaces must become %20
print(urllib.parse.quote(sys.argv[1], safe=',._'))
PY
)"
  QS="${QS}&p_order_by=${p_order_by}"
fi

URL="${BASE_URL%/}/rpc/ru_fts?${QS}"

curl -sS \
  -H "apikey: ${KEY}" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Accept: application/json" \
  "$URL"
