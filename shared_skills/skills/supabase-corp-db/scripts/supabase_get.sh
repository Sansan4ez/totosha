#!/usr/bin/env bash
set -euo pipefail

# Generic GET wrapper for Supabase PostgREST.
# Usage:
#   SUPABASE_KEY=... ./supabase_get.sh catalog_lamps \
#     "select=id,name,power_consumption_w" \
#     "power_consumption_w=gte.25" \
#     "order=name.asc" \
#     "limit=5" "offset=0"

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
    print("ERROR: Refusing to use a service_role key. Put the anon key into SUPABASE_KEY instead.", file=sys.stderr)
    raise SystemExit(2)
except Exception:
  pass
PY
fi

TABLE="${1:-}"
shift || true
if [[ -z "${TABLE}" ]]; then
  echo "Usage: $0 <table-or-path> [param ...]" >&2
  exit 1
fi

# params are passed as already URL-safe (encoded) k=v fragments.
# If values contain spaces/Cyrillic, prefer supabase_query.py (it encodes values correctly).
QS=""
for p in "$@"; do
  if [[ -z "$QS" ]]; then QS="?$p"; else QS="$QS&$p"; fi
done

URL="${BASE_URL%/}/${TABLE}${QS}"

curl -sS \
  -H "apikey: ${KEY}" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Accept: application/json" \
  "$URL"
