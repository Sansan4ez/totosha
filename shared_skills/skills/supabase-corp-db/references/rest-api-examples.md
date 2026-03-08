# REST API examples (curl)

Source: `skills/supabase-api-search/supabase_rest_api_examples.md`

---

## REST API Examples

### Catalog Lamps Example
```bash
curl -X GET "https://api.llm-studio.pro/rest/v1/catalog_lamps?select=id,name,passport_url,power_consumption_w&power_consumption_w=gte.25&power_consumption_w=lte.40&order=name.asc&limit=5&offset=0"
```
### Simple Queries
```bash
# Get all active employees
curl -X GET "https://api.llm-studio.pro/rest/v1/employees?select=*&end_date=is.null&limit=5&offset=0"

### Complex Query with Filters
```bash
# Get employees within date range and status
curl -X GET "https://api.llm-studio.pro/rest/v1/employees?select=first_name,last_name&start_date=gte.2021-01-01&start_date=lte.2021-12-31&status=eq.employed&limit=5&offset=0"
```

### Join Query
```bash
# Get employees with their department names
curl -X GET "https://api.llm-studio.pro/rest/v1/employees?select=employee_name,departments(department_name)&start_date=gt.2022-01-01&limit=5&offset=0"
```

### Aggregation Query
```bash
# Count active employees
curl -X GET "https://api.llm-studio.pro/rest/v1/employees?select=count&end_date=is.null&limit=5&offset=0"
```

### Complex Query with Nested Data
```bash
# Get department statistics with employee counts
curl -X GET "https://api.llm-studio.pro/rest/v1/departments?select=department_name,employees(count)&limit=5&offset=0"
```

### Full-Text Search (FTS) Example (Russian) - use 'ru_fts()' function!
```
ru_fts(
    p_table_name TEXT,                  -- Название таблицы
    p_search_column TEXT,               -- Колонка для текстового поиска
    p_search_query TEXT,                -- Поисковый запрос
    p_select_columns TEXT DEFAULT '*',  -- Колонки для SELECT (по умолчанию *)
    p_order_by TEXT DEFAULT NULL,       -- Сортировка (без "ORDER BY")
    p_limit_rows INT DEFAULT 5,         -- Лимит результатов
    p_offset_rows INT DEFAULT 0         -- Смещение для пагинации
)
```
```bash
# Базовый поиск по категории в portfolio
curl 'https://api.llm-studio.pro/rest/v1/rpc/ru_fts?p_table_name=portfolio&p_search_column=category_name&p_search_query=нефтегазовый%20комплекс'

# Выбор определенных колонок с сортировкой
curl 'https://api.llm-studio.pro/rest/v1/rpc/ru_fts?p_table_name=portfolio&p_search_column=category_name&p_search_query=взрывозащищенное%20оборудование&p_select_columns=id,name,url,image&p_order_by=name%20DESC&p_limit_rows=5&p_offset_rows=0'

# Поиск по другим таблицам (например, catalog_lamps)
curl 'https://api.llm-studio.pro/rest/v1/rpc/ru_fts?p_table_name=catalog_lamps&p_search_column=name&p_search_query=LED%20LINE-O-60B&p_select_columns=id,name,power_consumption_w'
```

## Best Practices
1. Use clear parameter names that reflect the data being queried
2. Include appropriate authentication headers
3. Specify Content-Type header for JSON responses
4. Use proper operators for filtering (gte, lte, eq, neq, etc.)
5. For text searches where exact matches are not guaranteed, use full-text search with `ru_fts()` function. Уou must use space-encoded notation `name%20ASC` for the `p_order_by` parameter format.
6. Implement pagination using `limit` and `offset` parameters. Don't overload `limit`.

<End Guidelines for writing Postgres SQL and API queries>
Domain: 'https://api.llm-studio.pro'
