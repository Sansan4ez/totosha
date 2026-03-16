"""Corporate DB (Supabase/PostgREST) server-side endpoints.

This module intentionally exposes only a small, allowlisted set of read-only
operations. It must not accept arbitrary PostgREST paths/selects from callers.

Auth model:
- tools-api reads SUPABASE_KEY (anon/public) from Docker secret /run/secrets/supabase_key
- core calls tools-api over internal Docker network; tools-api never returns the key
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/corp-db", tags=["corp-db"])

SUPABASE_SECRET_PATH = "/run/secrets/supabase_key"
DEFAULT_SUPABASE_REST_URL = "https://api.llm-studio.pro/rest/v1"


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


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


def _get_supabase_key() -> str:
    key = _read_file(SUPABASE_SECRET_PATH) or os.getenv("SUPABASE_KEY", "").strip()
    if not key:
        raise HTTPException(500, "SUPABASE_KEY is not configured")

    # Defense-in-depth: refuse service_role keys.
    payload = _jwt_payload(key)
    if payload.get("role") == "service_role":
        raise HTTPException(500, "Refusing to use service_role key")

    return key


def _get_supabase_rest_url() -> str:
    return os.getenv("SUPABASE_REST_URL", DEFAULT_SUPABASE_REST_URL).rstrip("/")


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    limit = max(1, min(int(limit), 20))
    offset = max(0, min(int(offset), 200))
    return limit, offset


def _req_str(v: Optional[str], name: str, max_len: int = 200) -> str:
    if v is None:
        raise HTTPException(400, f"Missing field: {name}")
    s = v.strip()
    if not s:
        raise HTTPException(400, f"Empty field: {name}")
    if len(s) > max_len:
        raise HTTPException(400, f"{name} too long")
    return s


class CorpDbSearchRequest(BaseModel):
    kind: Literal[
        "lamp_exact",
        "lamp_suggest",
        "sku_by_code",
        "category_lamps",
        "portfolio_by_sphere",
        "sphere_categories",
    ]

    # Common pagination
    limit: int = Field(default=5, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)

    # Inputs (used depending on kind)
    name: Optional[str] = None
    query: Optional[str] = None
    etm: Optional[str] = None
    oracl: Optional[str] = None
    category: Optional[str] = None
    sphere: Optional[str] = None
    fuzzy: bool = False


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str], params: dict[str, str]) -> Any:
    try:
        r = await client.get(url, headers=headers, params=params)
    except httpx.RequestError as e:
        raise HTTPException(502, f"Supabase request failed: {type(e).__name__}")

    if r.status_code >= 400:
        # Don't return full body (could contain internal details); keep it short.
        body = (r.text or "")[:300]
        raise HTTPException(502, f"Supabase error {r.status_code}: {body}")

    try:
        return r.json()
    except Exception:
        raise HTTPException(502, "Supabase returned non-JSON response")


async def _ru_fts(
    client: httpx.AsyncClient,
    rest_url: str,
    headers: dict[str, str],
    *,
    table: str,
    column: str,
    query: str,
    select_cols: str,
    order_by: str,
    limit_rows: int,
    offset_rows: int,
) -> Any:
    url = f"{rest_url}/rpc/ru_fts"
    params = {
        "p_table_name": table,
        "p_search_column": column,
        "p_search_query": query,
        "p_select_columns": select_cols,
        "p_order_by": order_by,
        "p_limit_rows": str(limit_rows),
        "p_offset_rows": str(offset_rows),
    }
    return await _get_json(client, url, headers, params)


@router.post("/search")
async def corp_db_search(req: CorpDbSearchRequest, request: Request):
    """Allowlisted corporate DB queries.

    Caller identity is carried by core via internal headers (not user-controlled).
    """

    # Used for audit/rate limiting later (intentionally optional for now).
    user_id = request.headers.get("X-User-Id", "")

    key = _get_supabase_key()
    rest_url = _get_supabase_rest_url()

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "totosha-tools-api/1.0",
    }

    limit, offset = _clamp(req.limit, req.offset)

    timeout = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        kind = req.kind

        if kind == "lamp_exact":
            name = _req_str(req.name, "name", max_len=200)
            select_cols = ",".join(
                [
                    "id",
                    "name",
                    "url",
                    "series",
                    "category_id",
                    "category_name",
                    # Tech fields
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
                    # Docs
                    "booklet_url",
                    "drawing_url",
                    "passport_url",
                    "certificate_url",
                    "ies_url",
                    "file_package_url",
                    "image_url",
                    "diffuser_url",
                ]
            )
            url = f"{rest_url}/catalog_lamps"
            params = {
                "select": select_cols,
                "name": f"eq.{name}",
                "limit": str(limit),
                "offset": str(offset),
            }
            data = await _get_json(client, url, headers, params)
            return {"ok": True, "kind": kind, "user_id": user_id, "data": data}

        if kind == "lamp_suggest":
            query = _req_str(req.query, "query", max_len=200)
            data = await _ru_fts(
                client,
                rest_url,
                headers,
                table="catalog_lamps",
                column="name",
                query=query,
                select_cols="id,name,url,series,category_name",
                order_by="name ASC",
                limit_rows=limit,
                offset_rows=offset,
            )
            return {"ok": True, "kind": kind, "user_id": user_id, "data": data}

        if kind == "sku_by_code":
            etm = (req.etm or "").strip() or None
            oracl = (req.oracl or "").strip() or None
            if bool(etm) == bool(oracl):
                raise HTTPException(400, "Provide exactly one of: etm, oracl")

            field = "etm_code" if etm else "oracl_code"
            value = etm or oracl

            url1 = f"{rest_url}/etm_oracl_catalog_sku"
            params1 = {
                "select": "catalog_lamps_id,etm_code,oracl_code,catalog_1c,short_box_name_wms,box_name,description,is_active",
                field: f"eq.{value}",
                "limit": str(limit),
                "offset": str(offset),
            }
            rows = await _get_json(client, url1, headers, params1)
            if not rows:
                return {"ok": True, "kind": kind, "user_id": user_id, "data": {"sku": [], "lamps": []}}

            ids = sorted({r.get("catalog_lamps_id") for r in rows if r.get("catalog_lamps_id") is not None})
            in_list = ",".join(str(i) for i in ids)

            url2 = f"{rest_url}/catalog_lamps"
            params2 = {
                "select": "id,name,url,series,category_name",
                "id": f"in.({in_list})",
                "limit": str(min(50, max(1, len(ids)))),
                "offset": "0",
            }
            lamps = await _get_json(client, url2, headers, params2)
            return {"ok": True, "kind": kind, "user_id": user_id, "data": {"sku": rows, "lamps": lamps}}

        if kind == "category_lamps":
            category = _req_str(req.category, "category", max_len=200)
            select_cols = "id,name,url,series,category_id,category_name"

            # 1) Try exact match first
            url = f"{rest_url}/catalog_lamps"
            params = {
                "select": select_cols,
                "category_name": f"eq.{category}",
                "order": "name.asc",
                "limit": str(limit),
                "offset": str(offset),
            }
            exact = await _get_json(client, url, headers, params)
            if exact and not req.fuzzy:
                return {"ok": True, "kind": kind, "user_id": user_id, "data": {"strategy": "exact", "rows": exact}}

            # 2) FTS fallback
            fts = await _ru_fts(
                client,
                rest_url,
                headers,
                table="catalog_lamps",
                column="category_name",
                query=category,
                select_cols=select_cols,
                order_by="name ASC",
                limit_rows=limit,
                offset_rows=offset,
            )
            return {
                "ok": True,
                "kind": kind,
                "user_id": user_id,
                "data": {"strategy": "fts", "exact": exact, "rows": fts},
            }

        if kind == "portfolio_by_sphere":
            sphere = _req_str(req.sphere, "sphere", max_len=200)
            select_cols = "id,name,url,image_url,group_name,sphere_name"

            if req.fuzzy:
                data = await _ru_fts(
                    client,
                    rest_url,
                    headers,
                    table="portfolio",
                    column="sphere_name",
                    query=sphere,
                    select_cols=select_cols,
                    order_by="name ASC",
                    limit_rows=limit,
                    offset_rows=offset,
                )
                return {"ok": True, "kind": kind, "user_id": user_id, "data": data}

            url = f"{rest_url}/portfolio"
            params = {
                "select": select_cols,
                "sphere_name": f"eq.{sphere}",
                "order": "name.asc",
                "limit": str(limit),
                "offset": str(offset),
            }
            data = await _get_json(client, url, headers, params)
            return {"ok": True, "kind": kind, "user_id": user_id, "data": data}

        if kind == "sphere_categories":
            sphere = _req_str(req.sphere, "sphere", max_len=200)
            select_cols = "id,name,category_name,category_url"

            if req.fuzzy:
                rows = await _ru_fts(
                    client,
                    rest_url,
                    headers,
                    table="spheres",
                    column="name",
                    query=sphere,
                    select_cols=select_cols,
                    order_by="category_name ASC",
                    limit_rows=min(200, limit),
                    offset_rows=0,
                )
            else:
                url = f"{rest_url}/spheres"
                params = {
                    "select": select_cols,
                    "name": f"eq.{sphere}",
                    "order": "category_name.asc",
                    "limit": str(min(200, limit)),
                    "offset": "0",
                }
                rows = await _get_json(client, url, headers, params)

            cats = []
            seen = set()
            for r in rows:
                cn = r.get("category_name") if isinstance(r, dict) else None
                if cn and cn not in seen:
                    seen.add(cn)
                    cats.append(cn)

            return {"ok": True, "kind": kind, "user_id": user_id, "data": {"rows": rows, "category_names": cats}}

        raise HTTPException(400, f"Unsupported kind: {kind}")
