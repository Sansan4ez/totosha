#!/usr/bin/env python3
"""
Преобразует `db/lamp_mountings_rows.csv`:

1. Заменяет поле `category_name` на `categoryId` по данным `db/categories.json`.
2. По умолчанию сохраняет результат как JSON в `db/lamp_mountings_rows.json`.
3. По `--format csv` может записать обновлённый CSV.

Для известных расхождений имён использует фиксированные алиасы. Значение
`LAD LED R320-4 Ex` мапится на категорию серии `LAD LED R320 Ex`, потому что
отдельной категории с таким именем в `categories.json` нет.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


CATEGORY_NAME_ALIASES: dict[str, str] = {
    "LAD LED LINE-15": "LAD LED LINE-300-15",
    "LAD LED LINE-25": "LAD LED LINE-600-25",
    "LAD LED LINE-40": "LAD LED LINE-1000-40",
    "LAD LED LINE-60": "LAD LED LINE-1000-60",
    "LAD LED LINE OZ-15": "LAD LED LINE-OZ",
    "LAD LED LINE OZ-25": "LAD LED LINE-OZ",
    "NL Nova 30": "NL Nova30",
    "NL Nova 60": "NL Nova60",
    "NL Nova 120": "NL Nova120",
    "LAD LED R320-4 Ex": "LAD LED R320 Ex",
}

CSV_OUTPUT_FIELDNAMES = [
    "id",
    "series",
    "categoryId",
    "mounting_type_id",
    "is_default",
    "created_at",
    "updated_at",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Заменяет category_name на categoryId в lamp_mountings_rows.csv "
            "и сохраняет результат в JSON или CSV."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("db/lamp_mountings_rows.csv"),
        help="Путь к исходному CSV-файлу.",
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path("db/categories.json"),
        help="Путь к файлу categories.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Куда записать результат. По умолчанию путь зависит от выбранного формата.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Формат выходного файла.",
    )
    parser.add_argument(
        "--json-root-key",
        default="lampMountings",
        help="Корневой ключ для JSON-объекта, если не используется --json-array.",
    )
    parser.add_argument(
        "--json-array",
        action="store_true",
        help="Сохраняет JSON как массив, а не как объект с корневым ключом.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверяет соответствия и показывает статистику без записи файла.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Некорректный JSON в {path}: {error}") from error


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames or []
            expected_fields = {
                "id",
                "series",
                "category_name",
                "mounting_type_id",
                "is_default",
                "created_at",
                "updated_at",
            }
            if set(fieldnames) != expected_fields:
                raise SystemExit(
                    f"Неожиданные колонки в {path}: {fieldnames}. "
                    f"Ожидались: {sorted(expected_fields)}"
                )
            return [dict(row) for row in reader]
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error


def validate_categories(data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    categories = data.get("categories")
    if not isinstance(categories, list):
        raise SystemExit(f"Ожидался список 'categories' в {path}")

    for category in categories:
        if not isinstance(category, dict):
            raise SystemExit(f"Все элементы 'categories' в {path} должны быть объектами")

    return categories


def build_categories_index(
    categories: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}

    for category in categories:
        name = category.get("name")
        category_id = category.get("id")
        if not name:
            continue
        if category_id is None:
            raise SystemExit(f"У категории {name!r} отсутствует поле 'id'")
        index.setdefault(str(name), []).append(category)

    return index


def select_category_match(
    matches: list[dict[str, Any]],
    source_name: str,
    target_name: str,
) -> tuple[dict[str, Any], str]:
    if len(matches) == 1:
        return matches[0], "alias" if source_name != target_name else "exact"

    top_level_matches = [match for match in matches if not match.get("parent")]
    if len(top_level_matches) == 1:
        return top_level_matches[0], "prefer-top-level"

    match_descriptions = ", ".join(
        f"id={match.get('id')}, url={match.get('url')!r}" for match in matches
    )
    raise SystemExit(
        f"Найдено несколько категорий для {source_name!r} "
        f"(цель поиска: {target_name!r}). Кандидаты: {match_descriptions}"
    )


def resolve_category_id(
    row: dict[str, str],
    categories_by_name: dict[str, list[dict[str, Any]]],
) -> tuple[int, str, str]:
    source_name = (row.get("category_name") or "").strip()
    if not source_name:
        raise SystemExit(f"Найдена строка без category_name: {row}")

    target_name = CATEGORY_NAME_ALIASES.get(source_name, source_name)
    matches = categories_by_name.get(target_name, [])
    if not matches:
        raise SystemExit(
            f"Не найдена категория для {source_name!r} "
            f"(цель поиска: {target_name!r})"
        )

    selected_category, resolution_kind = select_category_match(
        matches, source_name, target_name
    )
    return int(selected_category["id"]), resolution_kind, target_name


def parse_int(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit(f"Поле {field_name!r} содержит нецелое значение: {value!r}") from error


def parse_bool(value: str, field_name: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise SystemExit(f"Поле {field_name!r} содержит некорректный bool: {value!r}")


def transform_row_for_json(row: dict[str, str], category_id: int) -> dict[str, Any]:
    return {
        "id": parse_int(row["id"], "id"),
        "series": row["series"],
        "categoryId": category_id,
        "mounting_type_id": parse_int(row["mounting_type_id"], "mounting_type_id"),
        "is_default": parse_bool(row["is_default"], "is_default"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def transform_row_for_csv(row: dict[str, str], category_id: int) -> dict[str, str]:
    return {
        "id": row["id"],
        "series": row["series"],
        "categoryId": str(category_id),
        "mounting_type_id": row["mounting_type_id"],
        "is_default": row["is_default"].strip().lower(),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def default_output_path(input_path: Path, output_format: str) -> Path:
    if output_format == "csv":
        return input_path
    return input_path.with_suffix(".json")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=4)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=CSV_OUTPUT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def format_alias_stats(alias_usage: Counter[str]) -> str:
    items = [
        f"{source} -> {CATEGORY_NAME_ALIASES[source]} ({count})"
        for source, count in sorted(alias_usage.items())
    ]
    return "; ".join(items)


def main() -> int:
    args = parse_args()

    source_rows = load_csv_rows(args.input)
    categories_data = load_json(args.categories)
    categories = validate_categories(categories_data, args.categories)
    categories_by_name = build_categories_index(categories)

    transformed_rows: list[dict[str, Any]] = []
    resolution_stats: Counter[str] = Counter()
    alias_usage: Counter[str] = Counter()

    for row in source_rows:
        category_id, resolution_kind, target_name = resolve_category_id(
            row, categories_by_name
        )
        resolution_stats[resolution_kind] += 1
        if row["category_name"] != target_name:
            alias_usage[row["category_name"]] += 1

        if args.format == "json":
            transformed_rows.append(transform_row_for_json(row, category_id))
        else:
            transformed_rows.append(transform_row_for_csv(row, category_id))

    output_path = args.output or default_output_path(args.input, args.format)

    if args.dry_run:
        print(
            "Проверка пройдена: "
            f"строк={len(transformed_rows)}, "
            f"exact={resolution_stats['exact']}, "
            f"alias={resolution_stats['alias']}, "
            f"prefer_top_level={resolution_stats['prefer-top-level']}"
        )
        if alias_usage:
            print(f"Использованы алиасы: {format_alias_stats(alias_usage)}")
        print(f"Файл для записи: {output_path}")
        return 0

    if args.format == "json":
        payload: Any
        if args.json_array:
            payload = transformed_rows
        else:
            payload = {args.json_root_key: transformed_rows}
        write_json(output_path, payload)
    else:
        write_csv(output_path, transformed_rows)

    print(
        "Готово: "
        f"строк={len(transformed_rows)}, "
        f"exact={resolution_stats['exact']}, "
        f"alias={resolution_stats['alias']}, "
        f"prefer_top_level={resolution_stats['prefer-top-level']}, "
        f"файл={output_path}"
    )
    if alias_usage:
        print(f"Использованы алиасы: {format_alias_stats(alias_usage)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
