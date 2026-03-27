"""Corporate DB routes backed by internal Postgres."""

from __future__ import annotations

import json
import logging
import os
import re
from time import perf_counter
from typing import Any, Literal, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram

from src.observability import REGISTRY

router = APIRouter(prefix="/corp-db", tags=["corp-db"])
logger = logging.getLogger(__name__)

CORP_DB_RO_SECRET_PATH = "/run/secrets/corp_db_ro_dsn"
DEFAULT_PROXY_URL = "http://proxy:3200/v1"

PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "kb_search": {
        "entity_types": ["kb_chunk"],
        "weights": (1.0, 1.2, 0.15),
    },
    "entity_resolver": {
        "entity_types": ["lamp", "sku", "category", "portfolio", "sphere", "mounting_type", "category_mounting"],
        "weights": (0.9, 0.55, 1.2),
    },
    "candidate_generation": {
        "entity_types": ["lamp", "category", "mounting_type", "sphere"],
        "weights": (1.0, 0.9, 0.75),
    },
    "related_evidence": {
        "entity_types": ["kb_chunk", "portfolio", "category_mounting", "mounting_type", "sphere"],
        "weights": (1.0, 1.0, 0.35),
    },
}

ENTITY_TYPE_ALIASES: dict[str, str] = {
    "kb": "kb_chunk",
}

_pool: asyncpg.Pool | None = None
_client: AsyncOpenAI | None = None
CORP_DB_SEARCH_REQUESTS_TOTAL = Counter(
    "corp_db_search_requests_total",
    "Total corp_db search requests handled by tools-api.",
    labelnames=("kind", "status", "profile"),
    registry=REGISTRY,
)
CORP_DB_SEARCH_DURATION_MS = Histogram(
    "corp_db_search_duration_milliseconds",
    "Duration of corp_db search requests in tools-api.",
    labelnames=("kind", "status", "profile"),
    registry=REGISTRY,
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)
CORP_DB_EMBEDDINGS_UNAVAILABLE_TOTAL = Counter(
    "corp_db_embeddings_unavailable_total",
    "Total embedding resolution failures in corp-db search requests.",
    labelnames=("profile",),
    registry=REGISTRY,
)


class CorpDbSearchRequest(BaseModel):
    kind: Literal[
        "hybrid_search",
        "lamp_exact",
        "lamp_suggest",
        "sku_by_code",
        "category_lamps",
        "portfolio_by_sphere",
        "sphere_categories",
        "lamp_filters",
        "category_mountings",
    ]

    limit: int = Field(default=5, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)

    query: Optional[str] = None
    profile: Optional[Literal["kb_search", "entity_resolver", "candidate_generation", "related_evidence"]] = None
    entity_types: Optional[list[str]] = None
    include_debug: bool = False

    name: Optional[str] = None
    etm: Optional[str] = None
    oracl: Optional[str] = None
    category: Optional[str] = None
    sphere: Optional[str] = None
    mounting_type: Optional[str] = None
    ip: Optional[str] = None
    voltage_kind: Optional[Literal["AC", "DC", "AC/DC"]] = None
    explosion_protected: Optional[bool] = None
    fuzzy: bool = False

    power_w_min: Optional[int] = None
    power_w_max: Optional[int] = None
    flux_lm_min: Optional[int] = None
    flux_lm_max: Optional[int] = None
    cct_k_min: Optional[int] = None
    cct_k_max: Optional[int] = None
    temp_c_min: Optional[int] = None
    temp_c_max: Optional[int] = None


def _read_secret(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""


def _get_ro_dsn() -> str:
    dsn = _read_secret(CORP_DB_RO_SECRET_PATH) or os.getenv("CORP_DB_RO_DSN", "").strip()
    if not dsn:
        raise RuntimeError("CORP_DB_RO_DSN is not configured")
    return dsn


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(int(limit), 10)), max(0, min(int(offset), 200))


