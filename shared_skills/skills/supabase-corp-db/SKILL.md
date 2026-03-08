---
name: supabase-corp-db
description: Query the corporate Supabase PostgREST API (api.llm-studio.pro) to retrieve data about LАDзавод catalogs (catalog_lamps, categories, etm_oracl_catalog_sku, etm_oracl_archive), portfolio projects, series, and spheres. Use when you need to translate a natural-language question into a correct Supabase REST (PostgREST) request with filters, pagination (limit+offset), ordering, JOIN syntax (nested / !inner), or Russian full-text search via rpc/ru_fts.
---

# Supabase corporate DB (PostgREST) — workflow

## 0) Auth & base URL
- Base: set `SUPABASE_REST_URL` (example: `https://<project-ref>.supabase.co/rest/v1`)
- Always send headers:
  - `apikey: $SUPABASE_KEY`
  - `Authorization: Bearer $SUPABASE_KEY`
  - `Accept: application/json`

Use `SUPABASE_KEY` from environment (never hardcode secrets). For public access this must be the **anon/public** key (not `service_role`).

Totosha note:
- If this key must stay private, **do not** expose it to user sandboxes. Prefer a server-side proxy endpoint that injects the key.
- If you intentionally allow end users to query this API, use an **anon/public** key with strict RLS and read-only policies (see `references/supabase-rls-public-readonly.sql`).
  - Extra safety for public traffic: set server-side caps like `pgrst.db_max_rows` and `statement_timeout` for the `anon` role (also in that SQL file).

## 1) Map the user question → tables
Common mappings:
- **Каталог светильников** → `catalog_lamps` (есть `category_id` и также текстовое `category_name`)
- **Категории/иерархия категорий** → `categories` (`id`, `name`, `parent_id` …)
- **Коды/артикулы/описания SKU (ETM/ORACL/1C/WMS)** → `etm_oracl_catalog_sku` (+ join to `catalog_lamps` when нужен name/series/category)
- **Архив кодов** → `etm_oracl_archive`
- **Реализованные проекты** → `portfolio` (наблюдаемые поля: `group_name`, `sphere_name`, `image_url`)
- **Сферы применения → категории/серии** → `spheres` (наблюдаемые поля: `name`, `category_name`, `category_url`)
- **Описания серий** → `series`

If data is in unrelated tables and no FK relationship is set, do **two queries**.

## 2) Decide: simple select vs JOIN vs FTS
### 2.1 Simple select
Use when all needed fields are in one table.

### 2.2 JOIN (Supabase/PostgREST)
Use when you need fields from related tables **and** PostgREST knows the relationship.
Rules:
- Include the **primary key** of the main table in `select`.
- Select only needed fields from joined tables.
- Apply filters at the lowest level possible (`joined_table.field=eq...`).

JOIN syntax:
- **LEFT (default)** nested: `main?select=id,name,child(field1,field2)`
- **INNER**: `main?select=id,name,child:child_table!inner(field1,field2)`

Typical joins (only if the relationship exists in PostgREST schema cache):
- `catalog_lamps.id -> etm_oracl_catalog_sku.catalog_lamps_id` (works)
- `catalog_lamps.category_id -> categories.id` (may be missing; if you get `PGRST200`, switch to a 2-step query or filter via `catalog_lamps.category_name` instead of joining to `categories`).

### 2.3 Multi-step lookups (when JOIN is not available)
Use when tables are related logically, but REST relationship embedding is not available.
Common pattern “проекты/светильники по сфере применения”:
1) Start from `portfolio.sphere_name` (text value).
2) Find related categories via `spheres`:
   - filter `spheres.name` (eq/fts) → take `category_name` values.
3) Then query `catalog_lamps` using **text category** (fast and avoids join):
   - `catalog_lamps?select=id,name,series,category_name,url&category_name=in.(...names...)&limit=5&offset=0`

If you must go through `categories`:
- `categories?select=id,name&name=in.(...names...)&limit=...&offset=...`
- then `catalog_lamps?select=...&category_id=in.(...ids...)&limit=...&offset=...`

### 2.3 Full-text search (FTS) in Russian
Use RPC `ru_fts()` when exact match is unlikely (category/description/name fragments), especially for:
- `portfolio.group_name`
- `portfolio.name`
- `portfolio.sphere_name`
- `spheres.name`
- `spheres.category_name`
- `catalog_lamps.name`
- `series.description/features/specification` (if present)

If `ru_fts` returns “column does not exist”, first introspect the table with a tiny request like:
- `GET /<table>?select=*&limit=1&offset=0`
then retry with the correct column name.

RPC endpoint:
- `GET /rpc/ru_fts?p_table_name=...&p_search_column=...&p_search_query=...`

Always set:
- `p_select_columns` (don’t use `*` unless necessary)
- `p_limit_rows` and `p_offset_rows`
- `p_order_by` (URL-encoded spaces: `name%20ASC`)

## 3) Always paginate & don’t overload limit
- Always include `limit` and `offset`.
- Default: `limit=5&offset=0` unless user needs more.

