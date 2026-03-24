-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Knowledge base chunks table
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    source_file text NOT NULL,
    heading text NOT NULL,
    content text NOT NULL,
    fts tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('russian', coalesce(heading, '')), 'A') ||
        setweight(to_tsvector('russian', coalesce(content, '')), 'C')
    ) STORED,
    embedding vector(1536),
    file_hash text NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_chunks_fts ON knowledge_chunks USING gin (fts);

-- Trigram indexes for fuzzy search
CREATE INDEX IF NOT EXISTS idx_chunks_heading_trgm ON knowledge_chunks USING gin (heading gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm ON knowledge_chunks USING gin (content gin_trgm_ops);

-- Source file index for incremental updates
CREATE INDEX IF NOT EXISTS idx_chunks_source_file ON knowledge_chunks (source_file);

-- Semantic search index (IVFFlat) - created after data is loaded
-- Note: IVFFlat requires existing data for training, so we use HNSW instead
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- Hybrid search function using RRF (Reciprocal Rank Fusion)
CREATE OR REPLACE FUNCTION hybrid_search(
    query_text text,
    query_embedding vector(1536),
    match_count int DEFAULT 5,
    full_text_weight float DEFAULT 1.0,
    semantic_weight float DEFAULT 1.0,
    fuzzy_weight float DEFAULT 0.3,
    rrf_k int DEFAULT 60
)
RETURNS TABLE (
    id bigint,
    source_file text,
    heading text,
    content text,
    rrf_score float,
    debug_info jsonb
)
LANGUAGE sql
AS $$
    WITH full_text AS (
        SELECT
            kc.id,
            row_number() OVER (ORDER BY ts_rank_cd(kc.fts, websearch_to_tsquery('russian', query_text), 1) DESC) AS rank_ix,
            ts_rank_cd(kc.fts, websearch_to_tsquery('russian', query_text), 1) AS rank_score
        FROM knowledge_chunks kc
        WHERE kc.fts @@ websearch_to_tsquery('russian', query_text)
        ORDER BY rank_score DESC
        LIMIT least(match_count * 3, 30)
    ),
    semantic AS (
        SELECT
            kc.id,
            row_number() OVER (ORDER BY kc.embedding <#> query_embedding) AS rank_ix,
            1 - (kc.embedding <=> query_embedding) AS cosine_similarity
        FROM knowledge_chunks kc
        WHERE kc.embedding IS NOT NULL
        ORDER BY kc.embedding <#> query_embedding
        LIMIT least(match_count * 3, 30)
    ),
    fuzzy AS (
        SELECT
            kc.id,
            row_number() OVER (ORDER BY greatest(
                similarity(kc.heading, query_text),
                similarity(kc.content, query_text)
            ) DESC) AS rank_ix,
            greatest(
                similarity(kc.heading, query_text),
                similarity(kc.content, query_text)
            ) AS sim_score
        FROM knowledge_chunks kc
        WHERE
            kc.heading % query_text OR kc.content % query_text
        ORDER BY sim_score DESC
        LIMIT least(match_count * 3, 30)
    )
    SELECT
        kc.id,
        kc.source_file,
        kc.heading,
        kc.content,
        (
            coalesce(1.0 / (rrf_k + full_text.rank_ix), 0.0) * full_text_weight +
            coalesce(1.0 / (rrf_k + semantic.rank_ix), 0.0) * semantic_weight +
            coalesce(1.0 / (rrf_k + fuzzy.rank_ix), 0.0) * fuzzy_weight
        )::float AS rrf_score,
        jsonb_build_object(
            'fts', jsonb_build_object('rank_ix', full_text.rank_ix, 'rank_score', full_text.rank_score),
            'semantic', jsonb_build_object('rank_ix', semantic.rank_ix, 'cosine_similarity', semantic.cosine_similarity),
            'fuzzy', jsonb_build_object('rank_ix', fuzzy.rank_ix, 'sim_score', fuzzy.sim_score)
        ) AS debug_info
    FROM full_text
    FULL OUTER JOIN semantic ON full_text.id = semantic.id
    FULL OUTER JOIN fuzzy ON coalesce(full_text.id, semantic.id) = fuzzy.id
    JOIN knowledge_chunks kc ON coalesce(full_text.id, semantic.id, fuzzy.id) = kc.id
    ORDER BY rrf_score DESC
    LIMIT match_count;
$$;
