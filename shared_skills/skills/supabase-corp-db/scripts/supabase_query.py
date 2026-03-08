#!/usr/bin/env python3
"""Build (and optionally run) Supabase PostgREST GET URLs.

Examples:
  python supabase_query.py \
    --path catalog_lamps \
    --param "select=id,name,power_consumption_w" \
    --param "power_consumption_w=gte.25" \
    --param "order=name.asc" \
    --param "limit=5" --param "offset=0" \
    --dry-run

  SUPABASE_KEY=... python supabase_query.py --path catalog_lamps --param "select=id,name" --run
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request


def _get_key() -> str:
    key = os.getenv("SUPABASE_KEY") or ""
    if not key:
        raise SystemExit("ERROR: SUPABASE_KEY is not set")
    return key


def _jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _refuse_service_role(key: str) -> None:
    payload = _jwt_payload(key)
    if payload.get("role") == "service_role" and os.getenv("ALLOW_SUPABASE_SERVICE_ROLE", "") != "1":
        raise SystemExit(
            "ERROR: Refusing to use a service_role key. Put the anon key into SUPABASE_KEY instead "
            "(or set ALLOW_SUPABASE_SERVICE_ROLE=1 to override)."
        )


def build_url(base: str, path: str, params: list[str]) -> str:
    base = base.rstrip("/")
    path = path.lstrip("/")

    # Params are provided as raw k=v (may contain commas, parentheses, dots).
    # We encode key and value separately but keep PostgREST punctuation unescaped.
    safe_value = ",().!:_-*/"  # keep common PostgREST chars readable
    qp = []
    for p in params:
        if "=" not in p:
            raise ValueError(f"Param must be k=v, got: {p}")
        k, v = p.split("=", 1)
        k_enc = urllib.parse.quote(k, safe="._-")
        v_enc = urllib.parse.quote(v, safe=safe_value)
        qp.append(f"{k_enc}={v_enc}")

    qs = "&".join(qp)
    return f"{base}/{path}" + (f"?{qs}" if qs else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("SUPABASE_REST_URL", "https://api.llm-studio.pro/rest/v1"))
    ap.add_argument("--path", required=True, help="table name (e.g. catalog_lamps) or rpc/ru_fts")
    ap.add_argument("--param", action="append", default=[], help="k=v query param; repeatable")
    ap.add_argument("--dry-run", action="store_true", help="print URL only")
    ap.add_argument("--run", action="store_true", help="execute HTTP GET and print JSON")
    args = ap.parse_args()

    url = build_url(args.base, args.path, args.param)
    print(url)

    if args.run:
        key = _get_key()
        _refuse_service_role(key)

        req = urllib.request.Request(url)
        req.add_header("apikey", key)
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req) as resp:
            data = resp.read().decode("utf-8")
        try:
            parsed = json.loads(data)
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print(data)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
