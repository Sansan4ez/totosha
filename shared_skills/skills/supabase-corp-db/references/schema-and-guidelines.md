# Schema & querying guidelines (corporate Supabase)

Source: `skills/supabase-api-search/supabase_guide.md`

Important: the reference below may drift from the live Supabase schema. When a query fails with “column does not exist” or “no relationship found”, first introspect with:
- `GET /<table>?select=*&limit=1&offset=0`

Observed drift examples (live API):
- `portfolio` uses `image_url`, `group_name`, `sphere_name` (not `image`/`category_name`).
- `spheres` uses `name`, `category_name`, `category_url` (not `sphere_name`/`series_name`).
- `catalog_lamps -> categories` relationship may be missing in PostgREST schema cache (embedding/join can fail with `PGRST200`).

---

# Instructions
1. Выполни анализ вопроса пользователя с учетом структуры таблиц и Guidelines в базе данных 'Supabase'.
2. Определи название таблиц, содержащих требуемые для ответа данные.
3. Проанализируй, требуется ли объединение таблиц (JOIN) для получения всех необходимых данных:
   - Используй JOIN, если данные находятся в разных связанных таблицах (например, `catalog_lamps` и `etm_oracl_catalog_sku`, `categories` и `catalog_lamps`)
   - Для API запросов используй вложенную нотацию со скобками для LEFT JOIN или явную нотацию с `!inner=` для INNER JOIN
   - Включай первичный ключ основной таблицы в SELECT-выражение
   - Применяй фильтрацию на самом низком уровне
4. Определи нужно ли использовать полнотекстовый поиск (FTS): используй полнотекстовый поиск (FTS) с помощью функции `ru_fts()` для текстовых полей, если точное совпадение маловероятно (например, в таблице `portfolio` для `category_name` или `description`).
5. Определи какие столбцы нужно выбрать из таблиц, фильтры, порядок вывода, лимиты и пагинацию. Обязательно выбирай столбцы по которым делаешь фильтрацию или поиск. Проверь их наличие и соответствие примеру в используемой таблице согласно 'Структуры таблиц'
6. Напиши запрос по API к базе данных 'Supabase', чтобы получить данные для ответа на вопрос пользователя. Обязательно используй `limit` и `offset` parameters. Don't overload `limit`.

## Informaition about Supabase database
<Структура таблиц>
### categories (категории)
```sql
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,                        -- ID категории из API сайта
    name TEXT NOT NULL,                            -- Название категории
    url TEXT,                                      -- Ссылка на категорию
    image TEXT,                                    -- Ссылка на изображение категории
    parent_id INTEGER,                             -- ID родительской категории (для иерархии)
    display_order INTEGER,                         -- Порядок отображения
    is_active BOOLEAN DEFAULT TRUE,                -- Статус активности категории

    -- Метаданные
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Внешний ключ для иерархии категорий
    CONSTRAINT fk_parent_category FOREIGN KEY (parent_id) REFERENCES categories (id) ON DELETE SET NULL
);
```

