#!/usr/bin/env python3
"""
Преобразует `db/mounting_types_rows.csv` в валидный JSON.

В результирующем JSON сохраняются все поля, кроме `created_at` и `updated_at`.
По умолчанию результат записывается в `db/mounting_types_rows.json`.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


EXPECTED_FIELDS = [
    "id",
    "name",
    "mark",
    "description",
    "image_url",
    "url",
    "created_at",
    "updated_at",
]

OUTPUT_FIELDS = ["id", "name", "mark", "description", "image_url", "url"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Конвертирует mounting_types_rows.csv в JSON без полей "
            "created_at и updated_at."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("db/mounting_types_rows.csv"),
        help="Путь к исходному CSV-файлу.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("db/mounting_types_rows.json"),
        help="Куда записать JSON.",
    )
    parser.add_argument(
        "--json-root-key",
        default="mountingTypes",
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
        help="Проверяет данные и показывает статистику без записи файла.",
    )
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            fieldnames = reader.fieldnames or []
            if fieldnames != EXPECTED_FIELDS:
                raise SystemExit(
                    f"Неожиданные колонки в {path}: {fieldnames}. "
                    f"Ожидались: {EXPECTED_FIELDS}"
                )
            return [dict(row) for row in reader]
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error


def parse_int(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise SystemExit(f"Поле {field_name!r} содержит нецелое значение: {value!r}") from error


def normalize_text(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def transform_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": parse_int(row["id"], "id"),
        "name": row["name"],
        "mark": row["mark"],
        "description": normalize_text(row["description"]),
        "image_url": normalize_text(row["image_url"]),
        "url": normalize_text(row["url"]),
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=4)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def main() -> int:
    args = parse_args()

    rows = load_rows(args.input)
    transformed_rows = [transform_row(row) for row in rows]

    if args.dry_run:
        print(f"Проверка пройдена: строк={len(transformed_rows)}, файл={args.output}")
        return 0

    payload: Any
    if args.json_array:
        payload = transformed_rows
    else:
        payload = {args.json_root_key: transformed_rows}

    write_json(args.output, payload)
    print(f"Готово: строк={len(transformed_rows)}, файл={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