def _req_str(value: Optional[str], field_name: str, max_len: int = 240) -> str:
    if value is None:
        raise HTTPException(400, f"Missing field: {field_name}")
    text = value.strip()
    if not text:
        raise HTTPException(400, f"Empty field: {field_name}")
    if len(text) > max_len:
        raise HTTPException(400, f"{field_name} too long")
    return text


def _normalize_ws(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _preview(text: str, limit: int = 220) -> str:
    normalized = _normalize_ws(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _normalize_entity_types(values: Optional[list[str]]) -> Optional[list[str]]:
    if not values:
        return values

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = ENTITY_TYPE_ALIASES.get(str(raw).strip(), str(raw).strip())
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"Unsupported metadata payload: {type(value).__name__}")


def _success(kind: str, *, query: str | None = None, filters: dict[str, Any] | None = None, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = results or []
    return {
        "status": "success" if rows else "empty",
        "kind": kind,
        "query": query,
        "filters": filters or {},
        "results": rows,
    }


def _error(kind: str, message: str, *, query: str | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "kind": kind,
        "query": query,
        "results": [],
        "message": message,
    }


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
    timeout_ms = int(os.getenv("CORP_DB_STATEMENT_TIMEOUT_MS", "10000"))
    await conn.execute(f"SET statement_timeout = {timeout_ms}")


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _get_ro_dsn(),
            min_size=1,
            max_size=5,
            init=_init_connection,
        )
    return _pool


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.getenv("PROXY_URL", DEFAULT_PROXY_URL).rstrip("/"),
            api_key=os.getenv("PROXY_API_KEY", "proxy"),
        )
    return _client


async def _get_query_embedding(query: str) -> list[float] | None:
    try:
        response = await _get_client().embeddings.create(
            model="text-embedding-3-large",
            input=query,
            dimensions=1536,
        )
        return response.data[0].embedding
    except Exception as exc:
        logger.warning("corp-db embeddings unavailable for query=%r: %s", query[:120], exc)
        return None


def _hybrid_row(record: asyncpg.Record) -> dict[str, Any]:
    metadata = _json_object(record["metadata"])
    result = {
        "entity_type": record["entity_type"],
        "entity_id": record["entity_id"],
        "title": record["title"],
        "score": round(float(record["score"]), 6),
        "metadata": metadata,
    }
    if record["entity_type"] == "kb_chunk":
        result["document_title"] = metadata.get("document_title")
        result["heading"] = record["title"]
        result["preview"] = _preview(record["content"])
    else:
        result["preview"] = _preview(record["content"])
    if record["debug_info"] is not None:
        result["debug_info"] = record["debug_info"]
    return result


