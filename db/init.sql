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

CREATE OR REPLACE VIEW corp.v_catalog_lamps_agent AS
WITH base AS (
    SELECT
        l.lamp_id,
        l.category_id,
        coalesce(nullif(l.category_name, ''), c.name) AS category_name,
        l.name,
        l.url,
        l.image_url,
        l.luminous_flux_lm,
        l.power_w,
        l.beam_pattern,
        l.mounting_type,
        l.explosion_protection_marking,
        l.is_explosion_protected,
        l.color_temperature_k,
        l.color_rendering_index_ra,
        l.power_factor_operator,
        l.power_factor_min,
        l.climate_execution,
        l.operating_temperature_range_raw,
        l.operating_temperature_min_c,
        l.operating_temperature_max_c,
        l.ingress_protection,
        l.electrical_protection_class,
        l.supply_voltage_raw,
        l.supply_voltage_kind,
        l.supply_voltage_nominal_v,
        l.supply_voltage_min_v,
        l.supply_voltage_max_v,
        l.supply_voltage_tolerance_minus_pct,
        l.supply_voltage_tolerance_plus_pct,
        l.dimensions_raw,
        l.length_mm,
        l.width_mm,
        l.height_mm,
        l.warranty_years,
        l.weight_kg,
        CASE
            WHEN l.power_w IS NOT NULL THEN l.power_w::text || ' Вт'
            ELSE NULL
        END AS power_text,
        CASE
            WHEN l.luminous_flux_lm IS NOT NULL THEN l.luminous_flux_lm::text || ' лм'
            ELSE NULL
        END AS flux_text,
        CASE
            WHEN l.color_temperature_k IS NOT NULL THEN l.color_temperature_k::text || ' K'
            ELSE NULL
        END AS cct_text,
        CASE
            WHEN l.weight_kg IS NOT NULL THEN corp.numeric_text(l.weight_kg) || ' кг'
            ELSE NULL
        END AS weight_text,
        CASE
            WHEN nullif(l.ingress_protection, '') IS NULL THEN NULL
            WHEN l.ingress_protection ~* '^ip' THEN regexp_replace(l.ingress_protection, '^ip\s*', 'IP', 'i')
            ELSE 'IP' || regexp_replace(l.ingress_protection, '^\s+', '')
        END AS ingress_text,
        CASE
            WHEN l.color_rendering_index_ra IS NOT NULL THEN 'Ra ' || l.color_rendering_index_ra::text
            ELSE NULL
        END AS cri_text,
        CASE
            WHEN l.power_factor_min IS NOT NULL THEN concat_ws(' ', coalesce(l.power_factor_operator, ''), corp.numeric_text(l.power_factor_min))
            ELSE NULL
        END AS power_factor_text,
        CASE
            WHEN nullif(l.operating_temperature_range_raw, '') IS NOT NULL THEN l.operating_temperature_range_raw
            WHEN l.operating_temperature_min_c IS NOT NULL OR l.operating_temperature_max_c IS NOT NULL THEN concat_ws(
                ' ... ',
                CASE
                    WHEN l.operating_temperature_min_c IS NOT NULL THEN l.operating_temperature_min_c::text || '°C'
                    ELSE NULL
                END,
                CASE
                    WHEN l.operating_temperature_max_c IS NOT NULL THEN l.operating_temperature_max_c::text || '°C'
                    ELSE NULL
                END
            )
            ELSE NULL
        END AS temperature_text,
        CASE
            WHEN nullif(l.supply_voltage_raw, '') IS NOT NULL THEN l.supply_voltage_raw
            WHEN l.supply_voltage_nominal_v IS NOT NULL
                OR l.supply_voltage_min_v IS NOT NULL
                OR l.supply_voltage_max_v IS NOT NULL
                OR nullif(l.supply_voltage_kind, '') IS NOT NULL THEN concat_ws(
                    ' ',
                    nullif(l.supply_voltage_kind, ''),
                    CASE
                        WHEN l.supply_voltage_nominal_v IS NOT NULL THEN l.supply_voltage_nominal_v::text || ' В'
                        ELSE NULL
                    END,
                    CASE
                        WHEN l.supply_voltage_min_v IS NOT NULL OR l.supply_voltage_max_v IS NOT NULL THEN '(' || concat_ws(
                            ' ... ',
                            CASE
                                WHEN l.supply_voltage_min_v IS NOT NULL THEN l.supply_voltage_min_v::text || ' В'
                                ELSE NULL
                            END,
                            CASE
                                WHEN l.supply_voltage_max_v IS NOT NULL THEN l.supply_voltage_max_v::text || ' В'
                                ELSE NULL
                            END
                        ) || ')'
                        ELSE NULL
                    END
                )
            ELSE NULL
        END AS voltage_text,
        CASE
            WHEN nullif(l.dimensions_raw, '') IS NOT NULL THEN CASE
                WHEN l.dimensions_raw ~* '(мм|mm)' THEN l.dimensions_raw
                ELSE l.dimensions_raw || ' мм'
            END
            WHEN l.length_mm IS NOT NULL OR l.width_mm IS NOT NULL OR l.height_mm IS NOT NULL THEN concat_ws(
                ' x ',
                CASE WHEN l.length_mm IS NOT NULL THEN corp.numeric_text(l.length_mm) END,
                CASE WHEN l.width_mm IS NOT NULL THEN corp.numeric_text(l.width_mm) END,
                CASE WHEN l.height_mm IS NOT NULL THEN corp.numeric_text(l.height_mm) END
            ) || ' мм'
            ELSE NULL
        END AS dimensions_text,
        CASE
            WHEN l.warranty_years IS NOT NULL THEN l.warranty_years::text || ' лет'
            ELSE NULL
        END AS warranty_text,
        regexp_replace(
            lower(coalesce(l.name, '')),
            '[^0-9a-zа-я/+.-]+',
            ' ',
            'g'
        ) AS name_tokens,
        regexp_replace(
            lower(coalesce(coalesce(nullif(l.category_name, ''), c.name), '')),
            '[^0-9a-zа-я/+.-]+',
            ' ',
            'g'
        ) AS category_tokens
    FROM corp.catalog_lamps l
    LEFT JOIN corp.categories c ON c.category_id = l.category_id
)
SELECT
    b.lamp_id,
    b.category_id,
    b.category_name,
    b.name,
    b.url,
    b.image_url,
    b.luminous_flux_lm,
    b.power_w,
    b.beam_pattern,
    b.mounting_type,
    b.explosion_protection_marking,
    b.is_explosion_protected,
    b.color_temperature_k,
    b.color_rendering_index_ra,
    b.power_factor_operator,
    b.power_factor_min,
    b.climate_execution,
    b.operating_temperature_range_raw,
    b.operating_temperature_min_c,
    b.operating_temperature_max_c,
    b.ingress_protection,
    b.electrical_protection_class,
    b.supply_voltage_raw,
    b.supply_voltage_kind,
    b.supply_voltage_nominal_v,
    b.supply_voltage_min_v,
    b.supply_voltage_max_v,
    b.supply_voltage_tolerance_minus_pct,
    b.supply_voltage_tolerance_plus_pct,
    b.dimensions_raw,
    b.length_mm,
    b.width_mm,
    b.height_mm,
    b.warranty_years,
    b.weight_kg,
    concat_ws(
        ' | ',
        b.category_name,
        b.power_text,
        b.flux_text,
        b.cct_text,
        b.cri_text,
        b.beam_pattern,
        b.ingress_text,
        b.mounting_type,
        b.climate_execution,
        b.electrical_protection_class,
        b.weight_text,
        b.dimensions_text,
        b.warranty_text,
        CASE
            WHEN b.is_explosion_protected THEN 'Ex'
            ELSE NULL
        END
    ) AS preview,
    concat_ws(
        '. ',
        'Светильник ' || b.name,
        CASE
            WHEN b.category_name IS NOT NULL THEN 'Категория ' || b.category_name
            ELSE NULL
        END,
        CASE
            WHEN b.power_text IS NOT NULL THEN 'Мощность ' || b.power_text
            ELSE NULL
        END,
        CASE
            WHEN b.flux_text IS NOT NULL THEN 'Световой поток ' || b.flux_text
            ELSE NULL
        END,
        CASE
            WHEN b.cct_text IS NOT NULL THEN 'Цветовая температура ' || b.cct_text
            ELSE NULL
        END,
        CASE
            WHEN b.cri_text IS NOT NULL THEN 'Индекс цветопередачи ' || b.cri_text
            ELSE NULL
        END,
        CASE
            WHEN b.beam_pattern IS NOT NULL THEN 'Светораспределение ' || b.beam_pattern
            ELSE NULL
        END,
        CASE
            WHEN b.ingress_text IS NOT NULL THEN b.ingress_text
            ELSE NULL
        END,
        CASE
            WHEN b.mounting_type IS NOT NULL THEN 'Монтаж ' || b.mounting_type
            ELSE NULL
        END,
        CASE
            WHEN b.climate_execution IS NOT NULL THEN 'Климатическое исполнение ' || b.climate_execution
            ELSE NULL
        END,
        CASE
            WHEN b.electrical_protection_class IS NOT NULL THEN 'Класс электрозащиты ' || b.electrical_protection_class
            ELSE NULL
        END,
        CASE
            WHEN b.temperature_text IS NOT NULL THEN 'Рабочая температура ' || b.temperature_text
            ELSE NULL
        END,
        CASE
            WHEN b.voltage_text IS NOT NULL THEN 'Питание ' || b.voltage_text
            ELSE NULL
        END,
        CASE
            WHEN b.power_factor_text IS NOT NULL THEN 'Коэффициент мощности ' || b.power_factor_text
            ELSE NULL
        END,
        CASE
            WHEN b.weight_text IS NOT NULL THEN 'Вес ' || b.weight_text
            ELSE NULL
        END,
        CASE
            WHEN b.dimensions_text IS NOT NULL THEN 'Габариты ' || b.dimensions_text
            ELSE NULL
        END,
        CASE
            WHEN b.warranty_text IS NOT NULL THEN 'Гарантия ' || b.warranty_text
            ELSE NULL
        END,
        CASE
            WHEN b.is_explosion_protected AND b.explosion_protection_marking IS NOT NULL THEN 'Маркировка взрывозащиты ' || b.explosion_protection_marking
            WHEN b.is_explosion_protected THEN 'Исполнение взрывозащищенное'
            ELSE NULL
        END
    ) AS agent_summary,
    jsonb_strip_nulls(
        jsonb_build_object(
            'power_w', CASE
                WHEN b.power_w IS NOT NULL THEN corp.agent_fact('Мощность', b.power_text, to_jsonb(b.power_w), 'Вт')
                ELSE NULL
            END,
            'luminous_flux_lm', CASE
                WHEN b.luminous_flux_lm IS NOT NULL THEN corp.agent_fact('Световой поток', b.flux_text, to_jsonb(b.luminous_flux_lm), 'лм')
                ELSE NULL
            END,
            'color_temperature_k', CASE
                WHEN b.color_temperature_k IS NOT NULL THEN corp.agent_fact('Цветовая температура', b.cct_text, to_jsonb(b.color_temperature_k), 'K')
                ELSE NULL
            END,
            'beam_pattern', CASE
                WHEN b.beam_pattern IS NOT NULL THEN corp.agent_fact('Светораспределение', b.beam_pattern, to_jsonb(b.beam_pattern))
                ELSE NULL
            END,
            'mounting_type', CASE
                WHEN b.mounting_type IS NOT NULL THEN corp.agent_fact('Монтаж', b.mounting_type, to_jsonb(b.mounting_type))
                ELSE NULL
            END,
            'ingress_protection', CASE
                WHEN b.ingress_text IS NOT NULL THEN corp.agent_fact('Степень защиты', b.ingress_text, to_jsonb(b.ingress_protection))
                ELSE NULL
            END,
            'weight_kg', CASE
                WHEN b.weight_kg IS NOT NULL THEN corp.agent_fact('Вес', b.weight_text, to_jsonb(b.weight_kg), 'кг')
                ELSE NULL
            END,
            'color_rendering_index_ra', CASE
                WHEN b.color_rendering_index_ra IS NOT NULL THEN corp.agent_fact('Индекс цветопередачи', b.cri_text, to_jsonb(b.color_rendering_index_ra))
                ELSE NULL
            END,
            'power_factor_operator', CASE
                WHEN b.power_factor_operator IS NOT NULL THEN corp.agent_fact('Оператор коэффициента мощности', b.power_factor_operator, to_jsonb(b.power_factor_operator))
                ELSE NULL
            END,
            'power_factor_min', CASE
                WHEN b.power_factor_min IS NOT NULL THEN corp.agent_fact('Коэффициент мощности', b.power_factor_text, to_jsonb(b.power_factor_min))
                ELSE NULL
            END,
            'climate_execution', CASE
                WHEN b.climate_execution IS NOT NULL THEN corp.agent_fact('Климатическое исполнение', b.climate_execution, to_jsonb(b.climate_execution))
                ELSE NULL
            END,
            'operating_temperature_range_raw', CASE
                WHEN b.temperature_text IS NOT NULL THEN corp.agent_fact('Диапазон рабочих температур', b.temperature_text, to_jsonb(coalesce(b.operating_temperature_range_raw, b.temperature_text)))
                ELSE NULL
            END,
            'operating_temperature_min_c', CASE
                WHEN b.operating_temperature_min_c IS NOT NULL THEN corp.agent_fact('Минимальная рабочая температура', b.operating_temperature_min_c::text || '°C', to_jsonb(b.operating_temperature_min_c), '°C')
                ELSE NULL
            END,
            'operating_temperature_max_c', CASE
                WHEN b.operating_temperature_max_c IS NOT NULL THEN corp.agent_fact('Максимальная рабочая температура', b.operating_temperature_max_c::text || '°C', to_jsonb(b.operating_temperature_max_c), '°C')
                ELSE NULL
            END,
            'electrical_protection_class', CASE
                WHEN b.electrical_protection_class IS NOT NULL THEN corp.agent_fact('Класс электрозащиты', b.electrical_protection_class, to_jsonb(b.electrical_protection_class))
                ELSE NULL
            END,
            'supply_voltage_raw', CASE
                WHEN b.voltage_text IS NOT NULL THEN corp.agent_fact('Питание', b.voltage_text, to_jsonb(coalesce(b.supply_voltage_raw, b.voltage_text)))
                ELSE NULL
            END,
            'supply_voltage_kind', CASE
                WHEN b.supply_voltage_kind IS NOT NULL THEN corp.agent_fact('Род тока', b.supply_voltage_kind, to_jsonb(b.supply_voltage_kind))
                ELSE NULL
            END,
            'supply_voltage_nominal_v', CASE
                WHEN b.supply_voltage_nominal_v IS NOT NULL THEN corp.agent_fact('Номинальное напряжение', b.supply_voltage_nominal_v::text || ' В', to_jsonb(b.supply_voltage_nominal_v), 'В')
                ELSE NULL
            END,
            'supply_voltage_min_v', CASE
                WHEN b.supply_voltage_min_v IS NOT NULL THEN corp.agent_fact('Минимальное напряжение', b.supply_voltage_min_v::text || ' В', to_jsonb(b.supply_voltage_min_v), 'В')
                ELSE NULL
            END,
            'supply_voltage_max_v', CASE
                WHEN b.supply_voltage_max_v IS NOT NULL THEN corp.agent_fact('Максимальное напряжение', b.supply_voltage_max_v::text || ' В', to_jsonb(b.supply_voltage_max_v), 'В')
                ELSE NULL
            END,
            'supply_voltage_tolerance_minus_pct', CASE
                WHEN b.supply_voltage_tolerance_minus_pct IS NOT NULL THEN corp.agent_fact('Отрицательный допуск напряжения', corp.numeric_text(b.supply_voltage_tolerance_minus_pct) || '%', to_jsonb(b.supply_voltage_tolerance_minus_pct), '%')
                ELSE NULL
            END,
            'supply_voltage_tolerance_plus_pct', CASE
                WHEN b.supply_voltage_tolerance_plus_pct IS NOT NULL THEN corp.agent_fact('Положительный допуск напряжения', corp.numeric_text(b.supply_voltage_tolerance_plus_pct) || '%', to_jsonb(b.supply_voltage_tolerance_plus_pct), '%')
                ELSE NULL
            END,
            'dimensions_raw', CASE
                WHEN b.dimensions_text IS NOT NULL THEN corp.agent_fact('Габариты', b.dimensions_text, to_jsonb(coalesce(b.dimensions_raw, b.dimensions_text)))
                ELSE NULL
            END,
            'length_mm', CASE
                WHEN b.length_mm IS NOT NULL THEN corp.agent_fact('Длина', corp.numeric_text(b.length_mm) || ' мм', to_jsonb(b.length_mm), 'мм')
                ELSE NULL
            END,
            'width_mm', CASE
                WHEN b.width_mm IS NOT NULL THEN corp.agent_fact('Ширина', corp.numeric_text(b.width_mm) || ' мм', to_jsonb(b.width_mm), 'мм')
                ELSE NULL
            END,
            'height_mm', CASE
                WHEN b.height_mm IS NOT NULL THEN corp.agent_fact('Высота', corp.numeric_text(b.height_mm) || ' мм', to_jsonb(b.height_mm), 'мм')
                ELSE NULL
            END,
            'warranty_years', CASE
                WHEN b.warranty_years IS NOT NULL THEN corp.agent_fact('Гарантия', b.warranty_text, to_jsonb(b.warranty_years), 'лет')
                ELSE NULL
            END,
            'is_explosion_protected', corp.agent_fact(
                'Взрывозащита',
                CASE
                    WHEN b.is_explosion_protected THEN 'Да'
                    ELSE 'Нет'
                END,
                to_jsonb(b.is_explosion_protected)
            ),
            'explosion_protection_marking', CASE
                WHEN b.explosion_protection_marking IS NOT NULL THEN corp.agent_fact('Маркировка взрывозащиты', b.explosion_protection_marking, to_jsonb(b.explosion_protection_marking))
                ELSE NULL
            END
        )
    ) AS agent_facts,
    concat_ws(
        '. ',
        b.category_name,
        'Светильник ' || b.name,
        CASE
            WHEN b.power_text IS NOT NULL THEN 'Мощность ' || b.power_text
            ELSE NULL
        END,
        CASE
            WHEN b.flux_text IS NOT NULL THEN 'Световой поток ' || b.flux_text
            ELSE NULL
        END,
        CASE
            WHEN b.cct_text IS NOT NULL THEN 'Цветовая температура ' || b.cct_text
            ELSE NULL
        END,
        CASE
            WHEN b.cri_text IS NOT NULL THEN 'CRI ' || b.cri_text
            ELSE NULL
        END,
        CASE
            WHEN b.beam_pattern IS NOT NULL THEN 'Угол ' || b.beam_pattern
            ELSE NULL
        END,
        CASE
            WHEN b.ingress_text IS NOT NULL THEN b.ingress_text
            ELSE NULL
        END,
        CASE
            WHEN b.mounting_type IS NOT NULL THEN 'Монтаж ' || b.mounting_type
            ELSE NULL
        END,
        CASE
            WHEN b.climate_execution IS NOT NULL THEN 'Климат ' || b.climate_execution
            ELSE NULL
        END,
        CASE
            WHEN b.electrical_protection_class IS NOT NULL THEN 'Класс ' || b.electrical_protection_class
            ELSE NULL
        END,
        CASE
            WHEN b.temperature_text IS NOT NULL THEN 'Температура ' || b.temperature_text
            ELSE NULL
        END,
        CASE
            WHEN b.voltage_text IS NOT NULL THEN 'Питание ' || b.voltage_text
            ELSE NULL
        END,
        CASE
            WHEN b.power_factor_text IS NOT NULL THEN 'PF ' || b.power_factor_text
            ELSE NULL
        END,
        CASE
            WHEN b.weight_text IS NOT NULL THEN 'Вес ' || b.weight_text
            ELSE NULL
        END,
        CASE
            WHEN b.dimensions_text IS NOT NULL THEN 'Габариты ' || b.dimensions_text
            ELSE NULL
        END,
        CASE
            WHEN b.warranty_text IS NOT NULL THEN 'Гарантия ' || b.warranty_text
            ELSE NULL
        END,
        CASE
            WHEN b.is_explosion_protected THEN 'Взрывозащита'
            ELSE NULL
        END,
        b.explosion_protection_marking
    ) AS search_text,
    concat_ws(
        ' ',
        b.name_tokens,
        b.category_tokens,
        lower(coalesce(b.beam_pattern, '')),
        lower(coalesce(b.mounting_type, '')),
        lower(coalesce(b.ingress_text, '')),
        lower(coalesce(b.climate_execution, '')),
        lower(coalesce(b.electrical_protection_class, '')),
        lower(coalesce(b.explosion_protection_marking, '')),
        lower(coalesce(b.supply_voltage_raw, '')),
        lower(coalesce(b.supply_voltage_kind, '')),
        lower(coalesce(b.dimensions_text, '')),
        lower(coalesce(b.temperature_text, '')),
        lower(coalesce(b.power_text, '')),
        lower(coalesce(b.flux_text, '')),
        lower(coalesce(b.cct_text, '')),
        lower(coalesce(b.weight_text, '')),
        lower(coalesce(b.cri_text, '')),
        lower(coalesce(b.power_factor_text, '')),
        lower(coalesce(b.warranty_text, '')),
        CASE
            WHEN b.weight_kg IS NOT NULL THEN corp.numeric_text(b.weight_kg) || 'kg ' || corp.numeric_text(b.weight_kg) || ' кг вес масса'
            ELSE NULL
        END,
        CASE
            WHEN b.color_rendering_index_ra IS NOT NULL THEN 'cri ra ' || b.color_rendering_index_ra::text
            ELSE NULL
        END,
        CASE
            WHEN b.beam_pattern IS NOT NULL THEN 'угол светораспределение оптика ' || lower(b.beam_pattern)
            ELSE NULL
        END,
        CASE
            WHEN b.dimensions_text IS NOT NULL THEN 'габариты размер длина ширина высота ' || lower(b.dimensions_text)
            ELSE NULL
        END,
        CASE
            WHEN b.is_explosion_protected THEN 'взрывозащищенный ex'
            ELSE NULL
        END
    ) AS search_aliases
FROM base b;

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