## 4) Build request quickly (use bundled scripts)
Prefer these scripts to avoid mistakes:
- `scripts/supabase_get.sh` — generic GET for table endpoints. **Params must already be URL-safe** (no spaces). Best for numeric filters and simple values.
- `scripts/supabase_fts.sh` — rpc/ru_fts wrapper (proper encoding).
- `scripts/supabase_query.py` — builds a correct URL with encoding per key/value; use it when filters contain spaces/Cyrillic or complex strings.

## 5) Scenario playbooks (recommended)

### 1) Поиск характеристик/документов по ТОЧНОМУ имени светильника
- Table: `catalog_lamps`
- Filter: `name=eq.<точное имя>`
- Fields: тех.характеристики + ссылки на документы
- Script:
  - `scripts/lad_supabase_cli.py lamp exact --name "..." --limit 1 --offset 0`

### 2) Поиск характеристик/документов по НЕТОЧНОМУ имени светильника (с подбором вариантов)
- Step A (suggest): `rpc/ru_fts` по `catalog_lamps.name` → вернуть 5–10 кандидатов (id+name+url)
- Step B (user chooses): запросить карточку светильника по выбранному кандидату
- Scripts:
  - suggest (список): `scripts/lad_supabase_cli.py lamp suggest --query "..." --limit 5 --offset 0`
  - interactive pick (покажет варианты и спросит номер):
    - `scripts/lad_supabase_cli.py lamp pick --query "..." --limit 10`
  - non-interactive pick (для автоматизации):
    - `scripts/lad_supabase_cli.py lamp pick --query "..." --limit 10 --index 0`
  - include SKU in picked details:
    - `scripts/lad_supabase_cli.py lamp pick --query "..." --limit 10 --index 0 --with-sku`
  - direct by id: `scripts/lad_supabase_cli.py lamp by-id --id 1343 --limit 1 --offset 0`

### 3) Взаимный поиск по названию светильника, коду ETM или коду ORACL
- If user provides code:
  - Table: `etm_oracl_catalog_sku` filter by `etm_code` or `oracl_code` → get `catalog_lamps_id`
  - Then 2-step fetch `catalog_lamps?id=in.(...)` (do not rely on relationships)
- If user provides name:
  - Use `catalog_lamps` + embedded `etm_oracl_catalog_sku(...)` (known to work)
- Scripts:
  - `scripts/lad_supabase_cli.py sku by-code --etm "..."`
  - `scripts/lad_supabase_cli.py sku by-code --oracl "..."`
  - `scripts/lad_supabase_cli.py sku guess "<value>"` (tries ETM → ORACL → exact name → fuzzy candidates)

### 4) Поиск реализованных объектов в конкретной сфере применения
- Table: `portfolio`
- Filter: `sphere_name=eq...` (or FTS if user input is fuzzy)
- Script:
  - exact: `scripts/lad_supabase_cli.py portfolio by-sphere --sphere "..." --limit 5 --offset 0`
  - fuzzy: `scripts/lad_supabase_cli.py portfolio by-sphere --sphere "..." --fuzzy --limit 5 --offset 0`

### 5) Поиск категорий светильников, подходящих для сферы применения
- Step: filter `spheres.name` (eq/fts) → return distinct `category_name` (and `category_url`)
- Optional: map to `categories` by `categories.name=in.(...)` if you need ids
- Script:
  - `scripts/lad_supabase_cli.py sphere categories --sphere "..." --limit 50 --offset 0`

### 7) Поиск светильников, подходящих для сферы применения
- Step A: sphere → category_name(s) via `spheres`
- Step B: `catalog_lamps` filter by `category_name in (...)` (text)
- Script:
  - `scripts/lad_supabase_cli.py sphere lamps --sphere "..." --limit 5 --offset 0`

### 6) Поиск примеров реализации из портфолио для заданной категории светильника
- Step A: map category → sphere(s) via `spheres.category_name` (eq/fts)
- Step B: query `portfolio` where `sphere_name in (...)`
- Script:
  - `scripts/lad_supabase_cli.py category portfolio --category "..." --limit 5 --offset 0`

### 8) Поиск светильников по заданной категории (и/или подбор категории)
- Exact category: filter `catalog_lamps.category_name=eq...`
- Fuzzy category: `ru_fts` по `catalog_lamps.category_name` (полезно если пользователь пишет «линия оз» и т.п.)
- Script:
  - exact: `scripts/lad_supabase_cli.py category lamps --category "..." --limit 5 --offset 0`
  - fuzzy: `scripts/lad_supabase_cli.py category lamps --category "..." --fuzzy --limit 5 --offset 0`

## 6) Output standard (user-facing)
When answering a user request, output **only the user-ready answer**.

### Never include in normal replies
- which table(s) were queried
- REST URL(s)
- curl commands
- raw PostgREST filters / query strings
- pagination/join/FTS implementation details
- internal reasoning or step-by-step query plans

### What to include
- A clear, compact answer in plain Russian.
- If you return a list: show top results with the minimum useful fields (e.g., name, short description, key specs, code/article, link), formatted as bullets.
- If uncertainty exists (multiple matches): ask 1 concise clarifying question and offer 3–5 best candidates.

### Exception (on explicit request)
Only if the user explicitly asks “покажи запрос/URL/curl/из какой таблицы”, you may provide the technical details in a separate block.

## References
Read these when you need exact schemas / join details / examples:
- `references/schema-and-guidelines.md`
- `references/join-operations.md`
- `references/rest-api-examples.md`