async def _hybrid_search(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int) -> dict[str, Any]:
    query = _req_str(req.query, "query", max_len=400)
    profile_name = req.profile or "entity_resolver"
    preset = PROFILE_PRESETS[profile_name]
    entity_types = _normalize_entity_types(req.entity_types or preset["entity_types"])
    full_text_weight, semantic_weight, fuzzy_weight = preset["weights"]
    embedding = await _get_query_embedding(query)
    if embedding is None:
        CORP_DB_EMBEDDINGS_UNAVAILABLE_TOTAL.labels(profile_name).inc()
        semantic_weight = 0.0

    rows = await conn.fetch(
        """
        SELECT doc_id, entity_type, entity_id, title, content, metadata, score, debug_info
        FROM corp.corp_hybrid_search($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        query,
        embedding,
        limit,
        full_text_weight,
        semantic_weight,
        fuzzy_weight,
        60,
        entity_types,
        req.include_debug,
    )
    return _success(
        "hybrid_search",
        query=query,
        filters={"profile": profile_name, "entity_types": entity_types},
        results=[_hybrid_row(row) for row in rows],
    )


async def _lamp_exact(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    name = _req_str(req.name, "name")
    rows = await conn.fetch(
        """
        SELECT *
        FROM corp.catalog_lamps
        WHERE lower(name) = lower($1)
        ORDER BY name
        LIMIT $2 OFFSET $3
        """,
        name,
        limit,
        offset,
    )
    lamp_ids = [row["lamp_id"] for row in rows]
    docs = {}
    skus_by_lamp: dict[int, list[dict[str, Any]]] = {}
    if lamp_ids:
        doc_rows = await conn.fetch(
            "SELECT * FROM corp.catalog_lamp_documents WHERE lamp_id = ANY($1::bigint[])",
            lamp_ids,
        )
        docs = {row["lamp_id"]: dict(row) for row in doc_rows}
        sku_rows = await conn.fetch(
            """
            SELECT sku_id, lamp_id, etm_code, oracl_code, short_box_name_wms, catalog_1c, box_name, is_active
            FROM corp.etm_oracl_catalog_sku
            WHERE lamp_id = ANY($1::bigint[])
            ORDER BY is_active DESC, sku_id
            """,
            lamp_ids,
        )
        for row in sku_rows:
            skus_by_lamp.setdefault(row["lamp_id"], []).append(dict(row))

    return _success(
        "lamp_exact",
        query=name,
        results=[
            {
                "lamp_id": row["lamp_id"],
                "name": row["name"],
                "category_id": row["category_id"],
                "category_name": row.get("category_name"),
                "url": row.get("url"),
                "power_w": row.get("power_w"),
                "luminous_flux_lm": row.get("luminous_flux_lm"),
                "color_temperature_k": row.get("color_temperature_k"),
                "ingress_protection": row.get("ingress_protection"),
                "mounting_type": row.get("mounting_type"),
                "supply_voltage_raw": row.get("supply_voltage_raw"),
                "operating_temperature_range_raw": row.get("operating_temperature_range_raw"),
                "documents": docs.get(row["lamp_id"], {}),
                "sku": skus_by_lamp.get(row["lamp_id"], []),
            }
            for row in rows
        ],
    )


async def _sku_by_code(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    etm = (req.etm or "").strip() or None
    oracl = (req.oracl or "").strip() or None
    if bool(etm) == bool(oracl):
        raise HTTPException(400, "Provide exactly one of: etm, oracl")

    rows = await conn.fetch(
        """
        SELECT s.*, l.name AS lamp_name, l.category_id, l.category_name
        FROM corp.etm_oracl_catalog_sku s
        LEFT JOIN corp.catalog_lamps l ON l.lamp_id = s.lamp_id
        WHERE ($1::text IS NOT NULL AND s.etm_code = $1)
           OR ($2::text IS NOT NULL AND s.oracl_code = $2)
        ORDER BY s.is_active DESC, s.sku_id
        LIMIT $3 OFFSET $4
        """,
        etm,
        oracl,
        limit,
        offset,
    )
    return _success(
        "sku_by_code",
        query=etm or oracl,
        results=[
            {
                "sku_id": row["sku_id"],
                "lamp_id": row.get("lamp_id"),
                "lamp_name": row.get("lamp_name"),
                "category_id": row.get("category_id"),
                "category_name": row.get("category_name"),
                "etm_code": row.get("etm_code"),
                "oracl_code": row.get("oracl_code"),
                "catalog_1c": row.get("catalog_1c"),
                "short_box_name_wms": row.get("short_box_name_wms"),
                "box_name": row.get("box_name"),
                "description": row.get("description"),
                "is_active": row.get("is_active"),
            }
            for row in rows
        ],
    )


async def _category_lamps(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    category = _req_str(req.category, "category")
    rows = await conn.fetch(
        """
        SELECT l.lamp_id, l.name, l.category_id, l.category_name, l.power_w, l.luminous_flux_lm,
               l.color_temperature_k, l.ingress_protection, l.mounting_type, l.url
        FROM corp.catalog_lamps l
        JOIN corp.categories c ON c.category_id = l.category_id
        WHERE CASE
            WHEN $1 THEN c.name ILIKE ('%' || $2 || '%')
            ELSE lower(c.name) = lower($2)
        END
        ORDER BY l.name
        LIMIT $3 OFFSET $4
        """,
        req.fuzzy,
        category,
        limit,
        offset,
    )
    return _success(
        "category_lamps",
        query=category,
        results=[dict(row) for row in rows],
    )


async def _portfolio_by_sphere(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    sphere = _req_str(req.sphere, "sphere")
    rows = await conn.fetch(
        """
        SELECT p.portfolio_id, p.name, p.url, p.group_name, p.image_url, s.sphere_id, s.name AS sphere_name
        FROM corp.portfolio p
        JOIN corp.spheres s ON s.sphere_id = p.sphere_id
        WHERE CASE
            WHEN $1 THEN s.name ILIKE ('%' || $2 || '%')
            ELSE lower(s.name) = lower($2)
        END
        ORDER BY p.name
        LIMIT $3 OFFSET $4
        """,
        req.fuzzy,
        sphere,
        limit,
        offset,
    )
    return _success(
        "portfolio_by_sphere",
        query=sphere,
        results=[dict(row) for row in rows],
    )


async def _sphere_categories(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    sphere = _req_str(req.sphere, "sphere")
    rows = await conn.fetch(
        """
        SELECT s.sphere_id, s.name AS sphere_name, c.category_id, c.name AS category_name, c.url
        FROM corp.spheres s
        JOIN corp.sphere_categories sc ON sc.sphere_id = s.sphere_id
        JOIN corp.categories c ON c.category_id = sc.category_id
        WHERE CASE
            WHEN $1 THEN s.name ILIKE ('%' || $2 || '%')
            ELSE lower(s.name) = lower($2)
        END
        ORDER BY c.name
        LIMIT $3 OFFSET $4
        """,
        req.fuzzy,
        sphere,
        limit,
        offset,
    )
    return _success(
        "sphere_categories",
        query=sphere,
        results=[dict(row) for row in rows],
    )


async def _category_mountings(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    category = (req.category or "").strip() or None
    mounting_type = (req.mounting_type or "").strip() or None
    if not category and not mounting_type:
        raise HTTPException(400, "Provide category and/or mounting_type")

    conditions = []
    args: list[Any] = []

    if category:
        args.append(category)
        conditions.append(f"c.name ILIKE ('%' || ${len(args)} || '%')")
    if mounting_type:
        args.append(mounting_type)
        conditions.append(f"(mt.name ILIKE ('%' || ${len(args)} || '%') OR mt.mark ILIKE ('%' || ${len(args)} || '%'))")

    args.extend([limit, offset])
    rows = await conn.fetch(
        f"""
        SELECT cm.category_mounting_id, cm.series, cm.is_default,
               c.category_id, c.name AS category_name,
               mt.mounting_type_id, mt.name AS mounting_type_name, mt.mark
        FROM corp.category_mountings cm
        LEFT JOIN corp.categories c ON c.category_id = cm.category_id
        LEFT JOIN corp.mounting_types mt ON mt.mounting_type_id = cm.mounting_type_id
        WHERE {' AND '.join(conditions)}
        ORDER BY cm.series, mt.name
        LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    return _success(
        "category_mountings",
        filters={"category": category, "mounting_type": mounting_type},
        results=[dict(row) for row in rows],
    )


async def _lamp_filters(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    conditions = ["TRUE"]
    args: list[Any] = []
    filters: dict[str, Any] = {}

    if req.category:
        args.append(req.category.strip())
        filters["category"] = req.category.strip()
        conditions.append(f"c.name ILIKE ('%' || ${len(args)} || '%')")
    if req.mounting_type:
        args.append(req.mounting_type.strip())
        filters["mounting_type"] = req.mounting_type.strip()
        conditions.append(f"coalesce(l.mounting_type, '') ILIKE ('%' || ${len(args)} || '%')")
    if req.ip:
        args.append(req.ip.strip())
        filters["ip"] = req.ip.strip()
        conditions.append(f"coalesce(l.ingress_protection, '') ILIKE ('%' || ${len(args)} || '%')")
    if req.voltage_kind:
        args.append(req.voltage_kind)
        filters["voltage_kind"] = req.voltage_kind
        conditions.append(f"l.supply_voltage_kind = ${len(args)}")
    if req.explosion_protected is not None:
        args.append(req.explosion_protected)
        filters["explosion_protected"] = req.explosion_protected
        conditions.append(f"l.is_explosion_protected = ${len(args)}")

    range_specs = [
        ("power_w", req.power_w_min, req.power_w_max),
        ("luminous_flux_lm", req.flux_lm_min, req.flux_lm_max),
        ("color_temperature_k", req.cct_k_min, req.cct_k_max),
    ]
    for column, minimum, maximum in range_specs:
        if minimum is not None:
            args.append(minimum)
            filters[f"{column}_min"] = minimum
            conditions.append(f"l.{column} >= ${len(args)}")
        if maximum is not None:
            args.append(maximum)
            filters[f"{column}_max"] = maximum
            conditions.append(f"l.{column} <= ${len(args)}")

    if req.temp_c_min is not None:
        args.append(req.temp_c_min)
        filters["temp_c_min"] = req.temp_c_min
        conditions.append(f"l.operating_temperature_max_c >= ${len(args)}")
    if req.temp_c_max is not None:
        args.append(req.temp_c_max)
        filters["temp_c_max"] = req.temp_c_max
        conditions.append(f"l.operating_temperature_min_c <= ${len(args)}")

    args.extend([limit, offset])
    rows = await conn.fetch(
        f"""
        SELECT l.lamp_id, l.name, l.category_id, c.name AS category_name, l.power_w, l.luminous_flux_lm,
               l.color_temperature_k, l.ingress_protection, l.mounting_type, l.supply_voltage_kind,
               l.operating_temperature_range_raw, l.url
        FROM corp.catalog_lamps l
        LEFT JOIN corp.categories c ON c.category_id = l.category_id
        WHERE {' AND '.join(conditions)}
        ORDER BY l.name
        LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    return _success("lamp_filters", filters=filters, results=[dict(row) for row in rows])


@router.post("/search")
async def corp_db_search(req: CorpDbSearchRequest, request: Request):
    user_id = request.headers.get("X-User-Id", "")
    limit, offset = _clamp(req.limit, req.offset)
    started_at = perf_counter()
    profile_name = req.profile or "none"
    status = "error"

    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            if req.kind == "hybrid_search":
                result = await _hybrid_search(conn, req, limit)
            elif req.kind == "lamp_exact":
                result = await _lamp_exact(conn, req, limit, offset)
            elif req.kind == "lamp_suggest":
                if hasattr(req, "model_copy"):
                    suggest_req = req.model_copy(update={"kind": "hybrid_search", "profile": "entity_resolver", "entity_types": ["lamp", "sku"]})
                else:
                    suggest_req = req.copy(update={"kind": "hybrid_search", "profile": "entity_resolver", "entity_types": ["lamp", "sku"]})
                result = await _hybrid_search(conn, suggest_req, limit)
                result["kind"] = "lamp_suggest"
            elif req.kind == "sku_by_code":
                result = await _sku_by_code(conn, req, limit, offset)
            elif req.kind == "category_lamps":
                result = await _category_lamps(conn, req, limit, offset)
            elif req.kind == "portfolio_by_sphere":
                result = await _portfolio_by_sphere(conn, req, limit, offset)
            elif req.kind == "sphere_categories":
                result = await _sphere_categories(conn, req, limit, offset)
            elif req.kind == "category_mountings":
                result = await _category_mountings(conn, req, limit, offset)
            else:
                result = await _lamp_filters(conn, req, limit, offset)

            result["user_id"] = user_id
            status = str(result.get("status", "success"))
            return result
    except HTTPException:
        status = "http_error"
        raise
    except Exception:
        status = "error"
        return _error(req.kind, "Корпоративная база временно недоступна", query=req.query)
    finally:
        CORP_DB_SEARCH_REQUESTS_TOTAL.labels(req.kind, status, profile_name).inc()
        CORP_DB_SEARCH_DURATION_MS.labels(req.kind, status, profile_name).observe(
            (perf_counter() - started_at) * 1000
        )
