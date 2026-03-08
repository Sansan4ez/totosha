---
name: corp-wiki-md-search
description: Поиск по корпоративной wiki (Markdown) компании «ЛАДзавод светотехники»: контакты, реквизиты, продукты/серии, регламенты, процессы. Используй этот скилл каждый раз, когда вопрос про компанию и нужно отвечать «согласно wiki». Источник: /data/skills/corp-wiki-md-search/wiki/ (папка с .md в Totosha).
---

# Corp wiki markdown search

Use this skill to search the local корпоративная wiki in Markdown and present results as:
- **Top 3 files** by number of matches
- For each file: **2–3 lines of preview around the match** (context)

## Default wiki location

- Primary wiki folder (Totosha): `/data/skills/corp-wiki-md-search/wiki/` (Markdown files: `**/*.md`)

If the wiki later becomes a folder of Markdown pages, the same script supports directory search.

## Quick workflow

1) Clarify the query string (what to search).
2) Run the search script.
3) Respond with:
   - top 3 files + match counts
   - 2–3 lines around each match
   - ask a follow-up question if the query is too broad

## Run the search

### Search the default wiki (folder)

```bash
python3 /data/skills/corp-wiki-md-search/scripts/wiki_search.py "<query>" \
  --ignore-case --top 3 --context 2 --max-matches-per-file 5 --link-style plain
```

> Поиск **неточный**: запрос нормализуется в «стемы» (например, `контакты` → `контакт\w*`), поэтому находит и формы вроде «контактная». Слова в запросе ищутся **в любом порядке**. Для многословных запросов поиск идёт **по блоку/абзацу** (не только по одной строке).

`--link-style`:
- `plain` → `wiki/page.md:123` (универсально для чатов)
- `github` → `wiki/page.md#L123` (удобно для GitHub/GitLab-like)
- `file` → `file:///abs/path.md#L123` (для локальных просмотрщиков)

### Search a folder of .md pages (if applicable)

```bash
python3 /data/skills/corp-wiki-md-search/scripts/wiki_search.py "<query>" --path /path/to/wiki_dir --glob "**/*.md" --ignore-case --top 3 --context 1
```

## Output rules (how to answer)

- Prefer a compact bullet list.
- Do **not** dump large sections; show only short previews.
- Offer to open/quote the most relevant section if the user wants more detail.
