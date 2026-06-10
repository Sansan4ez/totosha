#!/usr/bin/env python3
"""
Нормализует значения свойств в `db/catalog.json`.

Скрипт:
- сохраняет исходное строковое значение в `propertyValue` по умолчанию;
- добавляет структурированные поля для фильтрации и поиска;
- удаляет поле `categoryName` из товаров, так как оно дублируется в `db/categories.json`;
- умеет при необходимости заменить `propertyValue` на нормализованное значение.

Поддерживаемые кейсы:
- единицы измерения, встроенные в `propertyValue` (`5000K`, `5 лет`);
- квалификаторы (`Ra 80`);
- знаки сравнения (`≧ 0.95`);
- диапазоны (`–65°С ... +50°С`);
- размеры (`390 x 105 x 82`);
- напряжение питания (`AC230`, `AC/DC 12 - 24`, `220±20%`).

Примеры:
    python scripts/normalize_catalog_property_values.py --dry-run
    python scripts/normalize_catalog_property_values.py --output db/catalog.normalized.json
    python scripts/normalize_catalog_property_values.py --in-place
    python scripts/normalize_catalog_property_values.py --in-place --replace-property-value
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


NORMALIZED_PROPERTY_KEYS = (
    "propertyValueRaw",
    "propertyValueNormalized",
    "propertyValueFrom",
    "propertyValueTo",
    "propertyValueList",
    "propertyAvailableValues",
    "propertySearchValues",
    "propertyCurrentTypes",
    "propertyQualifier",
    "propertySign",
    "propertyTolerance",
)

COMPARE_SIGN_MAP = {
    "≧": ">=",
    "≥": ">=",
    ">=": ">=",
    "=>": ">=",
    "≦": "<=",
    "≤": "<=",
    "<=": "<=",
    "=<": "<=",
    ">": ">",
    "<": "<",
    "=": "=",
}

RANGE_DELIMITERS_RE = re.compile(r"\s*(?:\.\.\.|…|–|—|-)\s*")
NUMBER_RE = r"[+-]?\d+(?:[.,]\d+)?"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Нормализует свойства в db/catalog.json и добавляет поля для "
            "структурированного поиска."
        )
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("db/catalog.json"),
        help="Путь к исходному catalog.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("db/catalog.normalized.json"),
        help="Куда записать результат, если не указан --in-place.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Перезаписывает исходный catalog.json вместо отдельного файла.",
    )
    parser.add_argument(
        "--replace-property-value",
        action="store_true",
        help=(
            "Заменяет propertyValue на нормализованное значение, а исходную "
            "строку переносит в propertyValueRaw."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показывает статистику без записи файла.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Некорректный JSON в {path}: {error}") from error


def validate_catalog(data: Any, path: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    products = data.get("products")
    if not isinstance(products, list):
        raise SystemExit(f"Ожидался список 'products' в {path}")

    for product in products:
        if not isinstance(product, dict):
            raise SystemExit(f"Все элементы 'products' в {path} должны быть объектами")
        properties = product.get("properties")
        if properties is None:
            continue
        if not isinstance(properties, list):
            raise SystemExit(
                f"Поле 'properties' у продукта {product.get('id')} должно быть списком"
            )
        for property_item in properties:
            if not isinstance(property_item, dict):
                raise SystemExit(
                    f"Все элементы 'properties' у продукта {product.get('id')} должны быть объектами"
                )

    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=4)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def parse_number(value: str) -> int | float:
    normalized = value.replace(",", ".").strip()
    number = float(normalized)
    if number.is_integer():
        return int(number)
    return number


def number_to_string(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def uniq_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        result.append(stripped)
    return result


def normalize_measure(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    lowered = stripped.lower()
    if stripped in {"K", "К", "k", "к"}:
        return "К"
    if stripped in {"°С", "°C", "C", "С"}:
        return "°C"
    if lowered in {"в", "v"}:
        return "В"
    if lowered in {"мм", "mm"}:
        return "мм"
    if lowered in {"кг", "kg"}:
        return "кг"
    if lowered in {"лм", "lm"}:
        return "Лм"
    if lowered in {"вт", "w"}:
        return "Вт"
    if lowered in {"лет", "год", "года", "г.", "yr", "years"}:
        return "лет"
    return stripped


def cleanup_property(property_item: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(property_item)
    for key in NORMALIZED_PROPERTY_KEYS:
        cleaned.pop(key, None)
    return cleaned


def normalize_scalar_with_measure(
    raw_value: str,
    measure_candidates: tuple[str, ...],
) -> tuple[int | float, str] | None:
    pattern = re.compile(
        rf"^\s*({NUMBER_RE})\s*({'|'.join(re.escape(item) for item in measure_candidates)})\s*$",
        re.IGNORECASE,
    )
    match = pattern.match(raw_value)
    if not match:
        return None
    value = parse_number(match.group(1))
    measure = normalize_measure(match.group(2))
    if measure is None:
        return None
    return value, measure


def normalize_qualified_value(raw_value: str) -> tuple[str, int | float] | None:
    match = re.match(rf"^\s*([A-Za-zА-Яа-я]+)\s*({NUMBER_RE})\s*$", raw_value)
    if not match:
        return None
    qualifier = match.group(1).strip()
    value = parse_number(match.group(2))
    return qualifier, value


def normalize_compare_value(raw_value: str) -> tuple[str, int | float] | None:
    match = re.match(rf"^\s*([<>]=?|[≧≥≦≤=]+)\s*({NUMBER_RE})\s*$", raw_value)
    if not match:
        return None
    sign = COMPARE_SIGN_MAP.get(match.group(1).strip())
    if sign is None:
        return None
    value = parse_number(match.group(2))
    return sign, value


def normalize_temperature_range(raw_value: str) -> tuple[int | float, int | float, str] | None:
    cleaned = (
        raw_value.replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("°С", "°C")
        .replace("° C", "°C")
    )
    match = re.match(
        rf"^\s*({NUMBER_RE})\s*°C\s*(?:\.\.\.|…)\s*({NUMBER_RE})\s*°C\s*$",
        cleaned,
        re.IGNORECASE,
    )
    if not match:
        return None
    return parse_number(match.group(1)), parse_number(match.group(2)), "°C"


def normalize_dimension_list(raw_value: str) -> tuple[list[int | float], str] | None:
    parts = re.split(r"\s*[xх×]\s*", raw_value.strip(), flags=re.IGNORECASE)
    if len(parts) < 2:
        return None
    try:
        values = [parse_number(part) for part in parts]
    except ValueError:
        return None
    return values, "мм"


def normalize_voltage_value(
    raw_value: str,
) -> tuple[list[str], list[int | float], int | float | None, int | float | None, str, str | None] | None:
    prepared = (
        raw_value.upper()
        .replace("АС", "AC")
        .replace("В", "")
        .replace("V", "")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace(" ", "")
    )

    asymmetric_tolerance_match = re.match(
        rf"^({NUMBER_RE})\+(\d+(?:[.,]\d+)?)%,({NUMBER_RE})-(\d+(?:[.,]\d+)?)%$",
        prepared,
    )
    if asymmetric_tolerance_match:
        nominal_up = parse_number(asymmetric_tolerance_match.group(1))
        nominal_down = parse_number(asymmetric_tolerance_match.group(3))
        if nominal_up == nominal_down:
            tolerance = (
                f"+{asymmetric_tolerance_match.group(2)}%"
                f"/-{asymmetric_tolerance_match.group(4)}%"
            )
            return [], [nominal_up], nominal_up, nominal_up, "В", tolerance

    tolerance_match = re.match(rf"^({NUMBER_RE})(±\d+(?:[.,]\d+)?%)$", prepared)
    if tolerance_match:
        value = parse_number(tolerance_match.group(1))
        return [], [value], value, value, "В", tolerance_match.group(2)

    match = re.match(rf"^(AC/DC|AC|DC)({NUMBER_RE})(?:-({NUMBER_RE}))?$", prepared)
    if not match:
        return None

    current_group = match.group(1)
    current_types = current_group.split("/")
    start_value = parse_number(match.group(2))
    end_value = parse_number(match.group(3)) if match.group(3) else start_value

    available_values = [start_value]
    if end_value != start_value:
        available_values.append(end_value)

    return current_types, available_values, start_value, end_value, "В", None


def apply_structured_fields(
    property_item: dict[str, Any],
    raw_value: str,
    *,
    replace_property_value: bool,
    normalized_value: Any | None = None,
    value_from: int | float | None = None,
    value_to: int | float | None = None,
    value_list: list[int | float] | None = None,
    available_values: list[int | float] | None = None,
    measure: str | None = None,
    qualifier: str | None = None,
    sign: str | None = None,
    tolerance: str | None = None,
    current_types: list[str] | None = None,
    search_values: list[str] | None = None,
) -> dict[str, Any]:
    updated = cleanup_property(property_item)

    normalized_measure = normalize_measure(measure) if measure is not None else None
    if normalized_measure is not None:
        updated["propertyMeasure"] = normalized_measure

    if qualifier:
        updated["propertyQualifier"] = qualifier
    if sign:
        updated["propertySign"] = sign
    if tolerance:
        updated["propertyTolerance"] = tolerance
    if current_types:
        updated["propertyCurrentTypes"] = current_types
    if value_from is not None:
        updated["propertyValueFrom"] = value_from
    if value_to is not None:
        updated["propertyValueTo"] = value_to
    if value_list:
        updated["propertyValueList"] = value_list
    if available_values:
        updated["propertyAvailableValues"] = available_values
    if normalized_value is not None:
        updated["propertyValueNormalized"] = normalized_value
    if search_values:
        deduplicated = uniq_strings(search_values)
        if deduplicated:
            updated["propertySearchValues"] = deduplicated

    if replace_property_value:
        updated["propertyValueRaw"] = raw_value
        if value_list is not None:
            updated["propertyValue"] = None
        elif value_from is not None and value_to is not None and normalized_value is None:
            updated["propertyValue"] = None
        elif available_values and normalized_value is None:
            updated["propertyValue"] = None
        else:
            updated["propertyValue"] = normalized_value

    return updated


def normalize_property(
    property_item: dict[str, Any],
    counters: Counter[str],
    *,
    replace_property_value: bool,
) -> dict[str, Any]:
    raw_value = property_item.get("propertyValue")
    if not isinstance(raw_value, str):
        return cleanup_property(property_item)

    property_name = property_item.get("propertyName")
    existing_measure = normalize_measure(property_item.get("propertyMeasure"))

    if property_name == "Цветовая температура":
        parsed = normalize_scalar_with_measure(raw_value, ("K", "К"))
        if parsed:
            value, measure = parsed
            counters["scalar_with_measure"] += 1
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                normalized_value=value,
                measure=existing_measure or measure,
                search_values=[number_to_string(value), f"{number_to_string(value)} {measure}"],
            )

    if property_name == "Гарантийный срок":
        parsed = normalize_scalar_with_measure(raw_value, ("лет", "год", "года", "г."))
        if parsed:
            value, measure = parsed
            counters["scalar_with_measure"] += 1
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                normalized_value=value,
                measure=measure,
                search_values=[number_to_string(value), f"{number_to_string(value)} {measure}"],
            )

    if property_name == "Индекс цветопередачи":
        parsed = normalize_qualified_value(raw_value)
        if parsed:
            qualifier, value = parsed
            counters["qualified_value"] += 1
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                normalized_value=value,
                qualifier=qualifier,
                search_values=[qualifier, number_to_string(value), f"{qualifier} {number_to_string(value)}"],
            )

    if property_name == "Коэффициент мощности":
        parsed = normalize_compare_value(raw_value)
        if parsed:
            sign, value = parsed
            counters["compare_value"] += 1
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                normalized_value=value,
                sign=sign,
                search_values=[sign, number_to_string(value), f"{sign} {number_to_string(value)}"],
            )

    if property_name == "Диапазон рабочих температур":
        parsed = normalize_temperature_range(raw_value)
        if parsed:
            value_from, value_to, measure = parsed
            counters["range_value"] += 1
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                value_from=value_from,
                value_to=value_to,
                measure=measure,
                search_values=[
                    number_to_string(value_from),
                    number_to_string(value_to),
                    f"{number_to_string(value_from)} {measure}",
                    f"{number_to_string(value_to)} {measure}",
                    f"{number_to_string(value_from)}..{number_to_string(value_to)} {measure}",
                ],
            )

    if property_name == "Габаритные размеры светильника":
        parsed = normalize_dimension_list(raw_value)
        if parsed:
            values, measure = parsed
            counters["dimension_list"] += 1
            compact_value = "x".join(number_to_string(value) for value in values)
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                value_list=values,
                measure=existing_measure or measure,
                search_values=[compact_value, *[number_to_string(value) for value in values]],
            )

    if property_name == "Напряжение питающей сети":
        parsed = normalize_voltage_value(raw_value)
        if parsed:
            current_types, available_values, value_from, value_to, measure, tolerance = parsed
            search_values = [number_to_string(value) for value in available_values]
            search_values.extend(current_types)
            search_values.extend(
                f"{current_type} {number_to_string(value)} {measure}"
                for current_type in current_types
                for value in available_values
            )
            if tolerance:
                search_values.append(tolerance)
            counters["voltage_value"] += 1
            normalized_value = available_values[0] if len(available_values) == 1 else None
            return apply_structured_fields(
                property_item,
                raw_value,
                replace_property_value=replace_property_value,
                normalized_value=normalized_value,
                value_from=value_from,
                value_to=value_to,
                available_values=available_values,
                current_types=current_types,
                measure=existing_measure or measure,
                tolerance=tolerance,
                search_values=search_values,
            )

    return cleanup_property(property_item)


def normalize_catalog(
    catalog: dict[str, Any],
    *,
    replace_property_value: bool,
) -> tuple[dict[str, Any], Counter[str], int]:
    counters: Counter[str] = Counter()
    normalized_products = 0

    updated_catalog = dict(catalog)
    updated_products: list[dict[str, Any]] = []

    for product in catalog["products"]:
        updated_product = dict(product)
        if "categoryName" in updated_product:
            updated_product.pop("categoryName", None)
            counters["removed_category_name"] += 1
        properties = product.get("properties")
        if not isinstance(properties, list):
            updated_products.append(updated_product)
            continue

        updated_properties = [
            normalize_property(
                property_item,
                counters,
                replace_property_value=replace_property_value,
            )
            for property_item in properties
        ]

        if updated_properties != properties:
            normalized_products += 1

        updated_product["properties"] = updated_properties
        updated_products.append(updated_product)

    updated_catalog["products"] = updated_products
    return updated_catalog, counters, normalized_products


def main() -> int:
    args = parse_args()

    if args.in_place:
        output_path = args.catalog
    else:
        output_path = args.output

    catalog = validate_catalog(load_json(args.catalog), args.catalog)
    normalized_catalog, counters, normalized_products = normalize_catalog(
        catalog,
        replace_property_value=args.replace_property_value,
    )

    normalized_properties = sum(counters.values())
    if args.dry_run:
        print(
            "Проверка пройдена: "
            f"products={len(normalized_catalog['products'])}, "
            f"normalized_products={normalized_products}, "
            f"normalized_properties={normalized_properties}"
        )
        for key in sorted(counters):
            print(f"- {key}: {counters[key]}")
        return 0

    write_json(output_path, normalized_catalog)
    print(
        "Готово: "
        f"products={len(normalized_catalog['products'])}, "
        f"normalized_products={normalized_products}, "
        f"normalized_properties={normalized_properties}, "
        f"file={output_path}"
    )
    for key in sorted(counters):
        print(f"- {key}: {counters[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
