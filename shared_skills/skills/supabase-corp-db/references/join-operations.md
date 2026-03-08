# JOIN operations (Supabase/PostgREST)

Source: `skills/supabase-api-search/supabase_join_operations.md`

---

## JOIN Operations in Supabase

### Принципы работы с JOIN в Supabase

При объединении таблиц в запросах к Supabase API необходимо следовать этим принципам:

1. **Когда использовать JOIN**
   - При необходимости получения данных из нескольких связанных таблиц
   - Когда требуется объединить информацию по ключевым полям (например, `catalog_lamps.id` и `etm_oracl_catalog_sku.catalog_lamps_id`)
   - Для получения дополнительной информации из родительских/дочерних таблиц (например, категории для светильников)
   - если есть внешний ключ или связь между таблицами НЕ настроены потребуется INNER JOIN с явным указанием условия.
   - если таблицы не связаны, следует использовать две отдельные операции для получения данных.
    Пример:
      1) Получить список специальных светильников из catalog_lamps с фильтрацией по необходимым полям.
      2) Отдельно запросить информацию о сферах применения из таблицы spheres.

2. **Типы JOIN и их синтаксис в API**
   - **LEFT JOIN (по умолчанию)** - используйте вложенную нотацию со скобками:
     ```
     table1?select=id,name,table2(field1,field2)
     ```
   - **INNER JOIN** - используйте нотацию с `!inner`:
     ```
     table1?select=id,name,alias:table2!inner(field1,field2)
     ```

3. **Оптимизация JOIN-запросов**
   - Всегда включайте первичный ключ основной таблицы в SELECT-выражение
   - Выбирайте только нужные поля из связанных таблиц
   - Применяйте фильтры к нужной таблице напрямую: `table1?select=...&table2.field=eq.value`
   - Используйте алиасы для улучшения читаемости в SQL-запросах

4. **Специфика для основных связей в базе данных**
   - `catalog_lamps ↔ categories`: связь по `catalog_lamps.category_id = categories.id`
   - `catalog_lamps ↔ etm_oracl_catalog_sku`: связь по `catalog_lamps.id = etm_oracl_catalog_sku.catalog_lamps_id`
   - `categories ↔ categories`: самосвязь для иерархии по `categories.parent_id = categories.id`

### JOIN Syntax for SQL Queries
```sql
-- Basic JOIN example with catalog_lamps and categories
select
  cl.id,
  cl.name,
  cl.power_consumption_w,
  cat.name as category_name,
  cat.url as category_url
from
  catalog_lamps cl
join
  categories cat on cl.category_id = cat.id
where
  cl.power_consumption_w >= 25
and
  cl.power_consumption_w <= 40
order by
  cl.name asc
limit 5
offset 0;

-- JOIN example with catalog_lamps and etm_oracl_catalog_sku
select
  cl.id,
  cl.name,
  cl.power_consumption_w,
  sku.etm_code,
  sku.oracl_code,
  sku.description
from
  catalog_lamps cl
join
  etm_oracl_catalog_sku sku on cl.id = sku.catalog_lamps_id
where
  cl.power_consumption_w >= 25
and
  cl.power_consumption_w <= 40
order by
  cl.name asc
limit 5
offset 0;
```

### JOIN Syntax in REST API Calls
Supabase API provides two methods for joining tables:

#### 1. Nested Object Notation
Use parentheses to specify the foreign table and fields to include:
```bash
curl -X GET "https://api.llm-studio.pro/rest/v1/catalog_lamps?select=id,name,power_consumption_w,etm_oracl_catalog_sku(etm_code,oracl_code,description)&power_consumption_w=gte.25&power_consumption_w=lte.40&order=name.asc&limit=5&offset=0"
```

#### 2. Explicit JOIN Notation
Use the `!inner=` parameter to explicitly join tables:
```bash
curl -X GET "https://api.llm-studio.pro/rest/v1/catalog_lamps?select=id,name,power_consumption_w,sku:etm_oracl_catalog_sku!inner(etm_code,oracl_code,description)&etm_oracl_catalog_sku.catalog_lamps_id=eq.catalog_lamps.id&power_consumption_w=gte.25&power_consumption_w=lte.40&order=name.asc&limit=5&offset=0"
```

### JOIN Types Examples

#### LEFT JOIN (Default)
Includes all records from the left table, even if there are no matches in the right table:
```bash
curl -X GET "https://api.llm-studio.pro/rest/v1/catalog_lamps?select=id,name,etm_oracl_catalog_sku(etm_code,oracl_code)&limit=5&offset=0"
```

#### INNER JOIN
Only includes records where there is a match in both tables:
```bash
curl -X GET "https://api.llm-studio.pro/rest/v1/catalog_lamps?select=id,name,sku:etm_oracl_catalog_sku!inner(etm_code,oracl_code)&limit=5&offset=0"
```

### Complex JOIN Example with Filtering
```bash
# Get catalog lamps with their SKU information, filtered by power consumption and with active SKUs only
curl -X GET "https://api.llm-studio.pro/rest/v1/catalog_lamps?select=id,name,power_consumption_w,etm_oracl_catalog_sku(etm_code,oracl_code,description,is_active)&power_consumption_w=gte.25&power_consumption_w=lte.40&etm_oracl_catalog_sku.is_active=eq.true&order=name.asc&limit=5&offset=0"
```

### Best Practices for JOINs
1. Use table aliases for readability in SQL queries
2. Specify only the columns you need to reduce payload size
3. Use appropriate join types based on data requirements
4. When filtering on joined tables, apply the filter at the lowest level possible
5. For complex multi-table queries, consider using explicit JOINs with aliases
6. Always include the primary key of the main table in the SELECT clause
7. Use consistent naming conventions for foreign key columns
8. Always include pagination (`limit` and `offset`) for large result sets
