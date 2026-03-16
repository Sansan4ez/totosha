#!/usr/bin/env python3
"""
Обновляет db/portfolio.json на основе db/portfolio_with_spheres.csv и db/spheres.json.

Что делает:
1. Переименовывает поле `categoryName` в `groupName`.
2. Находит для каждой записи сферу из CSV по точному совпадению поля `name`.
3. Добавляет поле `sphereId` по совпадению `sphere_name` из CSV с `name` в spheres.json.
4. Не сохраняет промежуточное поле `sphere_name` в итоговый JSON.

Если в данных есть несколько записей с одинаковым `name`, скрипт сопоставляет их
по порядку появления в пределах этого имени. Перед преобразованием скрипт
проверяет, что количество повторов в JSON и CSV совпадает.

По умолчанию перезаписывает исходный файл:
    python scripts/update_portfolio_spheres.py

Можно запустить без записи:
    python scripts/update_portfolio_spheres.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Обновляет portfolio.json, добавляя groupName и sphereId."
    )
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=Path("db/portfolio.json"),
        help="Путь до portfolio.json",
    )
    parser.add_argument(
        "--portfolio-csv",
        type=Path,
        default=Path("db/portfolio_with_spheres.csv"),
        help="Путь до CSV с group_name и sphere_name",
    )
    parser.add_argument(
        "--spheres",
        type=Path,
        default=Path("db/spheres.json"),
        help="Путь до spheres.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Куда записать обновленный portfolio.json. По умолчанию перезаписывает исходный файл.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только проверить соответствия и показать итоговую статистику без записи файла.",
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
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error

    required_columns = {"name", "group_name", "sphere_name"}
    if reader.fieldnames is None:
        raise SystemExit(f"В CSV {path} отсутствует заголовок")

    missing_columns = sorted(required_columns - set(reader.fieldnames))
    if missing_columns:
        raise SystemExit(
            f"В CSV {path} отсутствуют обязательные колонки: {', '.join(missing_columns)}"
        )

    return rows


def validate_root(data: Any, key: str, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    value = data.get(key)
    if not isinstance(value, list):
        raise SystemExit(f"Ожидался список {key!r} в {path}")

    for item in value:
        if not isinstance(item, dict):
            raise SystemExit(f"Все элементы {key!r} в {path} должны быть объектами")

    return value


def build_sphere_id_index(spheres: list[dict[str, Any]]) -> dict[str, int]:
    sphere_id_by_name: dict[str, int] = {}

    for sphere in spheres:
        sphere_name = sphere.get("name")
        sphere_id = sphere.get("id")

        if not sphere_name:
            raise SystemExit(f"В spheres.json найдена сфера без поля 'name': {sphere}")

        if sphere_id is None:
            raise SystemExit(
                f"В spheres.json у сферы {sphere_name!r} отсутствует поле 'id'"
            )

        if sphere_name in sphere_id_by_name:
            raise SystemExit(
                f"В spheres.json найдено несколько сфер с name={sphere_name!r}"
            )

        sphere_id_by_name[str(sphere_name)] = int(sphere_id)

    return sphere_id_by_name


def build_csv_rows_by_name(rows: list[dict[str, str]]) -> dict[str, deque[dict[str, str]]]:
    rows_by_name: dict[str, deque[dict[str, str]]] = defaultdict(deque)

    for row in rows:
        name = row.get("name")
        if not name:
            raise SystemExit(f"В CSV найдена строка без поля 'name': {row}")
        rows_by_name[name].append(row)

    return rows_by_name


def validate_name_counts(
    portfolio: list[dict[str, Any]], csv_rows: list[dict[str, str]]
) -> None:
    portfolio_counts = Counter()
    csv_counts = Counter()

    for item in portfolio:
        name = item.get("name")
        if not name:
            raise SystemExit(
                f"В portfolio.json найдена запись без поля 'name': {item}"
            )
        portfolio_counts[str(name)] += 1

    for row in csv_rows:
        csv_counts[row["name"]] += 1

    missing_in_csv = {
        name: count
        for name, count in portfolio_counts.items()
        if csv_counts.get(name, 0) < count
    }
    extra_in_csv = {
        name: count
        for name, count in csv_counts.items()
        if portfolio_counts.get(name, 0) < count
    }

    if missing_in_csv or extra_in_csv:
        messages: list[str] = []

        if missing_in_csv:
            preview = ", ".join(
                f"{name!r}: {count}" for name, count in sorted(missing_in_csv.items())
            )
            messages.append(f"Не хватает строк в CSV для name: {preview}")

        if extra_in_csv:
            preview = ", ".join(
                f"{name!r}: {count}" for name, count in sorted(extra_in_csv.items())
            )
            messages.append(f"В CSV есть лишние строки для name: {preview}")

        raise SystemExit(". ".join(messages))


def transform_portfolio_item(
    item: dict[str, Any],
    matched_row: dict[str, str],
    sphere_id_by_name: dict[str, int],
) -> dict[str, Any]:
    group_name = matched_row["group_name"]
    sphere_name = matched_row["sphere_name"]

    if not group_name:
        raise SystemExit(
            f"Для записи {item.get('name')!r} в CSV отсутствует значение group_name"
        )

    if not sphere_name:
        raise SystemExit(
            f"Для записи {item.get('name')!r} в CSV отсутствует значение sphere_name"
        )

    sphere_id = sphere_id_by_name.get(sphere_name)
    if sphere_id is None:
        raise SystemExit(
            f"Не найдена сфера с name={sphere_name!r} из CSV для записи {item.get('name')!r}"
        )

    source_group_name = item.get("categoryName")
    if source_group_name is not None and str(source_group_name) != group_name:
        raise SystemExit(
            f"Для записи {item.get('name')!r} group_name из CSV ({group_name!r}) "
            f"не совпадает с categoryName в JSON ({source_group_name!r})"
        )

    transformed: dict[str, Any] = {}
    for key, value in item.items():
        if key == "categoryName":
            transformed["groupName"] = group_name
            continue
        transformed[key] = value

    if "groupName" not in transformed:
        transformed["groupName"] = group_name

    transformed["sphereId"] = sphere_id
    return transformed


def transform_portfolio(
    portfolio: list[dict[str, Any]],
    csv_rows_by_name: dict[str, deque[dict[str, str]]],
    sphere_id_by_name: dict[str, int],
) -> list[dict[str, Any]]:
    transformed_items: list[dict[str, Any]] = []

    for item in portfolio:
        name = str(item["name"])
        rows = csv_rows_by_name.get(name)
        if not rows:
            raise SystemExit(f"Не найдена строка в CSV для записи {name!r}")

        transformed_items.append(
            transform_portfolio_item(item, rows.popleft(), sphere_id_by_name)
        )

    leftovers = {
        name: len(rows) for name, rows in csv_rows_by_name.items() if rows
    }
    if leftovers:
        preview = ", ".join(
            f"{name!r}: {count}" for name, count in sorted(leftovers.items())
        )
        raise SystemExit(f"После обработки в CSV остались лишние строки: {preview}")

    return transformed_items


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=4)
        tmp.write("\n")
        temp_path = Path(tmp.name)

    temp_path.replace(path)


def main() -> int:
    args = parse_args()

    portfolio_data = load_json(args.portfolio)
    spheres_data = load_json(args.spheres)
    csv_rows = load_csv_rows(args.portfolio_csv)

    portfolio = validate_root(portfolio_data, "portfolio", args.portfolio)
    spheres = validate_root(spheres_data, "spheres", args.spheres)

    validate_name_counts(portfolio, csv_rows)

    csv_rows_by_name = build_csv_rows_by_name(csv_rows)
    sphere_id_by_name = build_sphere_id_index(spheres)
    transformed_portfolio = transform_portfolio(
        portfolio, csv_rows_by_name, sphere_id_by_name
    )

    output_data = dict(portfolio_data)
    output_data["portfolio"] = transformed_portfolio

    if args.dry_run:
        duplicate_names = sum(1 for count in Counter(row["name"] for row in csv_rows).values() if count > 1)
        print(f"Проверка пройдена: {len(transformed_portfolio)} записей готовы к обновлению.")
        print(f"Повторяющихся name обработано по порядку: {duplicate_names}")
        return 0

    output_path = args.output or args.portfolio
    write_json(output_path, output_data)
    print(f"Файл обновлен: {output_path}")
    print(f"Обработано записей: {len(transformed_portfolio)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
