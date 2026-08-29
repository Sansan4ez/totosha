DO $seed$
DECLARE
    series_payload jsonb;
    duplicate_family text;
BEGIN
    series_payload := pg_read_file('/docker-entrypoint-initdb.d/series_catalog.json')::jsonb;

    IF jsonb_typeof(series_payload->'series') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'series_catalog.json must contain a series list';
    END IF;

    SELECT family_name
    INTO duplicate_family
    FROM (
        SELECT
            lower(trim(family.value)) AS family_key,
            min(trim(family.value)) AS family_name,
            count(DISTINCT trim(series_entry.value->>'name')) AS owner_count
        FROM jsonb_array_elements(series_payload->'series') WITH ORDINALITY AS series_entry(value, series_position)
        CROSS JOIN LATERAL jsonb_array_elements_text(
            jsonb_build_array(series_entry.value->>'name')
            || CASE
                WHEN jsonb_typeof(series_entry.value->'category_families') = 'array'
                    THEN series_entry.value->'category_families'
                ELSE '[]'::jsonb
            END
        ) AS family(value)
        GROUP BY lower(trim(family.value))
        HAVING count(DISTINCT trim(series_entry.value->>'name')) > 1
    ) duplicates
    LIMIT 1;

    IF duplicate_family IS NOT NULL THEN
        RAISE EXCEPTION 'category family % is shared by multiple canonical series', duplicate_family;
    END IF;

    TRUNCATE TABLE corp.catalog_series_families;
    INSERT INTO corp.catalog_series_families (
        canonical_series_name,
        category_family_name,
        position,
        source_hash
    )
    SELECT
        family.canonical_series_name,
        family.category_family_name,
        row_number() OVER (
            ORDER BY family.series_position, family.family_position
        )::integer,
        md5(series_payload::text)
    FROM (
        SELECT DISTINCT ON (lower(trim(family.value)))
            trim(series_entry.value->>'name') AS canonical_series_name,
            trim(family.value) AS category_family_name,
            series_entry.series_position,
            family.family_position
        FROM jsonb_array_elements(series_payload->'series') WITH ORDINALITY AS series_entry(value, series_position)
        CROSS JOIN LATERAL jsonb_array_elements_text(
            jsonb_build_array(series_entry.value->>'name')
            || CASE
                WHEN jsonb_typeof(series_entry.value->'category_families') = 'array'
                    THEN series_entry.value->'category_families'
                ELSE '[]'::jsonb
            END
        ) WITH ORDINALITY AS family(value, family_position)
        WHERE nullif(trim(series_entry.value->>'name'), '') IS NOT NULL
          AND nullif(trim(family.value), '') IS NOT NULL
        ORDER BY
            lower(trim(family.value)),
            series_entry.series_position,
            family.family_position
    ) family;
END;
$seed$;
