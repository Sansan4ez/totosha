import logging
import os
from time import perf_counter

import asyncpg
import numpy as np
from openai import AsyncOpenAI
from opentelemetry import metrics, trace
from pgvector.asyncpg import register_vector

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536  # reduced from 3072 to fit HNSW index limit (max 2000)

_pool: asyncpg.Pool | None = None
_client: AsyncOpenAI | None = None
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)
embedding_duration = meter.create_histogram(
    "kb_embedding_duration_ms",
    unit="ms",
    description="Duration of embedding requests for KB search",
)
hybrid_search_duration = meter.create_histogram(
    "kb_hybrid_search_duration_ms",
    unit="ms",
    description="End-to-end duration of hybrid KB search",
)
db_query_duration = meter.create_histogram(
    "kb_db_query_duration_ms",
    unit="ms",
    description="Duration of the PostgreSQL hybrid_search function call",
)
result_count_histogram = meter.create_histogram(
    "kb_result_count",
    description="Number of KB rows returned by hybrid search",
)


def _dsn() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql://adk:adk@localhost:5432/adk_kb",
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _dsn(),
            min_size=1,
            max_size=5,
            init=_init_connection,
        )
        logger.info("Database connection pool created")
    return _pool


async def _init_connection(conn: asyncpg.Connection):
    await register_vector(conn)


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


async def get_embedding(text: str) -> np.ndarray:
    started_at = perf_counter()
    with tracer.start_as_current_span("kb.get_embedding") as span:
        span.set_attribute("embedding.model", EMBEDDING_MODEL)
        span.set_attribute("embedding.dimensions", EMBEDDING_DIMENSIONS)
        span.set_attribute("input.length", len(text))
        response = await get_openai_client().embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        embedding_duration.record(
            (perf_counter() - started_at) * 1000,
            {"embedding.model": EMBEDDING_MODEL},
        )
        return np.array(response.data[0].embedding, dtype=np.float32)


async def hybrid_search(
    query: str,
    match_count: int = 5,
    full_text_weight: float = 1.0,
    semantic_weight: float = 1.0,
    fuzzy_weight: float = 0.3,
) -> list[dict]:
    started_at = perf_counter()
    with tracer.start_as_current_span("kb.hybrid_search") as span:
        span.set_attribute("kb.match_count", match_count)
        span.set_attribute("kb.full_text_weight", full_text_weight)
        span.set_attribute("kb.semantic_weight", semantic_weight)
        span.set_attribute("kb.fuzzy_weight", fuzzy_weight)

        pool = await get_pool()
        query_embedding = await get_embedding(query)

        db_started_at = perf_counter()
        rows = await pool.fetch(
            "SELECT id, source_file, heading, content, rrf_score, debug_info "
            "FROM hybrid_search($1, $2, $3, $4, $5, $6)",
            query,
            query_embedding,
            match_count,
            full_text_weight,
            semantic_weight,
            fuzzy_weight,
        )
        db_query_duration.record(
            (perf_counter() - db_started_at) * 1000,
            {"db.system": "postgresql"},
        )

        results = []
        for row in rows:
            results.append(
                {
                    "id": row["id"],
                    "source_file": row["source_file"],
                    "heading": row["heading"],
                    "content": row["content"],
                    "score": row["rrf_score"],
                }
            )

        span.set_attribute("kb.result_count", len(results))
        result_count_histogram.record(len(results))
        hybrid_search_duration.record((perf_counter() - started_at) * 1000)
        return results