### catalog_lamps (каталог светильников)
-- Important: there are no field `description` in this table!
```sql
CREATE TABLE IF NOT EXISTS catalog_lamps (
    id BIGINT PRIMARY KEY,                        -- ID из API сайта
    name TEXT NOT NULL UNIQUE,
    url TEXT,
    series TEXT,
    category_id INTEGER,
    category_name TEXT,
    low_voltage TEXT,                              -- Маркировка низковольтных
    explosion_protection TEXT,                     -- Маркировка взрывозащиты

    -- Документация
    booklet_url TEXT,
    drawing_url TEXT,
    passport_url TEXT,
    certificate_url TEXT,
    ies_url TEXT,
    file_package_url TEXT,
    image_url TEXT,
    diffuser_url TEXT,

    -- Технические характеристики
    luminous_flux_lm INTEGER,                      -- Световой поток (люмен)
    beam_angle TEXT,                               -- Угол рассеивания
    power_consumption_w INTEGER,                   -- Потребляемая мощность (Вт)
    color_temperature_k INTEGER,                   -- Цветовая температура (К)
    color_rendering_index INTEGER,                 -- Индекс цветопередачи
    power_factor NUMERIC(3,2),                     -- Коэффициент мощности
    climatic_execution_type TEXT,                  -- Климатическое исполнение
    operating_temperature_range TEXT,              -- Диапазон рабочих температур
    dust_and_water_protection_class TEXT,          -- Класс пылевлагозащиты (IP)
    electric_shock_protection_class TEXT,          -- Класс защиты от поражения эл. током
    nominal_voltage_v TEXT,                        -- Номинальное напряжение
    mounting_type TEXT,                            -- Тип монтажа
    dimensions_mm TEXT,                            -- Габаритные размеры (мм)
    weight_kg NUMERIC(5,2),                        -- Вес (кг)
    warranty_period_years INTEGER,                 -- Гарантийный срок (лет)

    -- Метаданные синхронизации
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Внешний ключ для связи с категориями
    CONSTRAINT fk_category
        FOREIGN KEY (category_id)
        REFERENCES categories (id)
        ON DELETE SET NULL
);
```
### etm_oracl_catalog_sku (Product SKU mapping table)
```sql
CREATE TABLE etm_oracl_catalog_sku (
    id BIGSERIAL PRIMARY KEY,
    catalog_lamps_id INTEGER NOT NULL UNIQUE,
    etm_code VARCHAR(50),
    oracl_code VARCHAR(50),
    short_box_name_wms VARCHAR(50),
    catalog_1c VARCHAR(50),
    box_name VARCHAR(200),
    description TEXT,
    comments TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    archived_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT fk_catalog_lamps_id
        FOREIGN KEY (catalog_lamps_id)
        REFERENCES catalog_lamps(id)
);
```
#### Пример данных `etm_oracl_catalog_sku':
```
{
    "catalog_lamps_id": 1343,
    "etm_code": "LINE1132",
    "oracl_code": "1669705",
    "short_box_name_wms": "LADLEDL1015B",
    "catalog_1c": "15Лайн-10 черный",
    "box_name": "ДБП-15w IP66 1751Лм 5000К 10° BLACK",
    "description": "Светильник светодиодный LAD LED LINE-10-15B 15Вт 5000К IP66 230В КСС типа \"К\" цвет корпуса черный LADesign LADLEDL1015B",
    "comments": "1750706",
    "is_active": 1,
    "archived_at": null,
    "created_at": "2025-01-26 23:14:47",
    "updated_at": "2025-01-26 23:14:47"
  }
```
### etm_oracl_archive (архив кодов)
```sql
CREATE TABLE IF NOT EXISTS etm_oracl_archive (
    id BIGSERIAL PRIMARY KEY,
    etm_code VARCHAR(50),
    oracl_code VARCHAR(50),
    catalog_lamps_name VARCHAR(100) NOT NULL,
    short_box_name_wms VARCHAR(50),
    catalog_1c VARCHAR(50),
    box_name VARCHAR(200),
    description TEXT,
    comments TEXT,
    archive_reason VARCHAR(20) CHECK (archive_reason IN ('obsolete', 'special_series', 'discontinued')),
    archived_at TIMESTAMP WITH TIME ZONE NOT NULL,
    original_created_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```
### portfolio (реализованные проекты)
```sql
CREATE TABLE IF NOT EXISTS portfolio (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    image TEXT NOT NULL,
    category_name TEXT NOT NULL
);
```
#### Пример данных `portfolio` table:
```
{
    "id": 1,
    "name": "Обустройство социально-бытовых объектов ПАО «ГМК «Норильский никель»",
    "url": "http://ladzavod.web.prime-gr.ru/portfolio/proizvodstvennye-ploshchadki-i-akb/obustrojstvo-socialno-bytovyh-obektov-pao-gmk-norilskij-nikel",
    "image": "http://ladzavod.web.prime-gr.ru/storage/app/uploads/public/67a/176/c15/67a176c15ff9b479708059.png",
    "category_name": "Производственные площадки и АКБ"
}
```
### spheres (связь сфер применения и серий)
```sql
CREATE TABLE IF NOT EXISTS spheres (
    id BIGSERIAL PRIMARY KEY,                    -- Уникальный идентификатор
    sphere_name TEXT NOT NULL,                   -- Название сферы применения
    sphere_url TEXT,                             -- Ссылка на сферу
    series_name TEXT NOT NULL,                   -- Название серии/категории
    series_url TEXT,                             -- Ссылка на серию/категорию
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```
### series (серии светильников)
```sql
CREATE TABLE IF NOT EXISTS series (
    id BIGSERIAL PRIMARY KEY,                        -- Уникальный идентификатор серии
    series_name TEXT NOT NULL,                       -- Название серии
    description TEXT,                                -- Описание серии
    features TEXT,                                   -- Особенности/ключевые преимущества
    specification TEXT,                              -- Технические характеристики/спецификация

    -- Метаданные
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```
<End Структура таблиц>

## Basic Query Structure
```sql
-- Corresponding SQL for the REST API query
select
  id,
  name,
  passport_url,
  power_consumption_w
from
  catalog_lamps
where
  power_consumption_w >= 25
and
  power_consumption_w <= 40
order by
  name asc
limit 5
offset 0;
```
### Query Parameters Explanation
- `select`: Specifies the columns to return
- `power_consumption_w`: Filter conditions using operators (gte, lte, eq, etc.)
- `order`: Sorting criteria (asc/desc)
- `limit`: Maximum number of records to return, must always be less than 5.
- `offset`: Number of records to skip