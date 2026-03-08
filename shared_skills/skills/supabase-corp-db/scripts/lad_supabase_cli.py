#!/usr/bin/env python3
"""LAD Supabase corporate DB helper (scenario-driven).

Requires:
  export SUPABASE_KEY=...   (use anon/public key for public access)
Optional:
  export SUPABASE_REST_URL=https://api.llm-studio.pro/rest/v1

Examples:
  # 1) Exact lamp name → characteristics + documents
  ./lad_supabase_cli.py lamp exact --name "LAD LED LINE-10-15B"

  # 2) Fuzzy lamp name → suggest candidates
  ./lad_supabase_cli.py lamp suggest --query "LINE 10 15" --limit 5

  # 3) Lookup by ETM/ORACL code → lamp mapping
  ./lad_supabase_cli.py sku by-code --etm VEGA10143
  ./lad_supabase_cli.py sku by-code --oracl 316463

  # 4) Portfolio objects by sphere
  ./lad_supabase_cli.py portfolio by-sphere --sphere "Промышленное освещение"

  # 5) Categories suitable for sphere
  ./lad_supabase_cli.py sphere categories --sphere "Промышленное освещение"

  # 6) Portfolio examples for given category_name
  ./lad_supabase_cli.py category portfolio --category "LAD LED LINE-OZ"

Notes:
- Uses small defaults (limit=5, offset=0).
- For text matching, prefers rpc/ru_fts when appropriate.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Iterable


DEFAULT_BASE = os.getenv("SUPABASE_REST_URL", "https://api.llm-studio.pro/rest/v1")

def _get_key() -> str:
    key = os.getenv("SUPABASE_KEY") or ""
    if not key:
        raise SystemExit("ERROR: SUPABASE_KEY is not set")
    return key


def _jwt_payload(token: str) -> dict[str, Any]:
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


def _headers() -> dict[str, str]:
    key = _get_key()
    _refuse_service_role(key)
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def _quote_kv(k: str, v: str) -> str:
    # Keep PostgREST punctuation readable.
    safe_value = ",().!:_-*/"  # common PostgREST chars
    return f"{urllib.parse.quote(k, safe='._-')}={urllib.parse.quote(v, safe=safe_value)}"


def build_url(path: str, params: dict[str, str] | Iterable[tuple[str, str]] | None = None, base: str = DEFAULT_BASE) -> str:
    base = base.rstrip("/")
    path = path.lstrip("/")

    if params is None:
        return f"{base}/{path}"

    if isinstance(params, dict):
        items = list(params.items())
    else:
        items = list(params)

    qs = "&".join(_quote_kv(k, v) for k, v in items)
    return f"{base}/{path}?{qs}" if qs else f"{base}/{path}"


def ru_fts(
    table: str,
    column: str,
    query: str,
    select_cols: str,
    order_by: str | None,
    limit_rows: int,
    offset_rows: int,
    base: str = DEFAULT_BASE,
) -> Any:
    params: list[tuple[str, str]] = [
        ("p_table_name", table),
        ("p_search_column", column),
        ("p_search_query", query),
        ("p_select_columns", select_cols),
        ("p_limit_rows", str(limit_rows)),
        ("p_offset_rows", str(offset_rows)),
    ]
    if order_by:
        params.append(("p_order_by", order_by))
    url = build_url("rpc/ru_fts", params, base=base)
    return _get_json(url)


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _prompt_pick(candidates: list[dict[str, Any]]) -> int:
    # Print numbered list to stderr so JSON output (if any) stays clean.
    for i, c in enumerate(candidates):
        cid = c.get("id")
        name = c.get("name")
        url = c.get("url")
        sys.stderr.write(f"[{i}] id={cid} | {name}\n")
        if url:
            sys.stderr.write(f"     {url}\n")
    sys.stderr.write("Enter number (or blank to cancel): ")
    sys.stderr.flush()

    s = sys.stdin.readline().strip()
    if not s:
        raise SystemExit("Cancelled")
    try:
        i = int(s)
    except ValueError:
        raise SystemExit("Invalid number")
    if i < 0 or i >= len(candidates):
        raise SystemExit("Index out of range")
    return i


# --- Scenario helpers ---

DOC_FIELDS = [
    "booklet_url",
    "drawing_url",
    "passport_url",
    "certificate_url",
    "ies_url",
    "file_package_url",
    "image_url",
    "diffuser_url",
]

TECH_FIELDS = [
    "luminous_flux_lm",
    "beam_angle",
    "power_consumption_w",
    "color_temperature_k",
    "color_rendering_index",
    "power_factor",
    "climatic_execution_type",
    "operating_temperature_range",
    "dust_and_water_protection_class",
    "electric_shock_protection_class",
    "nominal_voltage_v",
    "mounting_type",
    "dimensions_mm",
    "weight_kg",
    "warranty_period_years",
]


def lamp_exact(name: str, limit: int, offset: int) -> Any:
    select_cols = ",".join(["id", "name", "url", "series", "category_id", "category_name"] + TECH_FIELDS + DOC_FIELDS)
    url = build_url(
        "catalog_lamps",
        {
            "select": select_cols,
            "name": f"eq.{name}",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    return _get_json(url)


def lamp_suggest(query: str, limit: int, offset: int) -> Any:
    # FTS for non-exact name
    return ru_fts(
        table="catalog_lamps",
        column="name",
        query=query,
        select_cols="id,name,url,series,category_name",
        order_by="name ASC",
        limit_rows=limit,
        offset_rows=offset,
    )


def lamp_with_sku_by_name(name: str, limit: int, offset: int) -> Any:
    # Uses embedding which is known to work for etm_oracl_catalog_sku.
    select_cols = "id,name,url,series,category_name,etm_oracl_catalog_sku(etm_code,oracl_code,catalog_1c,short_box_name_wms,box_name,description,is_active)"
    url = build_url(
        "catalog_lamps",
        {
            "select": select_cols,
            "name": f"eq.{name}",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    return _get_json(url)


def lamp_by_id(lamp_id: int, limit: int, offset: int) -> Any:
    select_cols = ",".join(["id", "name", "url", "series", "category_id", "category_name"] + TECH_FIELDS + DOC_FIELDS)
    url = build_url(
        "catalog_lamps",
        {
            "select": select_cols,
            "id": f"eq.{lamp_id}",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    return _get_json(url)


def sku_by_code(etm: str | None, oracl: str | None, limit: int, offset: int) -> Any:
    if bool(etm) == bool(oracl):
        raise SystemExit("Provide exactly one of --etm or --oracl")
    field = "etm_code" if etm else "oracl_code"
    value = etm or oracl  # type: ignore[assignment]

    # 1) query mapping table
    select_cols = "catalog_lamps_id,etm_code,oracl_code,catalog_1c,short_box_name_wms,box_name,description,is_active"
    url1 = build_url(
        "etm_oracl_catalog_sku",
        {
            "select": select_cols,
            field: f"eq.{value}",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    rows = _get_json(url1)
    if not rows:
        return {"sku": [], "lamps": []}

    ids = sorted({r["catalog_lamps_id"] for r in rows if r.get("catalog_lamps_id") is not None})

    # 2) query lamps (2-step; avoids relying on relationship from SKU->lamps)
    # PostgREST: id=in.(1,2,3)
    in_list = ",".join(str(i) for i in ids)
    url2 = build_url(
        "catalog_lamps",
        {
            "select": "id,name,url,series,category_name",
            "id": f"in.({in_list})",
            "limit": str(min(50, max(1, len(ids)))),
            "offset": "0",
        },
    )
    lamps = _get_json(url2)
    return {"sku": rows, "lamps": lamps}


def portfolio_by_sphere(sphere: str, fuzzy: bool, limit: int, offset: int) -> Any:
    if fuzzy:
        return ru_fts(
            table="portfolio",
            column="sphere_name",
            query=sphere,
            select_cols="id,name,url,image_url,group_name,sphere_name",
            order_by="name ASC",
            limit_rows=limit,
            offset_rows=offset,
        )

    url = build_url(
        "portfolio",
        {
            "select": "id,name,url,image_url,group_name,sphere_name",
            "sphere_name": f"eq.{sphere}",
            "order": "name.asc",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    return _get_json(url)


def sphere_categories(sphere: str, fuzzy: bool, limit: int, offset: int) -> Any:
    if fuzzy:
        rows = ru_fts(
            table="spheres",
            column="name",
            query=sphere,
            select_cols="id,name,category_name,category_url",
            order_by="category_name ASC",
            limit_rows=limit,
            offset_rows=offset,
        )
    else:
        url = build_url(
            "spheres",
            {
                "select": "id,name,category_name,category_url",
                "name": f"eq.{sphere}",
                "order": "category_name.asc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        rows = _get_json(url)

    # Deduplicate category_name
    cats = []
    seen = set()
    for r in rows:
        cn = r.get("category_name")
        if cn and cn not in seen:
            seen.add(cn)
            cats.append(cn)

    return {"spheres_rows": rows, "category_names": cats}


def category_portfolio(category: str, fuzzy: bool, limit: int, offset: int) -> Any:
    # 1) map category_name -> spheres.name
    if fuzzy:
        srows = ru_fts(
            table="spheres",
            column="category_name",
            query=category,
            select_cols="id,name,category_name",
            order_by="name ASC",
            limit_rows=50,
            offset_rows=0,
        )
    else:
        url = build_url(
            "spheres",
            {
                "select": "id,name,category_name",
                "category_name": f"eq.{category}",
                "limit": "50",
                "offset": "0",
            },
        )
        srows = _get_json(url)

    sphere_names = sorted({r["name"] for r in srows if r.get("name")})
    if not sphere_names:
        return {"spheres": [], "portfolio": []}

    # 2) query portfolio by sphere_name in (...) (paginate)
    # For many spheres, we should chunk; keep simple with first N spheres.
    chunk = sphere_names[:20]
    in_list = ",".join(chunk)
    url2 = build_url(
        "portfolio",
        {
            "select": "id,name,url,image_url,group_name,sphere_name",
            "sphere_name": f"in.({in_list})",
            "order": "name.asc",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    prows = _get_json(url2)
    return {"spheres": srows, "sphere_names": chunk, "portfolio": prows}


def category_lamps(category_name: str, fuzzy: bool, limit: int, offset: int) -> Any:
    """Find lamps for a given category.

    Because naming can drift between tables (`spheres.category_name` vs `catalog_lamps.category_name`),
    this function tries multiple strategies:
    1) categories.name -> categories.id -> catalog_lamps.category_id
    2) catalog_lamps.category_name exact
    3) FTS on catalog_lamps.category_name
    """

    # Strategy 1: go through categories.id
    url_cat = build_url(
        "categories",
        {
            "select": "id,name",
            "name": f"eq.{category_name}",
            "limit": "5",
            "offset": "0",
        },
    )
    cats = _get_json(url_cat)
    cat_ids = [c["id"] for c in cats if c.get("id") is not None]

    lamps_by_id = []
    if cat_ids:
        in_ids = ",".join(str(i) for i in cat_ids)
        url_l1 = build_url(
            "catalog_lamps",
            {
                "select": "id,name,url,series,category_id,category_name",
                "category_id": f"in.({in_ids})",
                "order": "name.asc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        lamps_by_id = _get_json(url_l1)
        if lamps_by_id:
            return {"strategy": "categories.id -> catalog_lamps.category_id", "categories": cats, "lamps": lamps_by_id}

    # Strategy 2: catalog_lamps.category_name exact
    url_l2 = build_url(
        "catalog_lamps",
        {
            "select": "id,name,url,series,category_id,category_name",
            "category_name": f"eq.{category_name}",
            "order": "name.asc",
            "limit": str(limit),
            "offset": str(offset),
        },
    )
    lamps_exact = _get_json(url_l2)
    if lamps_exact and not fuzzy:
        return {"strategy": "catalog_lamps.category_name exact", "lamps": lamps_exact}

    # Strategy 3: FTS fallback (or primary when fuzzy)
    lamps_fts = ru_fts(
        table="catalog_lamps",
        column="category_name",
        query=category_name,
        select_cols="id,name,url,series,category_id,category_name",
        order_by="name ASC",
        limit_rows=limit,
        offset_rows=offset,
    )
    return {
        "strategy": "fts on catalog_lamps.category_name",
        "categories": cats,
        "lamps_exact": lamps_exact,
        "lamps": lamps_fts,
    }


def sphere_lamps(sphere: str, fuzzy: bool, limit: int, offset: int) -> Any:
    """Find lamps suitable for a sphere.

    Pipeline:
    1) spheres.name (eq/fts) -> category_name list
    2) Try categories.name -> id mapping, then catalog_lamps.category_id in (...)
    3) Fallback: FTS on catalog_lamps.category_name for each category_name
    """

    cat_info = sphere_categories(sphere=sphere, fuzzy=fuzzy, limit=200, offset=0)
    cat_names = cat_info.get("category_names", [])
    if not cat_names:
        return {"sphere": sphere, "categories": cat_info, "lamps": []}

    chunk = cat_names[:20]

    # Strategy 2: via categories.id
    in_names = ",".join(chunk)
    url_c = build_url(
        "categories",
        {
            "select": "id,name",
            "name": f"in.({in_names})",
            "limit": "50",
            "offset": "0",
        },
    )
    cats = _get_json(url_c)
    ids = [c["id"] for c in cats if c.get("id") is not None]

    lamps_by_id = []
    if ids:
        in_ids = ",".join(str(i) for i in ids)
        url_l = build_url(
            "catalog_lamps",
            {
                "select": "id,name,url,series,category_id,category_name",
                "category_id": f"in.({in_ids})",
                "order": "name.asc",
                "limit": str(limit),
                "offset": str(offset),
            },
        )
        lamps_by_id = _get_json(url_l)
        if lamps_by_id:
            return {
                "strategy": "sphere -> spheres.category_name -> categories.id -> catalog_lamps.category_id",
                "sphere": sphere,
                "categories_from_spheres": cat_info,
                "categories": cats,
                "lamps": lamps_by_id,
            }

    # Fallback: try to search by text category_name
    merged: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for cn in chunk:
        rows = ru_fts(
            table="catalog_lamps",
            column="category_name",
            query=cn,
            select_cols="id,name,url,series,category_id,category_name",
            order_by="name ASC",
            limit_rows=limit,
            offset_rows=0,
        )
        for r in rows:
            rid = r.get("id")
            if isinstance(rid, int) and rid not in seen_ids:
                seen_ids.add(rid)
                merged.append(r)

    return {
        "strategy": "fallback fts on catalog_lamps.category_name",
        "sphere": sphere,
        "categories_from_spheres": cat_info,
        "category_names": chunk,
        "categories": cats,
        "lamps": merged,
    }


def _looks_like_code(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{3,50}", s))


def sku_guess(value: str, limit: int, offset: int) -> Any:
    # Try by code first, then by lamp name exact/fuzzy.
    if _looks_like_code(value):
        # attempt ETM then ORACL
        res_etm = sku_by_code(etm=value, oracl=None, limit=limit, offset=offset)
        if res_etm.get("sku"):
            res_etm["matched_by"] = "etm_code"
            return res_etm
        res_or = sku_by_code(etm=None, oracl=value, limit=limit, offset=offset)
        if res_or.get("sku"):
            res_or["matched_by"] = "oracl_code"
            return res_or

    # fall back to lamp name
    exact = lamp_with_sku_by_name(value, limit=limit, offset=offset)
    if exact:
        return {"matched_by": "lamp_name_exact", "rows": exact}

    sugg = lamp_suggest(value, limit=limit, offset=offset)
    return {"matched_by": "lamp_name_fuzzy", "candidates": sugg}


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    # lamp
    lamp = sub.add_parser("lamp")
    lamp_sub = lamp.add_subparsers(dest="lamp_cmd", required=True)

    lp_exact = lamp_sub.add_parser("exact")
    lp_exact.add_argument("--name", required=True)
    lp_exact.add_argument("--limit", type=int, default=5)
    lp_exact.add_argument("--offset", type=int, default=0)

    lp_sug = lamp_sub.add_parser("suggest")
    lp_sug.add_argument("--query", required=True)
    lp_sug.add_argument("--limit", type=int, default=5)
    lp_sug.add_argument("--offset", type=int, default=0)

    lp_pick = lamp_sub.add_parser("pick")
    lp_pick.add_argument("--query", required=True, help="fuzzy name to search")
    lp_pick.add_argument("--limit", type=int, default=10)
    lp_pick.add_argument("--offset", type=int, default=0)
    lp_pick.add_argument("--index", type=int, default=None, help="0-based index of candidate; if omitted, prompt interactively")
    lp_pick.add_argument("--with-sku", action="store_true", help="also return embedded SKU info")

    lp_sku = lamp_sub.add_parser("with-sku")
    lp_sku.add_argument("--name", required=True)
    lp_sku.add_argument("--limit", type=int, default=5)
    lp_sku.add_argument("--offset", type=int, default=0)

    lp_id = lamp_sub.add_parser("by-id")
    lp_id.add_argument("--id", type=int, required=True)
    lp_id.add_argument("--limit", type=int, default=1)
    lp_id.add_argument("--offset", type=int, default=0)

    # sku
    sku = sub.add_parser("sku")
    sku_sub = sku.add_subparsers(dest="sku_cmd", required=True)

    sbc = sku_sub.add_parser("by-code")
    sbc.add_argument("--etm")
    sbc.add_argument("--oracl")
    sbc.add_argument("--limit", type=int, default=5)
    sbc.add_argument("--offset", type=int, default=0)

    sguess = sku_sub.add_parser("guess")
    sguess.add_argument("value")
    sguess.add_argument("--limit", type=int, default=5)
    sguess.add_argument("--offset", type=int, default=0)

    # portfolio
    port = sub.add_parser("portfolio")
    port_sub = port.add_subparsers(dest="port_cmd", required=True)

    pbs = port_sub.add_parser("by-sphere")
    pbs.add_argument("--sphere", required=True)
    pbs.add_argument("--fuzzy", action="store_true")
    pbs.add_argument("--limit", type=int, default=5)
    pbs.add_argument("--offset", type=int, default=0)

    # sphere
    sph = sub.add_parser("sphere")
    sph_sub = sph.add_subparsers(dest="sph_cmd", required=True)

    sc = sph_sub.add_parser("categories")
    sc.add_argument("--sphere", required=True)
    sc.add_argument("--fuzzy", action="store_true")
    sc.add_argument("--limit", type=int, default=50)
    sc.add_argument("--offset", type=int, default=0)

    sl = sph_sub.add_parser("lamps")
    sl.add_argument("--sphere", required=True)
    sl.add_argument("--fuzzy", action="store_true")
    sl.add_argument("--limit", type=int, default=5)
    sl.add_argument("--offset", type=int, default=0)

    # category
    cat = sub.add_parser("category")
    cat_sub = cat.add_subparsers(dest="cat_cmd", required=True)

    cp = cat_sub.add_parser("portfolio")
    cp.add_argument("--category", required=True)
    cp.add_argument("--fuzzy", action="store_true")
    cp.add_argument("--limit", type=int, default=5)
    cp.add_argument("--offset", type=int, default=0)

    cl = cat_sub.add_parser("lamps")
    cl.add_argument("--category", required=True)
    cl.add_argument("--fuzzy", action="store_true")
    cl.add_argument("--limit", type=int, default=5)
    cl.add_argument("--offset", type=int, default=0)

    args = p.parse_args()

    if args.cmd == "lamp" and args.lamp_cmd == "exact":
        print_json(lamp_exact(args.name, args.limit, args.offset))
        return 0
    if args.cmd == "lamp" and args.lamp_cmd == "suggest":
        print_json(lamp_suggest(args.query, args.limit, args.offset))
        return 0
    if args.cmd == "lamp" and args.lamp_cmd == "pick":
        candidates = lamp_suggest(args.query, args.limit, args.offset)
        if not isinstance(candidates, list):
            raise SystemExit("Unexpected response from ru_fts")
        if not candidates:
            print_json({"query": args.query, "candidates": [], "picked": None})
            return 0

        idx = args.index
        if idx is None:
            idx = _prompt_pick(candidates)
        if idx < 0 or idx >= len(candidates):
            raise SystemExit("Index out of range")

        picked = candidates[idx]
        lamp_id = picked.get("id")
        if not isinstance(lamp_id, int):
            raise SystemExit("Picked candidate has no integer id")

        details = lamp_by_id(lamp_id, limit=1, offset=0)
        if args.with_sku:
            # If SKU is needed, query exact by name (safe, because we already have the canonical name)
            nm = picked.get("name")
            if isinstance(nm, str) and nm:
                details = lamp_with_sku_by_name(nm, limit=1, offset=0)

        print_json({"query": args.query, "candidates": candidates, "picked_index": idx, "picked": picked, "details": details})
        return 0
    if args.cmd == "lamp" and args.lamp_cmd == "with-sku":
        print_json(lamp_with_sku_by_name(args.name, args.limit, args.offset))
        return 0
    if args.cmd == "lamp" and args.lamp_cmd == "by-id":
        print_json(lamp_by_id(args.id, args.limit, args.offset))
        return 0

    if args.cmd == "sku" and args.sku_cmd == "by-code":
        print_json(sku_by_code(args.etm, args.oracl, args.limit, args.offset))
        return 0
    if args.cmd == "sku" and args.sku_cmd == "guess":
        print_json(sku_guess(args.value, args.limit, args.offset))
        return 0

    if args.cmd == "portfolio" and args.port_cmd == "by-sphere":
        print_json(portfolio_by_sphere(args.sphere, args.fuzzy, args.limit, args.offset))
        return 0

    if args.cmd == "sphere" and args.sph_cmd == "categories":
        print_json(sphere_categories(args.sphere, args.fuzzy, args.limit, args.offset))
        return 0
    if args.cmd == "sphere" and args.sph_cmd == "lamps":
        print_json(sphere_lamps(args.sphere, args.fuzzy, args.limit, args.offset))
        return 0

    if args.cmd == "category" and args.cat_cmd == "portfolio":
        print_json(category_portfolio(args.category, args.fuzzy, args.limit, args.offset))
        return 0
    if args.cmd == "category" and args.cat_cmd == "lamps":
        print_json(category_lamps(args.category, args.fuzzy, args.limit, args.offset))
        return 0

    raise SystemExit("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
