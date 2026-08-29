CREATE OR REPLACE VIEW corp.v_catalog_lamps_agent AS
WITH RECURSIVE category_ancestry AS (
    SELECT
        c.category_id AS descendant_category_id,
        c.category_id AS ancestor_category_id,
        c.parent_category_id,
        c.name AS ancestor_name,
        0 AS depth,
        ARRAY[c.category_id]::bigint[] AS path
    FROM corp.categories c

    UNION ALL

    SELECT
        ca.descendant_category_id,
        parent.category_id AS ancestor_category_id,
        parent.parent_category_id,
        parent.name AS ancestor_name,
        ca.depth + 1,
        ca.path || parent.category_id
    FROM category_ancestry ca
    JOIN corp.categories parent ON parent.category_id = ca.parent_category_id
    WHERE NOT parent.category_id = ANY(ca.path)
),
category_series AS (
    SELECT DISTINCT ON (ca.descendant_category_id)
        ca.descendant_category_id AS category_id,
        family.canonical_series_name AS series_name
    FROM category_ancestry ca
    JOIN corp.catalog_series_families family
        ON family.category_family_name = ca.ancestor_name
    ORDER BY ca.descendant_category_id, ca.depth ASC
),
base AS (
    SELECT
        l.lamp_id,
        l.category_id,
        coalesce(nullif(l.category_name, ''), c.name) AS category_name,
        category_series.series_name,
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
    LEFT JOIN category_series ON category_series.category_id = l.category_id
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
        b.series_name,
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
            WHEN b.series_name IS NOT NULL THEN 'Серия ' || b.series_name
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
        b.series_name,
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
        lower(coalesce(b.series_name, '')),
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
    ) AS search_aliases,
    b.series_name
FROM base b;
