-- Canonical definition of corp.corp_hybrid_search.
-- Applied on fresh initdb (via /docker-entrypoint-initdb.d) and re-applied to live
-- databases by the corp-db-migrator (ensure-rfc026), so signature changes here reach
-- volumes that were initialized with an older init.sql.

-- Legacy signature (before source_files support); dropped so positional callers can
-- never bind include_debug into the source_files slot.
DROP FUNCTION IF EXISTS corp.corp_hybrid_search(
    text, vector, integer,
    double precision, double precision, double precision,
    integer, text[], boolean
);

CREATE OR REPLACE FUNCTION corp.corp_hybrid_search(
    query_text text,
    query_embedding vector(1536) DEFAULT NULL,
    match_count integer DEFAULT 5,
    full_text_weight double precision DEFAULT 1.0,
    semantic_weight double precision DEFAULT 1.0,
    fuzzy_weight double precision DEFAULT 0.3,
    rrf_k integer DEFAULT 60,
    entity_types text[] DEFAULT NULL,
    source_files text[] DEFAULT NULL,
    include_debug boolean DEFAULT false
)
RETURNS TABLE (
    doc_id bigint,
    entity_type text,
    entity_id text,
    title text,
    content text,
    aliases text,
    metadata jsonb,
    score double precision,
    debug_info jsonb
)
LANGUAGE sql
STABLE
AS $$
WITH params AS (
    SELECT
        greatest(1, least(match_count, 20)) AS top_n,
        greatest(10, least(match_count * 4, 40)) AS candidate_limit,
        websearch_to_tsquery('russian', query_text) AS ru_query,
        websearch_to_tsquery('simple', query_text) AS simple_query
),
base_docs AS (
    SELECT *
    FROM corp.corp_search_docs d
    WHERE (entity_types IS NULL OR d.entity_type = ANY(entity_types))
      AND (source_files IS NULL OR coalesce(d.metadata->>'source_file', '') = ANY(source_files))
),
full_text AS (
    SELECT
        d.doc_id,
        row_number() OVER (
            ORDER BY greatest(
                ts_rank_cd(d.fts, p.ru_query, 32),
                ts_rank_cd(d.fts, p.simple_query, 32)
            ) DESC
        ) AS rank_ix,
        greatest(
            ts_rank_cd(d.fts, p.ru_query, 32),
            ts_rank_cd(d.fts, p.simple_query, 32)
        ) AS rank_score
    FROM base_docs d
    CROSS JOIN params p
    WHERE query_text IS NOT NULL
      AND btrim(query_text) <> ''
      AND (
          d.fts @@ p.ru_query
          OR d.fts @@ p.simple_query
      )
    ORDER BY rank_score DESC
    LIMIT (SELECT candidate_limit FROM params)
),
semantic AS (
    SELECT
        d.doc_id,
        row_number() OVER (ORDER BY d.embedding <#> query_embedding) AS rank_ix,
        1 - (d.embedding <=> query_embedding) AS cosine_similarity
    FROM base_docs d
    WHERE query_embedding IS NOT NULL
      AND d.embedding IS NOT NULL
    ORDER BY d.embedding <#> query_embedding
    LIMIT (SELECT candidate_limit FROM params)
),
fuzzy AS (
    SELECT
        d.doc_id,
        row_number() OVER (
            ORDER BY greatest(
                similarity(d.title, query_text),
                similarity(d.aliases, query_text),
                similarity(d.content, query_text)
            ) DESC
        ) AS rank_ix,
        greatest(
            similarity(d.title, query_text),
            similarity(d.aliases, query_text),
            similarity(d.content, query_text)
        ) AS similarity_score
    FROM base_docs d
    WHERE query_text IS NOT NULL
      AND btrim(query_text) <> ''
      AND (
          d.title % query_text
          OR d.aliases % query_text
          OR d.content % query_text
      )
    ORDER BY similarity_score DESC
    LIMIT (SELECT candidate_limit FROM params)
),
merged AS (
    SELECT
        coalesce(ft.doc_id, sem.doc_id, fz.doc_id) AS doc_id,
        (
            coalesce(1.0 / (rrf_k + ft.rank_ix), 0.0) * full_text_weight +
            coalesce(1.0 / (rrf_k + sem.rank_ix), 0.0) * semantic_weight +
            coalesce(1.0 / (rrf_k + fz.rank_ix), 0.0) * fuzzy_weight
        )::double precision AS score,
        CASE
            WHEN include_debug THEN jsonb_build_object(
                'fts', jsonb_build_object('rank_ix', ft.rank_ix, 'rank_score', ft.rank_score),
                'semantic', jsonb_build_object('rank_ix', sem.rank_ix, 'cosine_similarity', sem.cosine_similarity),
                'fuzzy', jsonb_build_object('rank_ix', fz.rank_ix, 'similarity_score', fz.similarity_score)
            )
            ELSE NULL
        END AS debug_info
    FROM full_text ft
    FULL OUTER JOIN semantic sem ON sem.doc_id = ft.doc_id
    FULL OUTER JOIN fuzzy fz ON fz.doc_id = coalesce(ft.doc_id, sem.doc_id)
)
SELECT
    d.doc_id,
    d.entity_type,
    d.entity_id,
    d.title,
    d.content,
    d.aliases,
    d.metadata,
    m.score,
    m.debug_info
FROM merged m
JOIN corp.corp_search_docs d ON d.doc_id = m.doc_id
ORDER BY m.score DESC, d.doc_id
LIMIT (SELECT top_n FROM params);
$$;

-- DROP + CREATE produces a new pg_proc entry, so re-grant explicitly instead of
-- relying on the one-time "GRANT ... ON ALL FUNCTIONS" from initdb.
GRANT EXECUTE ON FUNCTION corp.corp_hybrid_search(
    text, vector, integer,
    double precision, double precision, double precision,
    integer, text[], text[], boolean
) TO corp_rw, corp_ro;
