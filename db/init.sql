CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS corp;
REVOKE ALL ON SCHEMA corp FROM PUBLIC;

CREATE OR REPLACE FUNCTION corp.make_search_fts(title text, content text, aliases text)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $$
SELECT
    setweight(to_tsvector('russian', coalesce($1, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce($1, '')), 'A') ||
    setweight(to_tsvector('russian', coalesce($2, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce($2, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce($3, '')), 'A');
$$;

CREATE TABLE IF NOT EXISTS corp.categories (
    category_id bigint PRIMARY KEY,
    name text NOT NULL,
    url text,
    image_url text,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.catalog_lamps (
    lamp_id bigint PRIMARY KEY,
    category_id bigint REFERENCES corp.categories(category_id) ON DELETE SET NULL,
    category_name text,
    name text NOT NULL,
    url text,
    image_url text,
    luminous_flux_lm integer,
    power_w integer,
    beam_pattern text,
    mounting_type text,
    explosion_protection_marking text,
    is_explosion_protected boolean NOT NULL DEFAULT false,
    color_temperature_k integer,
    color_rendering_index_ra integer,
    power_factor_operator text,
    power_factor_min numeric(8, 3),
    climate_execution text,
    operating_temperature_range_raw text,
    operating_temperature_min_c integer,
    operating_temperature_max_c integer,
    ingress_protection text,
    electrical_protection_class text,
    supply_voltage_raw text,
    supply_voltage_kind text,
    supply_voltage_nominal_v integer,
    supply_voltage_min_v integer,
    supply_voltage_max_v integer,
    supply_voltage_tolerance_minus_pct numeric(8, 3),
    supply_voltage_tolerance_plus_pct numeric(8, 3),
    dimensions_raw text,
    length_mm numeric(10, 3),
    width_mm numeric(10, 3),
    height_mm numeric(10, 3),
    warranty_years integer,
    weight_kg numeric(10, 3),
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.catalog_lamp_documents (
    lamp_id bigint PRIMARY KEY REFERENCES corp.catalog_lamps(lamp_id) ON DELETE CASCADE,
    instruction_url text,
    blueprint_url text,
    passport_url text,
    certificate_url text,
    ies_url text,
    diffuser_url text,
    complete_docs_url text,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.catalog_lamp_properties_raw (
    raw_property_id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    lamp_id bigint NOT NULL REFERENCES corp.catalog_lamps(lamp_id) ON DELETE CASCADE,
    property_code text NOT NULL,
    property_name_ru text NOT NULL,
    property_value_raw text,
    property_measure_raw text,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.etm_oracl_catalog_sku (
    sku_id text PRIMARY KEY,
    lamp_id bigint REFERENCES corp.catalog_lamps(lamp_id) ON DELETE SET NULL,
    etm_code text,
    oracl_code text,
    short_box_name_wms text,
    catalog_1c text,
    box_name text,
    description text,
    comments text,
    is_active boolean NOT NULL DEFAULT true,
    archived_at text,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.mounting_types (
    mounting_type_id bigint PRIMARY KEY,
    name text NOT NULL,
    mark text,
    description text,
    image_url text,
    url text,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.category_mountings (
    category_mounting_id bigint PRIMARY KEY,
    category_id bigint REFERENCES corp.categories(category_id) ON DELETE CASCADE,
    series text NOT NULL,
    mounting_type_id bigint REFERENCES corp.mounting_types(mounting_type_id) ON DELETE CASCADE,
    is_default boolean NOT NULL DEFAULT false,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.spheres (
    sphere_id bigint PRIMARY KEY,
    name text NOT NULL,
    url text,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.sphere_categories (
    sphere_id bigint NOT NULL REFERENCES corp.spheres(sphere_id) ON DELETE CASCADE,
    category_id bigint NOT NULL REFERENCES corp.categories(category_id) ON DELETE CASCADE,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sphere_id, category_id)
);

CREATE TABLE IF NOT EXISTS corp.portfolio (
    portfolio_id text PRIMARY KEY,
    name text NOT NULL,
    url text,
    image_url text,
    group_name text,
    sphere_id bigint REFERENCES corp.spheres(sphere_id) ON DELETE SET NULL,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corp.knowledge_chunks (
    chunk_id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    source_file text NOT NULL,
    document_title text NOT NULL,
    chunk_index integer NOT NULL,
    heading text NOT NULL,
    content text NOT NULL,
    preview text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_hash text NOT NULL,
    fts tsvector GENERATED ALWAYS AS (
        corp.make_search_fts(document_title || ' ' || heading, content, source_file)
    ) STORED,
    embedding vector(1536),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_file, chunk_index)
);

CREATE TABLE IF NOT EXISTS corp.corp_search_docs (
    doc_id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    title text NOT NULL,
    content text NOT NULL DEFAULT '',
    aliases text NOT NULL DEFAULT '',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_hash text NOT NULL,
    fts tsvector GENERATED ALWAYS AS (
        corp.make_search_fts(title, content, aliases)
    ) STORED,
    embedding vector(1536),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_categories_name_trgm
    ON corp.categories USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_name_trgm
    ON corp.catalog_lamps USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_category_id
    ON corp.catalog_lamps (category_id);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_power_w
    ON corp.catalog_lamps (power_w);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_flux
    ON corp.catalog_lamps (luminous_flux_lm);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_cct
    ON corp.catalog_lamps (color_temperature_k);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_ip
    ON corp.catalog_lamps USING gin (ingress_protection gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_mounting
    ON corp.catalog_lamps USING gin (mounting_type gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_voltage_kind
    ON corp.catalog_lamps (supply_voltage_kind);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_temp_range
    ON corp.catalog_lamps (operating_temperature_min_c, operating_temperature_max_c);

CREATE INDEX IF NOT EXISTS idx_sku_lamp_id
    ON corp.etm_oracl_catalog_sku (lamp_id);
CREATE INDEX IF NOT EXISTS idx_sku_etm_code
    ON corp.etm_oracl_catalog_sku USING gin (etm_code gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sku_oracl_code
    ON corp.etm_oracl_catalog_sku USING gin (oracl_code gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_category_mountings_category_id
    ON corp.category_mountings (category_id);
CREATE INDEX IF NOT EXISTS idx_category_mountings_mounting_type_id
    ON corp.category_mountings (mounting_type_id);
CREATE INDEX IF NOT EXISTS idx_mounting_types_name_trgm
    ON corp.mounting_types USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mounting_types_mark_trgm
    ON corp.mounting_types USING gin (mark gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_portfolio_sphere_id
    ON corp.portfolio (sphere_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_name_trgm
    ON corp.portfolio USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_spheres_name_trgm
    ON corp.spheres USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source_file
    ON corp.knowledge_chunks (source_file);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_fts
    ON corp.knowledge_chunks USING gin (fts);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_heading_trgm
    ON corp.knowledge_chunks USING gin (heading gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_title_trgm
    ON corp.knowledge_chunks USING gin (document_title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON corp.knowledge_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_corp_search_docs_entity_type
    ON corp.corp_search_docs (entity_type);
CREATE INDEX IF NOT EXISTS idx_corp_search_docs_fts
    ON corp.corp_search_docs USING gin (fts);
CREATE INDEX IF NOT EXISTS idx_corp_search_docs_title_trgm
    ON corp.corp_search_docs USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_corp_search_docs_aliases_trgm
    ON corp.corp_search_docs USING gin (aliases gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_corp_search_docs_embedding
    ON corp.corp_search_docs USING hnsw (embedding vector_cosine_ops);

CREATE OR REPLACE FUNCTION corp.corp_hybrid_search(
    query_text text,
    query_embedding vector(1536) DEFAULT NULL,
    match_count integer DEFAULT 5,
    full_text_weight double precision DEFAULT 1.0,
    semantic_weight double precision DEFAULT 1.0,
    fuzzy_weight double precision DEFAULT 0.3,
    rrf_k integer DEFAULT 60,
    entity_types text[] DEFAULT NULL,
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
    WHERE entity_types IS NULL OR d.entity_type = ANY(entity_types)
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

REVOKE ALL ON ALL TABLES IN SCHEMA corp FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA corp FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA corp FROM PUBLIC;

GRANT USAGE ON SCHEMA corp TO corp_rw;
GRANT USAGE ON SCHEMA corp TO corp_ro;

GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA corp TO corp_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA corp TO corp_rw;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA corp TO corp_rw;

GRANT SELECT ON ALL TABLES IN SCHEMA corp TO corp_ro;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA corp TO corp_ro;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA corp TO corp_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA corp
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO corp_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA corp
    GRANT USAGE, SELECT ON SEQUENCES TO corp_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA corp
    GRANT EXECUTE ON FUNCTIONS TO corp_rw;

ALTER DEFAULT PRIVILEGES IN SCHEMA corp
    GRANT SELECT ON TABLES TO corp_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA corp
    GRANT USAGE, SELECT ON SEQUENCES TO corp_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA corp
    GRANT EXECUTE ON FUNCTIONS TO corp_ro;
