"""Helpers to derive safe widget artifacts from agent text responses."""

from __future__ import annotations

import json
import re
from typing import Optional


_FENCED_ARTIFACT_RE = re.compile(
    r"```ui_artifact\s*(\{.*?\})\s*```",
    re.IGNORECASE | re.DOTALL,
)
_FIELD_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_ ]{1,40})\s*:\s*(.+?)\s*$")


def _clean_heading(value: str) -> str:
    return re.sub(r"^[#*\-\s]+", "", value).strip()


def _find_leading_heading(text: str, *, max_lines: int = 6) -> str:
    for line in text.splitlines()[:max_lines]:
        cleaned = _clean_heading(line)
        if cleaned:
            return cleaned[:240]
    return ""


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(bool(re.fullmatch(r":?-{3,}:?", cell.replace(" ", ""))) for cell in cells)


def _extract_markdown_table(text: str) -> Optional[dict]:
    lines = [line.rstrip() for line in text.splitlines()]
    for index in range(len(lines) - 1):
        header_line = lines[index]
        separator_line = lines[index + 1]
        if "|" not in header_line or "|" not in separator_line or not _is_separator_row(separator_line):
            continue
        header_cells = _split_table_row(header_line)
        if len(header_cells) < 2 or any(not cell for cell in header_cells):
            continue

        row_lines: list[str] = []
        for candidate in lines[index + 2 :]:
            if "|" not in candidate:
                break
            row_lines.append(candidate)
        if not row_lines:
            continue

        parsed_rows = []
        numeric_columns = []
        for row_line in row_lines:
            cells = _split_table_row(row_line)
            if len(cells) != len(header_cells):
                parsed_rows = []
                break
            parsed_rows.append(cells)

        if not parsed_rows:
            continue

        if len(header_cells) == 2:
            numeric_columns = []
            for row in parsed_rows:
                try:
                    numeric_columns.append(
                        {
                            "label": row[0],
                            "value": float(row[1].replace(",", "").strip()),
                        }
                    )
                except ValueError:
                    numeric_columns = []
                    break

        heading = _find_leading_heading("\n".join(lines[:index]))
        children = []
        if heading:
            children.append({"name": "header", "content": heading})
        if numeric_columns:
            children.append({"name": "bar_chart", "columns": numeric_columns})
        else:
            children.append(
                {
                    "name": "table",
                    "columns": [
                        {"key": f"col_{column_index}", "title": title}
                        for column_index, title in enumerate(header_cells)
                    ],
                    "rows": [{"values": row} for row in parsed_rows],
                }
            )

        return {
            "type": "component_tree",
            "version": "v1",
            "payload": {
                "root": {
                    "name": "card",
                    "children": children,
                }
            },
        }
    return None


def _extract_field_list_card(text: str) -> Optional[dict]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = _FIELD_LINE_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip().lower().replace(" ", "_")
        fields[key] = match.group(2).strip()

    title = fields.get("title") or fields.get("name") or fields.get("item_name")
    if not title:
        return None

    description = fields.get("description") or fields.get("summary")
    price = fields.get("price")
    image_url = fields.get("image") or fields.get("image_url")
    eyebrow = fields.get("category") or fields.get("type")
    cta_label = fields.get("cta") or fields.get("action")

    return {
        "type": "component_tree",
        "version": "v1",
        "payload": {
            "root": {
                "name": "item_card",
                "title": title,
                "description": description,
                "price": price,
                "image_url": image_url,
                "eyebrow": eyebrow,
                "cta_label": cta_label,
            }
        },
    }


def _extract_fenced_artifact(text: str) -> tuple[str, Optional[dict]]:
    match = _FENCED_ARTIFACT_RE.search(text)
    if not match:
        return text, None

    try:
        artifact = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text, None

    cleaned = (text[: match.start()] + text[match.end() :]).strip()
    return cleaned, artifact


def extract_ui_artifact(text: str, source: str) -> tuple[str, Optional[dict]]:
    if source != "web":
        return text, None

    cleaned_text, explicit_artifact = _extract_fenced_artifact(text)
    if explicit_artifact is not None:
        return cleaned_text or text, explicit_artifact

    table_artifact = _extract_markdown_table(text)
    if table_artifact is not None:
        return text, table_artifact

    card_artifact = _extract_field_list_card(text)
    if card_artifact is not None:
        return text, card_artifact

    return text, None
