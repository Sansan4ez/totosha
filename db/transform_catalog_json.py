#!/usr/bin/env python3
"""
Transform catalog.json into the minimal table-shaped outputs needed for DB load.

The script emits only the catalog-derived tables that are part of the target
PostgreSQL model:
1. `catalog_lamps`
2. `catalog_lamp_documents`
3. `catalog_lamp_properties_raw`

Usage:
    python3 transform_catalog_json.py
    python3 transform_catalog_json.py --input catalog.json --output-dir out
    python3 transform_catalog_json.py --format csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
    }
)

TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

NUMERIC_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class PropertySpec:
    source_name: str
    code: str
    label_ru: str
    target_column: str | None
    data_type: str
    unit: str | None = None
    notes: str | None = None


PROPERTY_SPECS: list[PropertySpec] = [
    PropertySpec(
        source_name="Световой поток светильника",
        code="luminous_flux_lm",
        label_ru="Световой поток светильника, Лм",
        target_column="luminous_flux_lm",
        data_type="integer",
        unit="Лм",
    ),
    PropertySpec(
        source_name="Энергопотребление",
        code="power_w",
        label_ru="Энергопотребление, Вт",
        target_column="power_w",
        data_type="integer",
        unit="Вт",
    ),
    PropertySpec(
        source_name="Угол излучения / Рассеиватель",
        code="beam_pattern",
        label_ru="Угол излучения / Рассеиватель",
        target_column="beam_pattern",
        data_type="text",
    ),
    PropertySpec(
        source_name="Тип крепления",
        code="mounting_type",
        label_ru="Тип крепления",
        target_column="mounting_type",
        data_type="text",
    ),
    PropertySpec(
        source_name="Маркировка взрывозащиты",
        code="explosion_protection_marking",
        label_ru="Маркировка взрывозащиты",
        target_column="explosion_protection_marking",
        data_type="text",
    ),
    PropertySpec(
        source_name="Цветовая температура",
        code="color_temperature_k",
        label_ru="Цветовая температура, K",
        target_column="color_temperature_k",
        data_type="integer",
        unit="К",
    ),
    PropertySpec(
        source_name="Индекс цветопередачи",
        code="color_rendering_index_ra",
        label_ru="Индекс цветопередачи, Ra",
        target_column="color_rendering_index_ra",
        data_type="integer",
    ),
    PropertySpec(
        source_name="Коэффициент мощности",
        code="power_factor_min",
        label_ru="Коэффициент мощности, min",
        target_column="power_factor_min",
        data_type="numeric",
    ),
    PropertySpec(
        source_name="Вид климатического исполнения",
        code="climate_execution",
        label_ru="Вид климатического исполнения",
        target_column="climate_execution",
        data_type="text",
    ),
    PropertySpec(
        source_name="Диапазон рабочих температур",
        code="operating_temperature_range",
        label_ru="Диапазон рабочих температур, C",
        target_column=None,
        data_type="range",
        unit="C",
        notes="Stored in operating_temperature_range_raw, operating_temperature_min_c, operating_temperature_max_c.",
    ),
    PropertySpec(
        source_name="Влаго и пылезащита",
        code="ingress_protection",
        label_ru="Влаго и пылезащита",
        target_column="ingress_protection",
        data_type="text",
    ),
    PropertySpec(
        source_name="Класс зашиты от поражения электрическим током",
        code="electrical_protection_class",
        label_ru="Класс защиты от поражения электрическим током",
        target_column="electrical_protection_class",
        data_type="text",
    ),
    PropertySpec(
        source_name="Напряжение питающей сети",
        code="supply_voltage",
        label_ru="Напряжение питающей сети, В",
        target_column=None,
        data_type="composite",
        unit="В",
        notes="Stored in supply_voltage_raw, supply_voltage_kind, supply_voltage_nominal_v, supply_voltage_min_v, supply_voltage_max_v, tolerance columns.",
    ),
    PropertySpec(
        source_name="Габаритные размеры светильника",
        code="dimensions_mm",
        label_ru="Габаритные размеры светильника, мм",
        target_column=None,
        data_type="composite",
        unit="мм",
        notes="Stored in dimensions_raw, length_mm, width_mm, height_mm.",
    ),
    PropertySpec(
        source_name="Гарантийный срок",
        code="warranty_years",
        label_ru="Гарантийный срок, лет",
        target_column="warranty_years",
        data_type="integer",
    ),
    PropertySpec(
        source_name="Вес светильника",
        code="weight_kg",
        label_ru="Вес светильника, кг",
        target_column="weight_kg",
        data_type="numeric",
        unit="кг",
    ),
]

PROPERTY_SPEC_BY_NAME = {spec.source_name: spec for spec in PROPERTY_SPECS}

DOCUMENT_SPECS: list[dict[str, str]] = [
    {"source_key": "instruction", "column": "instruction_url", "label_ru": "Инструкция"},
    {"source_key": "blueprint", "column": "blueprint_url", "label_ru": "Чертеж"},
    {"source_key": "passport", "column": "passport_url", "label_ru": "Паспорт"},
    {"source_key": "sertificate", "column": "certificate_url", "label_ru": "Сертификат"},
    {"source_key": "IES", "column": "ies_url", "label_ru": "IES"},
    {"source_key": "diffuser", "column": "diffuser_url", "label_ru": "Рассеиватель"},
    {"source_key": "complectOfDocs", "column": "complete_docs_url", "label_ru": "Комплект документов"},
]

LAMP_COLUMNS = [
    "lamp_id",
    "category_id",
    "name",
    "url",
    "image_url",
    "luminous_flux_lm",
    "power_w",
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
]


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u00a0", " ").strip()
    if not text:
        return None
    return re.sub(r"\s+", " ", text)


def clean_number_text(text: str) -> str:
    return (
        text.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace(",", ".")
        .translate(CYRILLIC_TO_LATIN)
    )


def coerce_number(value: float | None) -> int | float | None:
    if value is None:
        return None
    rounded = round(value, 6)
    if rounded.is_integer():
        return int(rounded)
    return rounded


def extract_numbers(text: str | None) -> list[float]:
    if not text:
        return []
    return [float(match) for match in NUMERIC_RE.findall(clean_number_text(text))]


def transliterate(text: str) -> str:
    chars: list[str] = []
    for char in text.lower():
        chars.append(TRANSLIT_MAP.get(char, char))
    return "".join(chars)


def slugify_identifier(text: str) -> str:
    slug = transliterate(text)
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug or "unknown_property"


def parse_simple_number(text: str | None) -> int | float | None:
    numbers = extract_numbers(text)
    if not numbers:
        return None
    return coerce_number(numbers[0])


def parse_temperature_range(text: str | None) -> tuple[int | float | None, int | float | None]:
    numbers = extract_numbers(text)
    if len(numbers) < 2:
        return None, None
    return coerce_number(numbers[0]), coerce_number(numbers[1])


def parse_dimensions(text: str | None) -> tuple[int | float | None, int | float | None, int | float | None]:
    numbers = extract_numbers(text)
    if len(numbers) < 3:
        return None, None, None
    return (
        coerce_number(numbers[0]),
        coerce_number(numbers[1]),
        coerce_number(numbers[2]),
    )


def parse_power_factor(text: str | None) -> tuple[str | None, int | float | None]:
    if not text:
        return None, None
    normalized = clean_number_text(text)
    operator = None
    if any(token in normalized for token in ("≧", "≥", ">=")):
        operator = ">="
    elif ">" in normalized:
        operator = ">"
    elif any(token in normalized for token in ("≦", "≤", "<=")):
        operator = "<="
    elif "<" in normalized:
        operator = "<"
    elif "=" in normalized:
        operator = "="
    return operator, parse_simple_number(normalized)


def parse_voltage(text: str | None) -> dict[str, Any]:
    normalized = normalize_text(text)
    result = {
        "supply_voltage_raw": normalized,
        "supply_voltage_kind": None,
        "supply_voltage_nominal_v": None,
        "supply_voltage_min_v": None,
        "supply_voltage_max_v": None,
        "supply_voltage_tolerance_minus_pct": None,
        "supply_voltage_tolerance_plus_pct": None,
    }
    if not normalized:
        return result

    upper = clean_number_text(normalized).upper()
    if "AC/DC" in upper:
        result["supply_voltage_kind"] = "AC/DC"
    elif "DC" in upper and "AC" not in upper:
        result["supply_voltage_kind"] = "DC"
    elif "AC" in upper:
        result["supply_voltage_kind"] = "AC"

    plus_minus_match = re.search(r"(\d+(?:\.\d+)?)\s*±\s*(\d+(?:\.\d+)?)%", upper)
    if plus_minus_match:
        nominal = float(plus_minus_match.group(1))
        tolerance = float(plus_minus_match.group(2))
        result["supply_voltage_nominal_v"] = coerce_number(nominal)
        result["supply_voltage_tolerance_minus_pct"] = coerce_number(tolerance)
        result["supply_voltage_tolerance_plus_pct"] = coerce_number(tolerance)
        result["supply_voltage_min_v"] = coerce_number(nominal * (1 - tolerance / 100))
        result["supply_voltage_max_v"] = coerce_number(nominal * (1 + tolerance / 100))
        return result

    if "%" in upper:
        plus_match = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)%", upper)
        minus_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)%", upper)
        if plus_match and minus_match and plus_match.group(1) == minus_match.group(1):
            nominal = float(plus_match.group(1))
            plus_pct = float(plus_match.group(2))
            minus_pct = float(minus_match.group(2))
            result["supply_voltage_nominal_v"] = coerce_number(nominal)
            result["supply_voltage_tolerance_minus_pct"] = coerce_number(minus_pct)
            result["supply_voltage_tolerance_plus_pct"] = coerce_number(plus_pct)
            result["supply_voltage_min_v"] = coerce_number(nominal * (1 - minus_pct / 100))
            result["supply_voltage_max_v"] = coerce_number(nominal * (1 + plus_pct / 100))
            return result

    numbers = extract_numbers(upper)
    if len(numbers) >= 2 and ("..." in upper or re.search(r"\d\s*-\s*\d", upper)):
        result["supply_voltage_min_v"] = coerce_number(min(numbers[:2]))
        result["supply_voltage_max_v"] = coerce_number(max(numbers[:2]))
        return result

    if numbers:
        nominal = coerce_number(numbers[-1])
        result["supply_voltage_nominal_v"] = nominal
        result["supply_voltage_min_v"] = nominal
        result["supply_voltage_max_v"] = nominal
    return result


def empty_lamp_row(product: dict[str, Any]) -> dict[str, Any]:
    row = {column: None for column in LAMP_COLUMNS}
    row.update(
        {
            "lamp_id": product["id"],
            "category_id": product["categoryId"],
            "name": product["name"],
            "url": product["url"],
            "image_url": product.get("image"),
            "is_explosion_protected": False,
        }
    )
    return row


def parse_property_into_lamp_row(
    row: dict[str, Any],
    spec: PropertySpec,
    raw_value: str | None,
    parse_failures: Counter[str],
) -> None:
    if spec.code in {"beam_pattern", "mounting_type", "explosion_protection_marking", "climate_execution", "ingress_protection", "electrical_protection_class"}:
        row[spec.target_column] = raw_value
        if spec.code == "explosion_protection_marking":
            row["is_explosion_protected"] = raw_value is not None
        return

    if spec.code in {"luminous_flux_lm", "power_w", "weight_kg"}:
        parsed = parse_simple_number(raw_value)
        row[spec.target_column] = parsed
        if raw_value and parsed is None:
            parse_failures[spec.code] += 1
        return

    if spec.code == "color_temperature_k":
        parsed = parse_simple_number(raw_value)
        row["color_temperature_k"] = parsed
        if raw_value and parsed is None:
            parse_failures[spec.code] += 1
        return

    if spec.code == "color_rendering_index_ra":
        parsed = parse_simple_number(raw_value)
        row["color_rendering_index_ra"] = parsed
        if raw_value and parsed is None:
            parse_failures[spec.code] += 1
        return

    if spec.code == "power_factor_min":
        operator, parsed = parse_power_factor(raw_value)
        row["power_factor_operator"] = operator
        row["power_factor_min"] = parsed
        if raw_value and parsed is None:
            parse_failures[spec.code] += 1
        return

    if spec.code == "operating_temperature_range":
        row["operating_temperature_range_raw"] = raw_value
        minimum, maximum = parse_temperature_range(raw_value)
        row["operating_temperature_min_c"] = minimum
        row["operating_temperature_max_c"] = maximum
        if raw_value and (minimum is None or maximum is None):
            parse_failures[spec.code] += 1
        return

    if spec.code == "supply_voltage":
        voltage = parse_voltage(raw_value)
        row.update(voltage)
        if raw_value and voltage["supply_voltage_min_v"] is None and voltage["supply_voltage_nominal_v"] is None:
            parse_failures[spec.code] += 1
        return

    if spec.code == "dimensions_mm":
        row["dimensions_raw"] = raw_value
        length, width, height = parse_dimensions(raw_value)
        row["length_mm"] = length
        row["width_mm"] = width
        row["height_mm"] = height
        if raw_value and (length is None or width is None or height is None):
            parse_failures[spec.code] += 1
        return

    if spec.code == "warranty_years":
        parsed = parse_simple_number(raw_value)
        row["warranty_years"] = parsed
        if raw_value and parsed is None:
            parse_failures[spec.code] += 1
        return


def write_rows(path: Path, rows: list[dict[str, Any]], table_format: str) -> None:
    if table_format == "jsonl":
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False))
                handle.write("\n")
        return

    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def transform_catalog(input_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    products = payload["products"]

    lamps: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    raw_properties: list[dict[str, Any]] = []
    parse_failures: Counter[str] = Counter()
    unknown_property_names: set[str] = set()

    for product in products:
        lamp_row = empty_lamp_row(product)

        for property_item in product["properties"]:
            property_name = property_item["propertyName"]
            raw_value = normalize_text(property_item.get("propertyValue"))
            raw_measure = normalize_text(property_item.get("propertyMeasure"))
            spec = PROPERTY_SPEC_BY_NAME.get(property_name)
            property_code = spec.code if spec else slugify_identifier(property_name)
            if spec:
                parse_property_into_lamp_row(lamp_row, spec, raw_value, parse_failures)
            else:
                unknown_property_names.add(property_name)

            raw_properties.append(
                {
                    "lamp_id": product["id"],
                    "property_code": property_code,
                    "property_name_ru": property_name,
                    "property_value_raw": raw_value,
                    "property_measure_raw": raw_measure,
                }
            )

        lamps.append(lamp_row)

        doc_row = {"lamp_id": product["id"]}
        docs_payload = product.get("docs") or {}
        for doc_spec in DOCUMENT_SPECS:
            doc_row[doc_spec["column"]] = normalize_text(docs_payload.get(doc_spec["source_key"]))
        documents.append(doc_row)

    summary = {
        "source_file": str(input_path),
        "lamp_row_count": len(lamps),
        "document_row_count": len(documents),
        "raw_property_row_count": len(raw_properties),
        "expected_property_rows": len(products) * 16,
        "documents_per_product": len(DOCUMENT_SPECS),
        "properties_per_product": 16,
        "parse_failures": dict(parse_failures),
        "unknown_properties": sorted(unknown_property_names),
    }

    return {
        "lamps": lamps,
        "documents": documents,
        "raw_properties": raw_properties,
        "summary": summary,
    }


def remove_legacy_outputs(output_dir: Path) -> None:
    legacy_names = [
        "catalog_categories.jsonl",
        "catalog_categories.csv",
        "catalog_lamp_filter_values.jsonl",
        "catalog_lamp_filter_values.csv",
        "catalog_lamp_property_dictionary.json",
        "catalog_summary.json",
        "catalog_schema.sql",
    ]
    for name in legacy_names:
        path = output_dir / name
        if path.exists():
            path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transform catalog.json into normalized table-shaped outputs.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("catalog.json"),
        help="Path to the source catalog.json file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("normalized_catalog"),
        help="Directory for generated tables.",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="jsonl",
        help="Tabular output format for generated tables.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    transformed = transform_catalog(args.input)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    remove_legacy_outputs(args.output_dir)
    extension = args.format

    write_rows(
        args.output_dir / f"catalog_lamps.{extension}",
        transformed["lamps"],
        args.format,
    )
    write_rows(
        args.output_dir / f"catalog_lamp_documents.{extension}",
        transformed["documents"],
        args.format,
    )
    write_rows(
        args.output_dir / f"catalog_lamp_properties_raw.{extension}",
        transformed["raw_properties"],
        args.format,
    )
    print(json.dumps(transformed["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
