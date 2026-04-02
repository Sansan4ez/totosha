"""Corporate DB routes backed by internal Postgres."""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from openai import AsyncOpenAI
from opentelemetry import trace
from pgvector.asyncpg import register_vector
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram

from src.observability import REGISTRY, REQUEST_ID

router = APIRouter(prefix="/corp-db", tags=["corp-db"])
logger = logging.getLogger(__name__)

CORP_DB_RO_SECRET_PATH = "/run/secrets/corp_db_ro_dsn"
DEFAULT_PROXY_URL = "http://proxy:3200/v1"
LATENCY_BUCKETS_MS = (
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    15000,
    20000,
    30000,
    45000,
    60000,
)

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
        "entity_types": ["lamp", "sku", "category", "mounting_type", "sphere"],
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
QUERY_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-я/+.-]+")
IP_RE = re.compile(r"\bip[\s-]?(\d{2,3})\b", re.IGNORECASE)
POWER_RE = re.compile(r"\b(\d{1,4})\s*(?:ватт|вт|w)\b", re.IGNORECASE)
CCT_RE = re.compile(r"\b(\d{4,5})\s*(?:k|к)\b", re.IGNORECASE)
LUMEN_RE = re.compile(r"\b(\d{3,6})\s*(?:lm|лм)\b", re.IGNORECASE)
NOISE_TOKENS = {
    "для",
    "под",
    "или",
    "как",
    "что",
    "есть",
    "нужен",
    "нужна",
    "нужно",
    "мне",
    "нам",
    "светильник",
    "светильники",
    "лампа",
    "лампы",
    "прожектор",
    "прожекторы",
    "модель",
    "модели",
    "серия",
    "серии",
    "проект",
    "проекты",
    "портфолио",
    "объект",
    "объекты",
}
MOUNTING_HINTS = {
    "подвес": "подвес",
    "консоль": "консоль",
    "лира": "лира",
    "кроншт": "кронштейн",
    "потолоч": "потол",
    "настенн": "настен",
}
LAMP_RESPONSE_FIELDS = (
    "power_w",
    "luminous_flux_lm",
    "beam_pattern",
    "mounting_type",
    "explosion_protection_marking",
    "is_explosion_protected",
    "color_temperature_k",
    "color_rendering_index_ra",
    "power_factor_operator",
    "power_factor_min",
    "climate_execution",
    "operating_temperature_range_raw",
    "operating_temperature_min_c",
    "operating_temperature_max_c",
    "ingress_protection",
    "electrical_protection_class",
    "supply_voltage_raw",
    "supply_voltage_kind",
    "supply_voltage_nominal_v",
    "supply_voltage_min_v",
    "supply_voltage_max_v",
    "supply_voltage_tolerance_minus_pct",
    "supply_voltage_tolerance_plus_pct",
    "dimensions_raw",
    "length_mm",
    "width_mm",
    "height_mm",
    "warranty_years",
    "weight_kg",
)
LAMP_TEXT_FILTER_SPECS = (
    ("category", "category_name"),
    ("mounting_type", "mounting_type"),
    ("ip", "ingress_protection"),
    ("beam_pattern", "beam_pattern"),
    ("climate_execution", "climate_execution"),
    ("electrical_protection_class", "electrical_protection_class"),
    ("explosion_protection_marking", "explosion_protection_marking"),
    ("supply_voltage_raw", "supply_voltage_raw"),
    ("dimensions_raw", "dimensions_raw"),
)
LAMP_EXACT_FILTER_SPECS = (
    ("voltage_kind", "supply_voltage_kind"),
    ("power_factor_operator", "power_factor_operator"),
)
LAMP_BOOLEAN_FILTER_SPECS = (("explosion_protected", "is_explosion_protected"),)
LAMP_RANGE_FILTER_SPECS = (
    ("power_w_min", "power_w_max", "power_w"),
    ("flux_lm_min", "flux_lm_max", "luminous_flux_lm"),
    ("cct_k_min", "cct_k_max", "color_temperature_k"),
    ("weight_kg_min", "weight_kg_max", "weight_kg"),
    ("cri_ra_min", "cri_ra_max", "color_rendering_index_ra"),
    ("power_factor_min_min", "power_factor_min_max", "power_factor_min"),
    ("voltage_nominal_v_min", "voltage_nominal_v_max", "supply_voltage_nominal_v"),
    ("voltage_min_v_min", "voltage_min_v_max", "supply_voltage_min_v"),
    ("voltage_max_v_min", "voltage_max_v_max", "supply_voltage_max_v"),
    ("voltage_tol_minus_pct_min", "voltage_tol_minus_pct_max", "supply_voltage_tolerance_minus_pct"),
    ("voltage_tol_plus_pct_min", "voltage_tol_plus_pct_max", "supply_voltage_tolerance_plus_pct"),
    ("length_mm_min", "length_mm_max", "length_mm"),
    ("width_mm_min", "width_mm_max", "width_mm"),
    ("height_mm_min", "height_mm_max", "height_mm"),
    ("warranty_years_min", "warranty_years_max", "warranty_years"),
)
HYBRID_ZERO_AS_UNSET_FIELDS = {
    "power_w_min",
    "power_w_max",
    "flux_lm_min",
    "flux_lm_max",
    "cct_k_min",
    "cct_k_max",
    "weight_kg_min",
    "weight_kg_max",
    "cri_ra_min",
    "cri_ra_max",
    "power_factor_min_min",
    "power_factor_min_max",
    "voltage_nominal_v_min",
    "voltage_nominal_v_max",
    "voltage_min_v_min",
    "voltage_min_v_max",
    "voltage_max_v_min",
    "voltage_max_v_max",
    "voltage_tol_minus_pct_min",
    "voltage_tol_minus_pct_max",
    "voltage_tol_plus_pct_min",
    "voltage_tol_plus_pct_max",
    "length_mm_min",
    "length_mm_max",
    "width_mm_min",
    "width_mm_max",
    "height_mm_min",
    "height_mm_max",
    "warranty_years_min",
    "warranty_years_max",
}
DECIMAL_RANGE_COLUMNS = {
    "weight_kg",
    "power_factor_min",
    "supply_voltage_tolerance_minus_pct",
    "supply_voltage_tolerance_plus_pct",
    "length_mm",
    "width_mm",
    "height_mm",
}
DECIMAL_EQUALITY_TOLERANCE = Decimal("0.0005")

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
    buckets=LATENCY_BUCKETS_MS,
)
CORP_DB_SEARCH_PHASE_DURATION_MS = Histogram(
    "corp_db_search_phase_duration_milliseconds",
    "Duration of individual corp-db search phases in tools-api.",
    labelnames=("kind", "profile", "phase", "status"),
    registry=REGISTRY,
    buckets=LATENCY_BUCKETS_MS,
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
        "portfolio_examples_by_lamp",
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
    beam_pattern: Optional[str] = None
    climate_execution: Optional[str] = None
    electrical_protection_class: Optional[str] = None
    explosion_protection_marking: Optional[str] = None
    supply_voltage_raw: Optional[str] = None
    dimensions_raw: Optional[str] = None
    power_factor_operator: Optional[str] = None
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
    weight_kg_min: Optional[float] = None
    weight_kg_max: Optional[float] = None
    cri_ra_min: Optional[int] = None
    cri_ra_max: Optional[int] = None
    power_factor_min_min: Optional[float] = None
    power_factor_min_max: Optional[float] = None
    temp_c_min: Optional[int] = None
    temp_c_max: Optional[int] = None
    voltage_nominal_v_min: Optional[int] = None
    voltage_nominal_v_max: Optional[int] = None
    voltage_min_v_min: Optional[int] = None
    voltage_min_v_max: Optional[int] = None
    voltage_max_v_min: Optional[int] = None
    voltage_max_v_max: Optional[int] = None
    voltage_tol_minus_pct_min: Optional[float] = None
    voltage_tol_minus_pct_max: Optional[float] = None
    voltage_tol_plus_pct_min: Optional[float] = None
    voltage_tol_plus_pct_max: Optional[float] = None
    length_mm_min: Optional[float] = None
    length_mm_max: Optional[float] = None
    width_mm_min: Optional[float] = None
    width_mm_max: Optional[float] = None
    height_mm_min: Optional[float] = None
    height_mm_max: Optional[float] = None
    warranty_years_min: Optional[int] = None
    warranty_years_max: Optional[int] = None


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


def _row_get(row: dict[str, Any] | asyncpg.Record, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _lamp_facts(row: dict[str, Any] | asyncpg.Record) -> dict[str, Any]:
    return _json_object(_row_get(row, "agent_facts"))


def _lamp_metadata(row: dict[str, Any] | asyncpg.Record, *, search_strategy: str | None = None) -> dict[str, Any]:
    metadata = {
        "lamp_id": row["lamp_id"],
        "name": row["name"],
        "category_id": _row_get(row, "category_id"),
        "category_name": _row_get(row, "category_name"),
        "url": _row_get(row, "url"),
        "image_url": _row_get(row, "image_url"),
        "preview": _row_get(row, "preview"),
        "agent_summary": _row_get(row, "agent_summary"),
        "facts": _lamp_facts(row),
    }
    for field in LAMP_RESPONSE_FIELDS:
        value = _row_get(row, field)
        if value is not None:
            metadata[field] = value
    if search_strategy:
        metadata["search_strategy"] = search_strategy
    return metadata


def _serialize_lamp_row(
    row: dict[str, Any] | asyncpg.Record,
    *,
    documents: dict[str, Any] | None = None,
    sku: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    facts = _lamp_facts(row)
    payload = {
        "lamp_id": row["lamp_id"],
        "name": row["name"],
        "category_id": _row_get(row, "category_id"),
        "category_name": _row_get(row, "category_name"),
        "url": _row_get(row, "url"),
        "image_url": _row_get(row, "image_url"),
        "preview": _row_get(row, "preview") or _preview(_row_get(row, "agent_summary") or row["name"]),
        "agent_summary": _row_get(row, "agent_summary"),
        "facts": facts,
        "metadata": _lamp_metadata(row),
    }
    for field in LAMP_RESPONSE_FIELDS:
        payload[field] = _row_get(row, field)
    if documents is not None:
        payload["documents"] = documents
    if sku is not None:
        payload["sku"] = sku
    return payload


def _hybrid_row_from_lamp_payload(payload: dict[str, Any], score: float, strategy: str) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    metadata["search_strategy"] = strategy
    return {
        "entity_type": "lamp",
        "entity_id": str(payload["lamp_id"]),
        "title": payload["name"],
        "score": round(float(score), 6),
        "metadata": metadata,
        "preview": payload.get("preview"),
        "agent_summary": payload.get("agent_summary"),
        "facts": payload.get("facts", {}),
    }


def _hybrid_response_filters(
    *,
    profile_name: str,
    entity_types: list[str] | None,
    explicit_lamp_filters: bool,
    search_strategy: str,
) -> dict[str, Any]:
    return {
        "profile": profile_name,
        "entity_types": entity_types,
        "search_strategy": search_strategy,
        "lamp_filters_applied": explicit_lamp_filters,
    }


def _get_tracer():
    return trace.get_tracer("tools-api.corp_db")


@asynccontextmanager
async def _observe_search_phase(
    *,
    kind: str,
    profile: str,
    phase: str,
    attributes: dict[str, Any] | None = None,
    span_name: str | None = None,
):
    started_at = perf_counter()
    status = "success"
    request_id = REQUEST_ID.get("-")
    with _get_tracer().start_as_current_span(span_name or f"corp_db.{phase}") as span:
        span.set_attribute("corp_db.kind", kind)
        span.set_attribute("corp_db.profile", profile)
        span.set_attribute("corp_db.phase", phase)
        if request_id and request_id != "-":
            span.set_attribute("request_id", request_id)
        for key, value in (attributes or {}).items():
            if value is None:
                continue
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            status = "error"
            span.record_exception(exc)
            raise
        finally:
            duration_ms = (perf_counter() - started_at) * 1000
            span.set_attribute("corp_db.status", status)
            span.set_attribute("corp_db.duration_ms", duration_ms)
            CORP_DB_SEARCH_PHASE_DURATION_MS.labels(kind, profile, phase, status).observe(duration_ms)


def _success(
    kind: str,
    *,
    query: str | None = None,
    filters: dict[str, Any] | None = None,
    results: list[dict[str, Any]] | None = None,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = results or []
    response = {
        "status": "success" if rows else "empty",
        "kind": kind,
        "query": query,
        "filters": filters or {},
        "results": rows,
    }
    if debug:
        response["debug"] = debug
    return response


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
    elif record["entity_type"] == "lamp":
        result["preview"] = metadata.get("preview") or _preview(record["content"])
        result["agent_summary"] = metadata.get("agent_summary")
        result["facts"] = _json_object(metadata.get("facts"))
    else:
        result["preview"] = _preview(record["content"])
    if record["debug_info"] is not None:
        result["debug_info"] = record["debug_info"]
    return result


def _debug_info_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _rows_have_lexical_signal(rows: list[asyncpg.Record]) -> bool:
    for row in rows:
        debug_info = _debug_info_object(row["debug_info"])
        fts = debug_info.get("fts", {})
        fuzzy = debug_info.get("fuzzy", {})
        if fts.get("rank_ix") is not None or fuzzy.get("rank_ix") is not None:
            return True
    return False


def _request_like(req: CorpDbSearchRequest, **updates: Any) -> CorpDbSearchRequest:
    if hasattr(req, "model_copy"):
        return req.model_copy(update=updates)
    return req.copy(update=updates)


async def _fetch_lamp_exact_rows(
    conn: asyncpg.Connection,
    *,
    name: str,
    limit: int,
    offset: int,
) -> list[asyncpg.Record]:
    name_variants, core_name = _lamp_exact_name_variants(name)
    return await conn.fetch(
        r"""
        SELECT l.*
        FROM corp.v_catalog_lamps_agent l
        WHERE regexp_replace(lower(coalesce(name, '')), '\s+', ' ', 'g') = ANY($1::text[])
           OR regexp_replace(regexp_replace(lower(coalesce(name, '')), '^lad\s+', '', 'i'), '\s+', ' ', 'g') = ANY($1::text[])
           OR regexp_replace(regexp_replace(lower(coalesce(name, '')), '^(lad\s+)?led\s+', '', 'i'), '\s+', ' ', 'g') = $2
        ORDER BY CASE
            WHEN regexp_replace(lower(coalesce(name, '')), '\s+', ' ', 'g') = ANY($1::text[]) THEN 0
            WHEN regexp_replace(regexp_replace(lower(coalesce(name, '')), '^lad\s+', '', 'i'), '\s+', ' ', 'g') = ANY($1::text[]) THEN 1
            WHEN regexp_replace(regexp_replace(lower(coalesce(name, '')), '^(lad\s+)?led\s+', '', 'i'), '\s+', ' ', 'g') = $2 THEN 2
            ELSE 99
        END, name
        LIMIT $3 OFFSET $4
        """,
        name_variants,
        core_name,
        limit,
        offset,
    )


def _portfolio_examples_response(
    *,
    query: str,
    status: str,
    filters: dict[str, Any],
    lamp: dict[str, Any] | None = None,
    spheres: list[dict[str, Any]] | None = None,
    portfolio_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    examples = portfolio_examples or []
    payload = {
        "status": status,
        "kind": "portfolio_examples_by_lamp",
        "query": query,
        "filters": filters,
        "results": examples,
        "portfolio_examples": examples,
    }
    if lamp is not None:
        payload["lamp"] = lamp
    if spheres is not None:
        payload["spheres"] = spheres
    return payload


def _log_portfolio_examples_result(
    *,
    status: str,
    lamp_id: Any = None,
    category_id: Any = None,
    sphere_count: int = 0,
    portfolio_count: int = 0,
) -> None:
    logger.info(
        "corp-db portfolio_examples_by_lamp status=%s request_id=%s lamp_id=%s category_id=%s sphere_count=%s portfolio_count=%s",
        status,
        REQUEST_ID.get("-"),
        lamp_id,
        category_id,
        sphere_count,
        portfolio_count,
    )


def _sanitize_filter_defaults(req: CorpDbSearchRequest) -> CorpDbSearchRequest:
    updates: dict[str, Any] = {}
    for field_name, value in req.__dict__.items():
        if field_name == "kind":
            continue
        if isinstance(value, str) and not value.strip():
            updates[field_name] = None
    for field_name in HYBRID_ZERO_AS_UNSET_FIELDS:
        value = getattr(req, field_name)
        if value == 0 or value == 0.0:
            updates[field_name] = None
    if req.temp_c_min == 0:
        updates["temp_c_min"] = None
    if req.temp_c_max == 0:
        updates["temp_c_max"] = None
    if req.explosion_protected is False:
        updates["explosion_protected"] = None
    if not updates:
        return req
    return _request_like(req, **updates)


def _normalize_dimension_filter(text: str) -> str:
    return re.sub(r"[^0-9x]+", "", text.lower().replace("х", "x"))


def _normalize_range_bound(value: Any, *, column: str) -> Any:
    if value is None:
        return None
    if column in DECIMAL_RANGE_COLUMNS and isinstance(value, (float, Decimal)):
        return Decimal(str(value))
    return value


def _is_decimal_equality_range(minimum: Any, maximum: Any, *, column: str) -> bool:
    if column not in DECIMAL_RANGE_COLUMNS or minimum is None or maximum is None:
        return False
    return Decimal(str(minimum)) == Decimal(str(maximum))


def _normalize_query_text(query: str) -> str:
    text = _normalize_ws(query).lower().replace("\u00a0", " ")
    text = re.sub(r"\bip[\s-]?(\d{2,3})\b", lambda m: f"ip{m.group(1)}", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(\d{1,4})\s*(?:ватт|вт|w)\b",
        lambda m: f"{m.group(1)}w {m.group(1)} вт",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(\d{4,5})\s*(?:k|к)\b",
        lambda m: f"{m.group(1)}k {m.group(1)} к",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(\d{3,6})\s*(?:lm|лм)\b",
        lambda m: f"{m.group(1)}lm {m.group(1)} лм",
        text,
        flags=re.IGNORECASE,
    )
    return _normalize_ws(text)


def _normalize_lamp_exact_name(value: str) -> str:
    return _normalize_ws(str(value).replace("\u00a0", " ").strip()).lower()


def _lamp_exact_name_variants(value: str) -> tuple[list[str], str]:
    raw = _normalize_lamp_exact_name(value)
    without_brand = _normalize_ws(re.sub(r"^lad\s+", "", raw, flags=re.IGNORECASE))
    without_brand_led = _normalize_ws(re.sub(r"^(?:lad\s+)?led\s+", "", raw, flags=re.IGNORECASE))

    variants: list[str] = []
    for candidate in (raw, without_brand, without_brand_led):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants, without_brand_led or raw


def _strong_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in QUERY_TOKEN_RE.findall(_normalize_query_text(query)):
        normalized = token.lower()
        if normalized in NOISE_TOKENS:
            continue
        if len(normalized) < 2 and not any(char.isdigit() for char in normalized):
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms[:6]


def _query_has_identifier_terms(query: str) -> bool:
    for token in QUERY_TOKEN_RE.findall(_normalize_query_text(query)):
        normalized = token.lower()
        if len(normalized) < 3:
            continue
        if re.fullmatch(r"ip\d{2,3}", normalized):
            continue
        if re.fullmatch(r"\d+(?:w|k|lm)", normalized):
            continue
        has_alpha = any(char.isalpha() for char in normalized)
        has_digit = any(char.isdigit() for char in normalized)
        if has_alpha and has_digit:
            return True
        if has_digit and "-" in normalized:
            return True
    return False


def _explicit_lamp_filter_count(req: CorpDbSearchRequest) -> int:
    count = 0
    for field_name, _ in LAMP_TEXT_FILTER_SPECS:
        if getattr(req, field_name) not in (None, ""):
            count += 1
    for field_name, _ in LAMP_EXACT_FILTER_SPECS:
        if getattr(req, field_name) not in (None, ""):
            count += 1
    for field_name, _ in LAMP_BOOLEAN_FILTER_SPECS:
        if getattr(req, field_name) is not None:
            count += 1
    for min_field, max_field, _ in LAMP_RANGE_FILTER_SPECS:
        if getattr(req, min_field) is not None or getattr(req, max_field) is not None:
            count += 1
    if req.temp_c_min is not None or req.temp_c_max is not None:
        count += 1
    return count


def _is_filter_heavy_query(req: CorpDbSearchRequest, query: str) -> bool:
    if not _has_explicit_lamp_filters(req):
        return False
    strong_terms = _strong_query_terms(query)
    return _explicit_lamp_filter_count(req) >= 2 or len(strong_terms) >= 4 or len(query) >= 48


def _should_short_circuit_lamp_filters(
    req: CorpDbSearchRequest,
    *,
    query: str,
    entity_types: list[str] | None,
    direct_filter_rows: list[dict[str, Any]],
) -> bool:
    if not direct_filter_rows:
        return False
    if entity_types and any(entity_type != "lamp" for entity_type in entity_types):
        return False
    return _is_filter_heavy_query(req, query) and not _query_has_identifier_terms(query)


def _should_enable_fuzzy(req: CorpDbSearchRequest, query: str, profile_name: str) -> bool:
    if req.fuzzy:
        return not _is_filter_heavy_query(req, query)
    strong_terms = _strong_query_terms(query)
    if _is_filter_heavy_query(req, query):
        return False
    if profile_name == "candidate_generation" and len(strong_terms) >= 4:
        return False
    return len(strong_terms) <= 3 and len(query) <= 64


def _should_run_semantic_fallback(
    *,
    explicit_lamp_filters: bool,
    direct_filter_rows: list[dict[str, Any]],
    primary_rows: list[dict[str, Any]],
    primary_has_lexical_signal: bool,
) -> bool:
    if direct_filter_rows:
        return False
    if explicit_lamp_filters and primary_rows:
        return False
    return not primary_rows or not primary_has_lexical_signal


def _should_run_token_fallback(
    *,
    query: str,
    explicit_lamp_filters: bool,
    direct_filter_rows: list[dict[str, Any]],
    primary_rows: list[dict[str, Any]],
    primary_has_lexical_signal: bool,
) -> bool:
    strong_terms = _strong_query_terms(query)
    if not strong_terms:
        return False
    if explicit_lamp_filters or direct_filter_rows:
        return False
    if len(strong_terms) > 4 or len(query) > 72:
        return False
    return not primary_rows or not primary_has_lexical_signal


def _should_run_alias_fallback_for_token(token: str) -> bool:
    normalized = token.strip().lower()
    if not normalized:
        return False
    return _query_has_identifier_terms(normalized) or len(normalized) <= 5


def _extract_filter_retry(query: str) -> dict[str, Any]:
    normalized = _normalize_query_text(query)
    filters: dict[str, Any] = {}

    match = IP_RE.search(normalized)
    if match:
        filters["ip"] = f"IP{match.group(1)}"

    match = POWER_RE.search(normalized)
    if match:
        value = int(match.group(1))
        tolerance = max(5, min(20, int(round(value * 0.15))))
        filters["power_w_min"] = max(0, value - tolerance)
        filters["power_w_max"] = value + tolerance

    match = CCT_RE.search(normalized)
    if match:
        value = int(match.group(1))
        filters["cct_k_min"] = max(0, value - 250)
        filters["cct_k_max"] = value + 250

    match = LUMEN_RE.search(normalized)
    if match:
        value = int(match.group(1))
        tolerance = max(250, min(2000, int(round(value * 0.2))))
        filters["flux_lm_min"] = max(0, value - tolerance)
        filters["flux_lm_max"] = value + tolerance

    lowered = normalized.lower()
    for needle, mounting_type in MOUNTING_HINTS.items():
        if needle in lowered:
            filters["mounting_type"] = mounting_type
            break

    if "взрыв" in lowered or "2ex" in lowered or "ex" in lowered:
        filters["explosion_protected"] = True

    return filters


def _has_explicit_lamp_filters(req: CorpDbSearchRequest) -> bool:
    for field_name, _ in LAMP_TEXT_FILTER_SPECS:
        if getattr(req, field_name) not in (None, ""):
            return True
    for field_name, _ in LAMP_EXACT_FILTER_SPECS:
        if getattr(req, field_name) not in (None, ""):
            return True
    for field_name, _ in LAMP_BOOLEAN_FILTER_SPECS:
        if getattr(req, field_name) is not None:
            return True
    for min_field, max_field, _ in LAMP_RANGE_FILTER_SPECS:
        if getattr(req, min_field) is not None or getattr(req, max_field) is not None:
            return True
    return req.temp_c_min is not None or req.temp_c_max is not None


def _build_lamp_conditions(
    req: CorpDbSearchRequest,
    *,
    alias: str = "l",
    param_offset: int = 0,
) -> tuple[list[str], list[Any], dict[str, Any]]:
    conditions = ["TRUE"]
    args: list[Any] = []
    filters: dict[str, Any] = {}

    for field_name, column in LAMP_TEXT_FILTER_SPECS:
        value = getattr(req, field_name)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if field_name == "dimensions_raw":
            normalized = _normalize_dimension_filter(text)
            if not normalized:
                continue
            args.append(normalized)
            filters[field_name] = text
            conditions.append(
                "regexp_replace(lower(coalesce("
                f"{alias}.{column}, '')), '[^0-9x]+', '', 'g') LIKE ('%' || ${len(args) + param_offset} || '%')"
            )
            continue
        args.append(text)
        filters[field_name] = text
        conditions.append(f"coalesce({alias}.{column}, '') ILIKE ('%' || ${len(args) + param_offset} || '%')")

    for field_name, column in LAMP_EXACT_FILTER_SPECS:
        value = getattr(req, field_name)
        if value is None:
            continue
        if field_name == "voltage_kind":
            normalized = str(value).strip().upper()
            if not normalized:
                continue
            args.append(normalized)
            filters[field_name] = normalized
            param_ref = f"${len(args) + param_offset}"
            conditions.append(
                "("
                f"nullif(trim(coalesce({alias}.{column}, '')), '') IS NULL "
                f"OR upper({alias}.{column}) = {param_ref} "
                f"OR upper({alias}.{column}) = 'AC/DC' "
                f"OR ({param_ref} = 'AC/DC' AND upper({alias}.{column}) IN ('AC', 'DC'))"
                ")"
            )
            continue
        args.append(value)
        filters[field_name] = value
        conditions.append(f"{alias}.{column} = ${len(args) + param_offset}")

    for field_name, column in LAMP_BOOLEAN_FILTER_SPECS:
        value = getattr(req, field_name)
        if value is None:
            continue
        args.append(value)
        filters[field_name] = value
        conditions.append(f"{alias}.{column} = ${len(args) + param_offset}")

    for min_field, max_field, column in LAMP_RANGE_FILTER_SPECS:
        minimum = getattr(req, min_field)
        maximum = getattr(req, max_field)
        normalized_min = _normalize_range_bound(minimum, column=column)
        normalized_max = _normalize_range_bound(maximum, column=column)

        # Treat exact equality-style ranges on numeric columns as a tiny closed interval.
        # This avoids false empties from float -> SQL transport while keeping normal ranges unchanged.
        if _is_decimal_equality_range(normalized_min, normalized_max, column=column):
            args.append(normalized_min - DECIMAL_EQUALITY_TOLERANCE)
            filters[min_field] = minimum
            conditions.append(f"{alias}.{column} >= ${len(args) + param_offset}")
            args.append(normalized_max + DECIMAL_EQUALITY_TOLERANCE)
            filters[max_field] = maximum
            conditions.append(f"{alias}.{column} <= ${len(args) + param_offset}")
            continue

        if minimum is not None:
            args.append(normalized_min)
            filters[min_field] = minimum
            conditions.append(f"{alias}.{column} >= ${len(args) + param_offset}")
        if maximum is not None:
            args.append(normalized_max)
            filters[max_field] = maximum
            conditions.append(f"{alias}.{column} <= ${len(args) + param_offset}")

    if req.temp_c_min is not None:
        args.append(req.temp_c_min)
        filters["temp_c_min"] = req.temp_c_min
        conditions.append(f"{alias}.operating_temperature_max_c >= ${len(args) + param_offset}")
    if req.temp_c_max is not None:
        args.append(req.temp_c_max)
        filters["temp_c_max"] = req.temp_c_max
        conditions.append(f"{alias}.operating_temperature_min_c <= ${len(args) + param_offset}")

    return conditions, args, filters


async def _run_hybrid_query(
    conn: asyncpg.Connection,
    *,
    query: str,
    embedding: list[float] | None,
    limit: int,
    full_text_weight: float,
    semantic_weight: float,
    fuzzy_weight: float,
    entity_types: list[str] | None,
    include_debug: bool,
) -> list[asyncpg.Record]:
    return await conn.fetch(
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
        include_debug,
    )


async def _run_alias_fallback_query(
    conn: asyncpg.Connection,
    *,
    token: str,
    limit: int,
    entity_types: list[str] | None,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            d.doc_id,
            d.entity_type,
            d.entity_id,
            d.title,
            d.content,
            d.metadata,
            greatest(
                similarity(lower(d.title), lower($1)),
                similarity(lower(d.aliases), lower($1))
            )::double precision AS score,
            jsonb_build_object(
                'fts', jsonb_build_object('rank_ix', null, 'rank_score', null),
                'fuzzy', jsonb_build_object('rank_ix', 1, 'similarity_score', greatest(
                    similarity(lower(d.title), lower($1)),
                    similarity(lower(d.aliases), lower($1))
                )),
                'semantic', jsonb_build_object('rank_ix', null, 'cosine_similarity', null)
            ) AS debug_info
        FROM corp.corp_search_docs d
        WHERE ($3::text[] IS NULL OR d.entity_type = ANY($3))
          AND (
              lower(d.title) LIKE ('%' || lower($1) || '%')
              OR lower(d.aliases) LIKE ('%' || lower($1) || '%')
          )
        ORDER BY score DESC, d.doc_id
        LIMIT $2
        """,
        token,
        limit,
        entity_types,
    )

def _merge_hybrid_results(groups: list[tuple[str, list[dict[str, Any]]]], limit: int) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for label, rows in groups:
        label_bonus = 0.0
        if label == "filters":
            label_bonus = 0.2
        elif label != "primary":
            label_bonus = 0.05
        for rank, row in enumerate(rows, start=1):
            key = (str(row["entity_type"]), str(row["entity_id"]))
            bonus = label_bonus + (1.0 / (40 + rank))
            existing = merged.get(key)
            if existing is None:
                current = dict(row)
                current["score"] = round(float(row.get("score", 0.0)) + bonus, 6)
                current["search_strategy"] = [label]
                if "debug_info" in current and current["debug_info"] is None:
                    current.pop("debug_info")
                merged[key] = current
                continue

            existing["score"] = round(float(existing.get("score", 0.0)) + bonus, 6)
            strategies = existing.setdefault("search_strategy", [])
            if label not in strategies:
                strategies.append(label)

    ordered = sorted(
        merged.values(),
        key=lambda row: (-float(row.get("score", 0.0)), str(row.get("entity_type")), str(row.get("entity_id"))),
    )
    return ordered[:limit]


async def _filter_hybrid_lamp_rows(
    conn: asyncpg.Connection,
    rows: list[dict[str, Any]],
    req: CorpDbSearchRequest,
) -> list[dict[str, Any]]:
    lamp_ids = [int(row["entity_id"]) for row in rows if row.get("entity_type") == "lamp" and str(row.get("entity_id", "")).isdigit()]
    if not lamp_ids:
        return [row for row in rows if row.get("entity_type") != "lamp" and not _has_explicit_lamp_filters(req)]

    conditions, args, _ = _build_lamp_conditions(req, alias="l", param_offset=1)
    filtered_rows = await conn.fetch(
        f"""
        SELECT *
        FROM corp.v_catalog_lamps_agent l
        WHERE l.lamp_id = ANY($1::bigint[])
          AND {' AND '.join(conditions)}
        """,
        lamp_ids,
        *args,
    )
    payload_by_id = {str(row["lamp_id"]): _serialize_lamp_row(row) for row in filtered_rows}

    enriched: list[dict[str, Any]] = []
    for row in rows:
        if row.get("entity_type") != "lamp":
            if not _has_explicit_lamp_filters(req):
                enriched.append(row)
            continue
        payload = payload_by_id.get(str(row.get("entity_id")))
        if not payload:
            continue
        updated = dict(row)
        updated["metadata"] = payload["metadata"]
        updated["preview"] = payload["preview"]
        updated["agent_summary"] = payload["agent_summary"]
        updated["facts"] = payload["facts"]
        enriched.append(updated)
    return enriched


async def _hybrid_search(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int) -> dict[str, Any]:
    # Strategy:
    # 1) explicit structured lamp filters get the first, authoritative cheap path via lamp_filters;
    # 2) hybrid starts with lexical-only search and delays embeddings until lexical evidence is weak;
    # 3) token/alias fallback is skipped once structured filters already produced usable lamp results.
    req = _sanitize_filter_defaults(req)
    query = _req_str(req.query, "query", max_len=400)
    profile_name = req.profile or "entity_resolver"
    preset = PROFILE_PRESETS[profile_name]
    explicit_lamp_filters = _has_explicit_lamp_filters(req)
    requested_entity_types = req.entity_types or preset["entity_types"]
    if explicit_lamp_filters and not req.entity_types:
        requested_entity_types = ["lamp"]
    entity_types = _normalize_entity_types(requested_entity_types)
    response_filters = _hybrid_response_filters(
        profile_name=profile_name,
        entity_types=entity_types,
        explicit_lamp_filters=explicit_lamp_filters,
        search_strategy="primary",
    )
    full_text_weight, semantic_weight, fuzzy_weight = preset["weights"]
    fuzzy_enabled = _should_enable_fuzzy(req, query, profile_name)
    lexical_fuzzy_weight = fuzzy_weight if fuzzy_enabled else 0.0

    query_limit = limit
    if explicit_lamp_filters:
        query_limit = max(limit, 10)

    direct_filter_rows: list[dict[str, Any]] = []
    if explicit_lamp_filters:
        async with _observe_search_phase(
            kind="hybrid_search",
            profile=profile_name,
            phase="lamp_filters",
            attributes={"corp_db.fast_path": True},
        ):
            direct_filter_result = await _lamp_filters(conn, _request_like(req, kind="lamp_filters"), limit, 0)
        if direct_filter_result["results"]:
            direct_filter_rows = [
                _hybrid_row_from_lamp_payload(row, 0.95 - index * 0.01, "lamp_filters")
                for index, row in enumerate(direct_filter_result["results"])
            ]
            if _should_short_circuit_lamp_filters(
                req,
                query=query,
                entity_types=entity_types,
                direct_filter_rows=direct_filter_rows,
            ):
                response_filters["search_strategy"] = "lamp_filters"
                return _success(
                    "hybrid_search",
                    query=query,
                    filters=response_filters,
                    results=direct_filter_rows[:limit],
                    debug={
                        "strategy": "lamp_filters",
                        "reason": "explicit_filter_fast_path",
                        "semantic_enabled": False,
                        "fuzzy_enabled": False,
                    }
                    if req.include_debug
                    else None,
                )

    async with _observe_search_phase(
        kind="hybrid_search",
        profile=profile_name,
        phase="hybrid_primary",
        attributes={
            "corp_db.semantic_enabled": False,
            "corp_db.fuzzy_enabled": fuzzy_enabled,
            "corp_db.entity_types": ",".join(entity_types or []),
        },
    ):
        rows = await _run_hybrid_query(
            conn,
            query=query,
            embedding=None,
            limit=query_limit,
            full_text_weight=full_text_weight,
            semantic_weight=0.0,
            fuzzy_weight=lexical_fuzzy_weight,
            entity_types=entity_types,
            include_debug=req.include_debug,
        )
    primary_rows = [_hybrid_row(row) for row in rows]
    if explicit_lamp_filters and primary_rows:
        primary_rows = await _filter_hybrid_lamp_rows(conn, primary_rows, req)

    if direct_filter_rows:
        async with _observe_search_phase(kind="hybrid_search", profile=profile_name, phase="merge"):
            groups: list[tuple[str, list[dict[str, Any]]]] = []
            if primary_rows:
                groups.append(("primary", primary_rows))
            groups.append(("lamp_filters", direct_filter_rows))
            primary_rows = _merge_hybrid_results(groups, limit)

    primary_has_lexical_signal = _rows_have_lexical_signal(rows)
    filter_retry = _extract_filter_retry(query) if profile_name == "candidate_generation" else {}
    should_run_filter_fallback = bool(filter_retry) and not direct_filter_rows
    should_run_semantic = _should_run_semantic_fallback(
        explicit_lamp_filters=explicit_lamp_filters,
        direct_filter_rows=direct_filter_rows,
        primary_rows=primary_rows,
        primary_has_lexical_signal=primary_has_lexical_signal,
    )
    should_run_token_fallback = _should_run_token_fallback(
        query=query,
        explicit_lamp_filters=explicit_lamp_filters,
        direct_filter_rows=direct_filter_rows,
        primary_rows=primary_rows,
        primary_has_lexical_signal=primary_has_lexical_signal,
    )

    primary_strategy = "lamp_filters" if direct_filter_rows and not rows else "primary"

    if primary_rows and not should_run_filter_fallback and not should_run_semantic and not should_run_token_fallback:
        return _success(
            "hybrid_search",
            query=query,
            filters=_hybrid_response_filters(
                profile_name=profile_name,
                entity_types=entity_types,
                explicit_lamp_filters=explicit_lamp_filters,
                search_strategy=primary_strategy,
            ),
            results=primary_rows,
            debug={
                "strategy": primary_strategy,
                "semantic_enabled": False,
                "fuzzy_enabled": fuzzy_enabled,
            }
            if req.include_debug
            else None,
        )

    fallback_groups: list[tuple[str, list[dict[str, Any]]]] = []
    merged_groups: list[tuple[str, list[dict[str, Any]]]] = [("primary", primary_rows)] if primary_rows else []
    debug_reason = "primary_empty" if not rows else "lexical_only"

    if should_run_semantic:
        embedding: list[float] | None = None
        async with _observe_search_phase(kind="hybrid_search", profile=profile_name, phase="embedding"):
            embedding = await _get_query_embedding(query)
        if embedding is None:
            CORP_DB_EMBEDDINGS_UNAVAILABLE_TOTAL.labels(profile_name).inc()
            debug_reason = "semantic_unavailable"
        else:
            async with _observe_search_phase(
                kind="hybrid_search",
                profile=profile_name,
                phase="hybrid_primary",
                attributes={
                    "corp_db.semantic_enabled": True,
                    "corp_db.fuzzy_enabled": fuzzy_enabled,
                    "corp_db.entity_types": ",".join(entity_types or []),
                },
            ):
                semantic_rows = await _run_hybrid_query(
                    conn,
                    query=query,
                    embedding=embedding,
                    limit=query_limit,
                    full_text_weight=full_text_weight,
                    semantic_weight=semantic_weight,
                    fuzzy_weight=lexical_fuzzy_weight,
                    entity_types=entity_types,
                    include_debug=req.include_debug,
                )
            formatted_semantic = [_hybrid_row(row) for row in semantic_rows]
            if explicit_lamp_filters and formatted_semantic:
                formatted_semantic = await _filter_hybrid_lamp_rows(conn, formatted_semantic, req)
            if formatted_semantic:
                fallback_groups.append(("semantic", formatted_semantic))
                debug_reason = "semantic_fallback"

    if should_run_filter_fallback:
        filter_req = _request_like(req, kind="lamp_filters", **filter_retry)
        async with _observe_search_phase(kind="hybrid_search", profile=profile_name, phase="lamp_filters"):
            filter_result = await _lamp_filters(conn, filter_req, limit, 0)
        if filter_result["results"]:
            fallback_groups.append(
                (
                    "filters",
                    [
                        _hybrid_row_from_lamp_payload(row, 0.95 - index * 0.01, "filters")
                        for index, row in enumerate(filter_result["results"])
                    ],
                )
            )

    token_queries: list[tuple[str, str]] = []
    normalized_query = _normalize_query_text(query)
    if normalized_query and normalized_query != query:
        token_queries.append(("normalized", normalized_query))

    strong_terms = _strong_query_terms(query)
    if len(strong_terms) >= 2:
        token_queries.append(("strong_terms", " ".join(strong_terms[:4])))
    for token in strong_terms[:4]:
        token_queries.append((f"token:{token}", token))

    seen_queries: set[str] = set()
    deduped_token_queries: list[tuple[str, str]] = []
    for label, token_query in token_queries:
        if token_query and token_query not in seen_queries:
            seen_queries.add(token_query)
            deduped_token_queries.append((label, token_query))

    if should_run_token_fallback:
        for label, token_query in deduped_token_queries[:5]:
            async with _observe_search_phase(
                kind="hybrid_search",
                profile=profile_name,
                phase="token_fallback",
                attributes={"corp_db.retry_query": token_query[:120], "corp_db.retry_label": label},
            ):
                retry_rows = await _run_hybrid_query(
                    conn,
                    query=token_query,
                    embedding=None,
                    limit=max(limit, 3),
                    full_text_weight=max(full_text_weight, 1.05),
                    semantic_weight=0.0,
                    fuzzy_weight=max(lexical_fuzzy_weight, 1.1 if fuzzy_enabled else 0.0),
                    entity_types=entity_types,
                    include_debug=req.include_debug,
                )
            formatted = [_hybrid_row(row) for row in retry_rows]
            if explicit_lamp_filters and formatted:
                formatted = await _filter_hybrid_lamp_rows(conn, formatted, req)
            if not formatted and label.startswith("token:") and _should_run_alias_fallback_for_token(token_query):
                async with _observe_search_phase(
                    kind="hybrid_search",
                    profile=profile_name,
                    phase="alias_fallback",
                    attributes={"corp_db.retry_query": token_query[:120], "corp_db.retry_label": label},
                ):
                    alias_rows = await _run_alias_fallback_query(
                        conn,
                        token=token_query,
                        limit=max(limit, 3),
                        entity_types=entity_types,
                    )
                formatted = [_hybrid_row(row) for row in alias_rows]
                if explicit_lamp_filters and formatted:
                    formatted = await _filter_hybrid_lamp_rows(conn, formatted, req)
            if formatted:
                fallback_groups.append((label, formatted))

    async with _observe_search_phase(kind="hybrid_search", profile=profile_name, phase="merge"):
        merged_rows = _merge_hybrid_results([*merged_groups, *fallback_groups], limit)
    if merged_rows:
        logger.info(
            "corp-db hybrid fallback used profile=%s query=%r reason=%s strategy=%s",
            profile_name,
            query[:120],
            debug_reason,
            ",".join(label for label, _ in [*merged_groups, *fallback_groups]),
        )
    return _success(
        "hybrid_search",
        query=query,
        filters=_hybrid_response_filters(
            profile_name=profile_name,
            entity_types=entity_types,
            explicit_lamp_filters=explicit_lamp_filters,
            search_strategy="fallback" if fallback_groups else primary_strategy,
        ),
        results=merged_rows,
        debug={
            "strategy": "fallback" if fallback_groups else "primary",
            "reason": debug_reason,
            "queries": [label for label, _ in deduped_token_queries],
            "primary_has_lexical_signal": primary_has_lexical_signal,
            "semantic_enabled": any(label == "semantic" for label, _ in fallback_groups),
            "fuzzy_enabled": fuzzy_enabled,
        }
        if (req.include_debug or fallback_groups)
        else None,
    )


async def _lamp_exact(conn: asyncpg.Connection, req: CorpDbSearchRequest, limit: int, offset: int) -> dict[str, Any]:
    name = _req_str(req.name, "name")
    rows = await _fetch_lamp_exact_rows(conn, name=name, limit=limit, offset=offset)
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
            _serialize_lamp_row(
                row,
                documents=docs.get(row["lamp_id"], {}),
                sku=skus_by_lamp.get(row["lamp_id"], []),
            )
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
        SELECT l.*
        FROM corp.v_catalog_lamps_agent l
        WHERE CASE
            WHEN $1 THEN coalesce(l.category_name, '') ILIKE ('%' || $2 || '%')
            ELSE lower(coalesce(l.category_name, '')) = lower($2)
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
        results=[_serialize_lamp_row(row) for row in rows],
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


async def _portfolio_examples_by_lamp(
    conn: asyncpg.Connection,
    req: CorpDbSearchRequest,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    query = _req_str(req.name, "name")
    profile_name = "exact_chain"

    async with _observe_search_phase(
        kind="portfolio_examples_by_lamp",
        profile=profile_name,
        phase="lamp_exact",
        span_name="corp_db.portfolio_examples.lamp_exact",
    ):
        lamp_rows = await _fetch_lamp_exact_rows(conn, name=query, limit=1, offset=0)

    if not lamp_rows:
        response = _portfolio_examples_response(
            query=query,
            status="empty",
            filters={"reason": "lamp_not_found"},
        )
        _log_portfolio_examples_result(status="empty")
        return response

    lamp_row = lamp_rows[0]
    lamp_payload = _serialize_lamp_row(lamp_row)
    category_id = _row_get(lamp_row, "category_id")
    category_name = _row_get(lamp_row, "category_name")
    lamp_id = _row_get(lamp_row, "lamp_id")

    if category_id is None:
        response = _portfolio_examples_response(
            query=query,
            status="empty",
            filters={
                "reason": "category_missing",
                "lamp_id": lamp_id,
            },
            lamp=lamp_payload,
        )
        _log_portfolio_examples_result(status="empty", lamp_id=lamp_id)
        return response

    async with _observe_search_phase(
        kind="portfolio_examples_by_lamp",
        profile=profile_name,
        phase="sphere_lookup",
        span_name="corp_db.portfolio_examples.sphere_lookup",
        attributes={"corp_db.category_id": int(category_id)},
    ):
        sphere_rows = await conn.fetch(
            """
            SELECT s.sphere_id, s.name AS sphere_name
            FROM corp.sphere_categories sc
            JOIN corp.spheres s ON s.sphere_id = sc.sphere_id
            WHERE sc.category_id = $1
            ORDER BY s.name
            """,
            category_id,
        )

    spheres = [dict(row) for row in sphere_rows]
    if not spheres:
        response = _portfolio_examples_response(
            query=query,
            status="empty",
            filters={
                "reason": "spheres_not_found",
                "lamp_id": lamp_id,
                "category_id": category_id,
                "category_name": category_name,
                "sphere_count": 0,
            },
            lamp=lamp_payload,
            spheres=[],
        )
        _log_portfolio_examples_result(status="empty", lamp_id=lamp_id, category_id=category_id)
        return response

    sphere_ids = [row["sphere_id"] for row in spheres]
    async with _observe_search_phase(
        kind="portfolio_examples_by_lamp",
        profile=profile_name,
        phase="portfolio_lookup",
        span_name="corp_db.portfolio_examples.portfolio_lookup",
        attributes={"corp_db.sphere_count": len(sphere_ids)},
    ):
        portfolio_rows = await conn.fetch(
            """
            SELECT p.portfolio_id, p.name, p.url, p.group_name, p.image_url, s.sphere_id, s.name AS sphere_name
            FROM corp.portfolio p
            JOIN corp.spheres s ON s.sphere_id = p.sphere_id
            WHERE p.sphere_id = ANY($1::bigint[])
            ORDER BY s.name, p.name
            LIMIT $2 OFFSET $3
            """,
            sphere_ids,
            limit,
            offset,
        )

    portfolio_examples = [dict(row) for row in portfolio_rows]
    if not portfolio_examples:
        response = _portfolio_examples_response(
            query=query,
            status="empty",
            filters={
                "reason": "portfolio_not_found",
                "lamp_id": lamp_id,
                "category_id": category_id,
                "category_name": category_name,
                "sphere_count": len(spheres),
            },
            lamp=lamp_payload,
            spheres=spheres,
        )
        _log_portfolio_examples_result(
            status="empty",
            lamp_id=lamp_id,
            category_id=category_id,
            sphere_count=len(spheres),
        )
        return response

    async with _observe_search_phase(
        kind="portfolio_examples_by_lamp",
        profile=profile_name,
        phase="response_build",
        span_name="corp_db.portfolio_examples.response_build",
    ):
        response = _portfolio_examples_response(
            query=query,
            status="success",
            filters={
                "lamp_match": "exact",
                "category_id": category_id,
                "category_name": category_name,
                "sphere_count": len(spheres),
                "portfolio_count": len(portfolio_examples),
            },
            lamp=lamp_payload,
            spheres=spheres,
            portfolio_examples=portfolio_examples,
        )

    _log_portfolio_examples_result(
        status="success",
        lamp_id=lamp_id,
        category_id=category_id,
        sphere_count=len(spheres),
        portfolio_count=len(portfolio_examples),
    )
    return response


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
    conditions, args, filters = _build_lamp_conditions(req, alias="l")

    args.extend([limit, offset])
    rows = await conn.fetch(
        f"""
        SELECT l.*
        FROM corp.v_catalog_lamps_agent l
        WHERE {' AND '.join(conditions)}
        ORDER BY l.name
        LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    return _success("lamp_filters", filters=filters, results=[_serialize_lamp_row(row) for row in rows])


@router.post("/search")
async def corp_db_search(req: CorpDbSearchRequest, request: Request):
    user_id = request.headers.get("X-User-Id", "")
    limit, offset = _clamp(req.limit, req.offset)
    started_at = perf_counter()
    profile_name = req.profile or "none"
    status = "error"
    req = _sanitize_filter_defaults(req)

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
            elif req.kind == "portfolio_examples_by_lamp":
                result = await _portfolio_examples_by_lamp(conn, req, limit, offset)
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
