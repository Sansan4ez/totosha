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

CREATE OR REPLACE FUNCTION corp.numeric_text(value numeric)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
SELECT CASE
    WHEN $1 IS NULL THEN NULL
    ELSE nullif(trim(trailing '.' FROM trim(trailing '0' FROM $1::text)), '')
END;
$$;

CREATE OR REPLACE FUNCTION corp.agent_fact(
    label text,
    text_value text,
    raw_value jsonb DEFAULT NULL,
    unit text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
SELECT jsonb_strip_nulls(
    jsonb_build_object(
        'label', $1,
        'text', $2,
        'value', $3,
        'unit', $4
    )
);
$$;

CREATE TABLE IF NOT EXISTS corp.categories (
    category_id bigint PRIMARY KEY,
    name text NOT NULL,
    url text,
    image_url text,
    parent_category_id bigint,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE IF EXISTS corp.categories
    ADD COLUMN IF NOT EXISTS parent_category_id bigint;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'categories_parent_category_id_fkey'
          AND conrelid = 'corp.categories'::regclass
    ) THEN
        ALTER TABLE corp.categories
            ADD CONSTRAINT categories_parent_category_id_fkey
            FOREIGN KEY (parent_category_id)
            REFERENCES corp.categories(category_id)
            ON DELETE SET NULL;
    END IF;
END;
$$;

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

CREATE TABLE IF NOT EXISTS corp.sphere_curated_categories (
    sphere_id bigint NOT NULL REFERENCES corp.spheres(sphere_id) ON DELETE CASCADE,
    category_id bigint NOT NULL REFERENCES corp.categories(category_id) ON DELETE CASCADE,
    position integer NOT NULL,
    source_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sphere_id, category_id),
    UNIQUE (sphere_id, position),
    CHECK (position > 0)
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

\ir /docker-entrypoint-initdb.d/25-catalog-lamps-agent.sql


CREATE INDEX IF NOT EXISTS idx_categories_name_trgm
    ON corp.categories USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_categories_parent_category_id
    ON corp.categories (parent_category_id);
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
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_beam_pattern
    ON corp.catalog_lamps USING gin (beam_pattern gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_climate_execution
    ON corp.catalog_lamps USING gin (climate_execution gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_electrical_protection_class
    ON corp.catalog_lamps USING gin (electrical_protection_class gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_explosion_marking
    ON corp.catalog_lamps USING gin (explosion_protection_marking gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_dimensions_raw
    ON corp.catalog_lamps USING gin (dimensions_raw gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_weight_kg
    ON corp.catalog_lamps (weight_kg);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_cri_ra
    ON corp.catalog_lamps (color_rendering_index_ra);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_power_factor_min
    ON corp.catalog_lamps (power_factor_min);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_voltage_nominal
    ON corp.catalog_lamps (supply_voltage_nominal_v);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_voltage_min
    ON corp.catalog_lamps (supply_voltage_min_v);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_voltage_max
    ON corp.catalog_lamps (supply_voltage_max_v);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_voltage_tol_minus
    ON corp.catalog_lamps (supply_voltage_tolerance_minus_pct);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_voltage_tol_plus
    ON corp.catalog_lamps (supply_voltage_tolerance_plus_pct);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_length_mm
    ON corp.catalog_lamps (length_mm);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_width_mm
    ON corp.catalog_lamps (width_mm);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_height_mm
    ON corp.catalog_lamps (height_mm);
CREATE INDEX IF NOT EXISTS idx_catalog_lamps_warranty_years
    ON corp.catalog_lamps (warranty_years);

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
CREATE INDEX IF NOT EXISTS idx_sphere_curated_categories_category_id
    ON corp.sphere_curated_categories (category_id);
CREATE INDEX IF NOT EXISTS idx_sphere_curated_categories_sphere_position
    ON corp.sphere_curated_categories (sphere_id, position);

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

ALTER TABLE IF EXISTS corp.corp_search_docs OWNER TO corp_rw;
ALTER SEQUENCE IF EXISTS corp.corp_search_docs_doc_id_seq OWNER TO corp_rw;

-- corp.corp_hybrid_search is defined in db/sql/corp_hybrid_search.sql (single source
-- of truth). It is applied on fresh initdb as 30-corp-hybrid-search.sql and re-applied
-- to live databases by corp-db-migrator (ensure-rfc026).

REVOKE ALL ON ALL TABLES IN SCHEMA corp FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA corp FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA corp FROM PUBLIC;

GRANT USAGE ON SCHEMA corp TO corp_rw;
GRANT CREATE ON SCHEMA corp TO corp_rw;
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
