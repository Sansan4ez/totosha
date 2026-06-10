RFC: Shared Skill `corp-pg-db` для корпоративных данных (Postgres + Hybrid Search)
===============================================================================

Status
------

Proposed

Date
----

2026-03-23

Context and motivation
----------------------

Сейчас доступ к корпоративным данным каталога реализован через tool `corp_db_search` и тонкий клиент в [core/tools/corp_db.py](/home/admin/totosha.feature-db/core/tools/corp_db.py), который проксирует запросы в `tools-api` и далее в Supabase/PostgREST. Это:

- усложняет инфраструктуру (внешняя Supabase, ключи, PostgREST RPC);
- не совпадает с целевой моделью “корпоративные источники внутри периметра”;
- слабо расширяемо под гибридный поиск и фильтрацию по параметрам светильников.

Цель этого RFC: добавить в проект новый **shared skill** (доступный как `/data/skills/...` в sandbox), который даёт агенту ясные инструкции и стабильный allowlisted tool/API-интерфейс для поиска/фильтрации по корпоративной базе данных на **PostgreSQL**, наполненной данными из JSON-источников и выбранного подмножества корпоративной wiki.

Goals
-----

- Добавить shared skill `corp-pg-db` (kebab-case) с:
  - инструкциями для агента, когда использовать `corp_db_search`;
  - примерами запросов и правил маршрутизации между `corp_db` и `corp_wiki`.
- Добавить операторский пайплайн в `db/` для инициализации, сидирования и переиндексации новой Postgres БД.
- Развернуть PostgreSQL (pgvector + pg_trgm + FTS) с данными:
  - каноническими нормализованными таблицами, загружаемыми из JSON-источников в [/home/admin/totosha.feature-db/db](/home/admin/totosha.feature-db/db);
  - 1 таблица по Markdown из корпоративной wiki в [shared_skills/skills/corp-wiki-md-search/wiki](/home/admin/totosha.feature-db/shared_skills/skills/corp-wiki-md-search/wiki), но только для файлов, включённых в manifest продвижения в БД.
- Реализовать **гибридный поиск** (FTS + pgvector + trigram + RRF) по основным полям/таблицам в соответствии с [/home/admin/totosha.feature-db/docs/kb-hybrid-search.md](/home/admin/totosha.feature-db/docs/kb-hybrid-search.md).
- Поддержать фильтрацию по “основным полям” и параметрам светильников (поток, мощность, CCT, IP и т.д.) с предсказуемыми правилами нормализации.
- Предусмотреть тесты и моки (включая мок эмбеддингов).
- Сохранить совместную работу `corp-wiki-md-search` и `corp_db_search`: wiki остаётся полным файловым корпусом, а БД получает структурированные данные и promoted subset KB.

Non-goals for first implementation (v1)
---------------------------------------

- Запись/изменение корпоративных данных пользователем (только read-only).
- Поддержка произвольных SQL-запросов из CLI/skill (исключено по security).
- Интеграция в Admin UI и любые публичные эндпоинты наружу.
- 100% покрытие всех полей/атрибутов из JSON; в v1 нормализуются только ключевые параметры для фильтров.

Implementation considerations
-----------------------------

- **Security (0 secrets в агенте/песочнице):**
  - sandbox/agent не получает DB credentials;
  - доступ к эмбеддингам осуществляется через `proxy` (`http://proxy:3200/v1/embeddings`), ключи остаются в контейнере proxy (как сейчас для `/v1/*`).
  - публичный runtime-путь к корп. БД проходит только через allowlisted tool/API (`corp_db_search` -> `tools-api` -> Postgres); не через shell/CLI;
  - любые запросы ограничены allowlist’ом операций и лимитами (limit/offset/clamp);
  - в публичном режиме при недоступном sandbox shell-выполнение должно fail-closed, без local fallback для доступа к `/data` или БД.
- **Determinism и воспроизводимость:**
  - схема и индексы описываются одним каноническим SQL-источником;
  - сидирование из исходников (JSON/wiki Markdown) должно быть идемпотентным и поддерживать incremental.
- **Hybrid search:**
  - как в [db/init.sql](/home/admin/totosha.feature-db/db/init.sql): `vector(1536)`, `hnsw`, `tsvector` + GIN, `pg_trgm` + GIN, и RRF-фьюжн.
- **Operational simplicity:**
  - одна команда для оператора: “init + seed + reindex”;
  - для агента один стабильный runtime-контракт: `corp_db_search`.

Agreed architectural decisions
------------------------------

- Единственный источник истины для схемы Postgres и SQL-функций: [db/init.sql](/home/admin/totosha.feature-db/db/init.sql).
- Канонический нормализатор каталога: [db/transform_catalog_json.py](/home/admin/totosha.feature-db/db/transform_catalog_json.py). Новые сидеры используют его, а не дублируют parsing/normalization-логику.
- Shared skill `corp-pg-db` хранит только инструкции и примеры использования. SQL, operator scripts и логика сидирования живут в `db/`.
- Канонический источник Markdown-контента: [shared_skills/skills/corp-wiki-md-search/wiki](/home/admin/totosha.feature-db/shared_skills/skills/corp-wiki-md-search/wiki). БД ingest-ит только выбранное подмножество этих файлов по manifest.
- `docs/knowledge_base` не является отдельным источником истины. Если каталог сохраняется, он должен быть только generated mirror из wiki и не редактироваться вручную.
- В публичном режиме runtime-доступ к корп. БД идёт только через `corp_db_search`; прямой SQL и shell-доступ к БД для агента исключены.

High-level behavior
-------------------

1. Оператор поднимает `postgres` контейнер (pgvector) с базовой схемой и расширениями (на базе [db/Dockerfile](/home/admin/totosha.feature-db/db/Dockerfile) и [db/init.sql](/home/admin/totosha.feature-db/db/init.sql)).
2. Операторский worker загружает JSON-источники и promoted subset корпоративной wiki в нормализованные таблицы (v1: full reset и incremental по hash).
3. Скрипт индексации строит “поисковый слой” (см. раздел Data model и Hybrid search).
4. Во время диалога агент:
  - загружает инструкцию skill `corp-pg-db` (через `/data/skills/...`);
  - по правилам маршрутизации выбирает `corp_db_search` и/или `corp-wiki-md-search`;
  - отвечает пользователю, основываясь только на результатах.

Domain-specific sections
------------------------

Skill packaging (shared skill)
------------------------------

Новый skill размещается в репозитории: `shared_skills/skills/corp-pg-db/` и синхронизируется в `workspace/_shared/skills` через [shared_skills/sync-skills.sh](/home/admin/totosha.feature-db/shared_skills/sync-skills.sh), после чего доступен в контейнерах как `/data/skills/corp-pg-db`.

Предлагаемая структура:

```text
shared_skills/skills/corp-pg-db/
  skill.json
  SKILL.md
  examples.md                # optional examples / troubleshooting
```

Примечание:

- skill содержит только инструкции для агента и не является источником истины для SQL или operator tooling;
- SQL, manifest и operator scripts находятся в `db/`;
- публичный runtime-путь поиска идёт через встроенный tool `corp_db_search`, а не через shell-команды в песочнице;
- operator команды выполняются в отдельном `corp-db-worker`, а не в sandbox и не через `tools-api`.

PostgreSQL: schema and tables
-----------------------------

### Роли и подключение (security boundary)

Рекомендуемая модель доступа:

- `corp_rw` (writer): используется только `corp-db-worker` (operator-only).
- `corp_ro` (read-only): используется только `tools-api` рантайм-эндпоинтами поиска/фильтрации.

DSN передаются сервисам через Docker secrets:

- `CORP_DB_RW_DSN` (secret) доступен только `corp-db-worker`.
- `CORP_DB_RO_DSN` (secret) доступен только `tools-api`, который реализует allowlisted запросы.

Права доступа:

- `corp_ro` получает только `SELECT` по allowlisted VIEW/MATERIALIZED VIEW и `EXECUTE` по allowlisted search/functions;
- `corp_ro` не получает `INSERT/UPDATE/DELETE/DDL`;
- sandbox и agent не получают DSN и не подключаются к Postgres напрямую;
- в публичном режиме отсутствие sandbox не должно приводить к local shell fallback для доступа к корп. данным.

Postgres не публикуется наружу и доступен только по внутренней docker-сети.

### Канонические таблицы из JSON-источников

Источник: файлы в [/home/admin/totosha.feature-db/db](/home/admin/totosha.feature-db/db)

Принцип v1: число таблиц не обязано совпадать с числом файлов. Если исходник содержит вложенные сущности, они раскладываются в отдельные реляционные таблицы.

1. `categories` ← `db/categories.json` (`categories[]`)
   - колонки: `id`, `name`, `url`, `image_url`
   - поля `parent` и `powerDescription` из JSON в v1 не нормализуются и не индексируются
2. `catalog_lamps` ← `db/catalog.json` (`products[]`)
   - основная wide-таблица для фильтрации и сортировки
   - содержит только `category_id`, без дублирования `category_name`
3. `catalog_lamp_documents` ← `db/catalog.json` (`products[].docs`)
   - `1:1` таблица документов по лампе
   - фиксированные колонки: `instruction_url`, `blueprint_url`, `passport_url`, `certificate_url`, `ies_url`, `diffuser_url`, `complete_docs_url`
4. `catalog_lamp_properties_raw` ← `db/catalog.json` (`products[].properties[]`)
   - raw-источник правды по свойствам лампы
   - колонки: `lamp_id`, `property_code`, `property_name_ru`, `property_value_raw`, `property_measure_raw`
5. `etm_oracl_catalog_sku` ← `db/etm_oracl_catalog_sku.json` (array)
   - во внутренней схеме FK унифицируется как `lamp_id`, хотя в JSON поле называется `catalog_lamps_id`
6. `category_mountings` ← `db/lamp_mountings.json` (`lampMountings[]`)
   - имя исходного файла остаётся историческим, но нормализованная таблица названа по фактической семантике: совместимость `category_id` / `series` с `mounting_type_id`
7. `mounting_types` ← `db/mounting_types.json` (`mountingTypes[]`)
8. `portfolio` ← `db/portfolio.json` (`portfolio[]`)
9. `spheres` ← `db/spheres.json` (`spheres[]`)
10. `sphere_categories` ← `db/spheres.json` (`spheres[].categoriesId[]`)
   - связывающая таблица `sphere_id -> category_id`

### 1 таблица из Markdown KB

11. `knowledge_chunks` ← chunking файлов из корпоративной wiki [shared_skills/skills/corp-wiki-md-search/wiki](/home/admin/totosha.feature-db/shared_skills/skills/corp-wiki-md-search/wiki), включённых в manifest `db/knowledge_base_manifest.yaml`, по правилам из [/home/admin/totosha.feature-db/docs/kb-hybrid-search.md](/home/admin/totosha.feature-db/docs/kb-hybrid-search.md) (chunking по `###`, игнор текста до первой `###`, пустые chunk’и пропускать).

### Канонический нормализатор JSON

- [db/transform_catalog_json.py](/home/admin/totosha.feature-db/db/transform_catalog_json.py) является каноническим нормализатором `catalog.json`.
- Любые новые сидеры/worker scripts используют этот модуль напрямую или вызывают его как подкоманду, а не дублируют parsing/normalization rules.
- `db/normalized_catalog/*.jsonl` считаются производными артефактами / fixtures и не являются источником истины.

### Где лежат исходники JSON/wiki в runtime

В локальной разработке канонические источники лежат в репозитории:

- структурированные JSON: `db/*.json`;
- Markdown wiki: `shared_skills/skills/corp-wiki-md-search/wiki/*.md`.

Каталог `docs/knowledge_base` не является отдельным источником истины. Если он сохраняется, то только как generated mirror из wiki без ручного редактирования.

Принятое решение для production:

- хранить актуальные JSON дампы в `workspace/_shared/corp_pg_db/sources/` (в контейнерах: `/data/corp_pg_db/sources/`);
- хранить канонические wiki Markdown в shared skill `corp-wiki-md-search`, который доступен в контейнерах как `/data/skills/corp-wiki-md-search/wiki/`;
- выбирать, какие wiki-файлы ingest-ятся в БД, через manifest `db/knowledge_base_manifest.yaml`, поставляемый вместе с worker image;
- не заводить отдельный `/data/corp_pg_db/knowledge_base/` в v1, чтобы не создавать второй источник истины.

Файлы wiki, включённые в manifest для ingest в БД:

- обязаны содержать ровно один корректный `# H1`, который сохраняется как `document_title`;
- chunk-ятся по `###`;
- могут продолжать одновременно использоваться и в `corp-wiki-md-search`, и в БД.

Во всех операторских скриптах предусмотреть флаги:

- `--sources-dir` (локально по умолчанию `./db`, в контейнере `/data/corp_pg_db/sources`);
- `--wiki-dir` (локально по умолчанию `./shared_skills/skills/corp-wiki-md-search/wiki`, в контейнере `/data/skills/corp-wiki-md-search/wiki`);
- `--kb-manifest` (по умолчанию `./db/knowledge_base_manifest.yaml` в dev / образе worker).

### Нормализация параметров светильников (filter fields)

В `catalog_lamps` v1 выделяются отдельные типизированные колонки (для фильтрации/сортировки), нормализуемые из `products[].properties[]`:

- `lamp_id bigint primary key`
- `category_id bigint not null references categories(id)`
- `name text`
- `url text unique`
- `image_url text`
- `luminous_flux_lm int`
- `power_w int`
- `beam_pattern text`
- `mounting_type text`
- `explosion_protection_marking text`
- `is_explosion_protected boolean`
- `color_temperature_k int`
- `color_rendering_index_ra int`
- `power_factor_operator text`, `power_factor_min numeric`
- `climate_execution text`
- `operating_temperature_range_raw text`
- `operating_temperature_min_c int`, `operating_temperature_max_c int`
- `ingress_protection text`
- `electrical_protection_class text`
- `supply_voltage_raw text`
- `supply_voltage_kind text`
- `supply_voltage_nominal_v numeric`, `supply_voltage_min_v numeric`, `supply_voltage_max_v numeric`
- `supply_voltage_tolerance_minus_pct numeric`, `supply_voltage_tolerance_plus_pct numeric`
- `dimensions_raw text`
- `length_mm numeric`, `width_mm numeric`, `height_mm numeric`
- `weight_kg numeric`
- `warranty_years int`

Отдельный принцип v1:

- в `catalog_lamps` лежат только поля, по которым реально нужны фильтрация, сортировка, join или индексация;
- оригинальные свойства не дублируются в JSONB, а сохраняются построчно в `catalog_lamp_properties_raw`;
- документы не лежат JSON-объектом в `catalog_lamps`, а вынесены в `catalog_lamp_documents`.

### Индексы для фильтров (v1)

Минимально необходимые индексы для `catalog_lamps`:

- `BTREE(category_id)`
- `BTREE(power_w)`, `BTREE(luminous_flux_lm)`, `BTREE(color_temperature_k)`
- `BTREE(color_rendering_index_ra)`
- `BTREE(ingress_protection)`
- `BTREE(mounting_type)`
- `BTREE(supply_voltage_kind)`
- `BTREE(is_explosion_protected)`
- `BTREE(warranty_years)`
- `BTREE(operating_temperature_min_c, operating_temperature_max_c)`
- `GIN(name gin_trgm_ops)` для быстрого поиска по названию

Для `etm_oracl_catalog_sku`:

- `UNIQUE(etm_code)` и/или `BTREE(etm_code)` (в зависимости от качества данных)
- `UNIQUE(oracl_code)` и/или `BTREE(oracl_code)`
- `BTREE(lamp_id)` (join на лампы)

Для `categories`:

- `GIN(name gin_trgm_ops)`

Для `catalog_lamp_properties_raw`:

- `PRIMARY KEY(lamp_id, property_code)`
- `BTREE(property_code)`
- `BTREE(property_name_ru)`

### Derived read models: VIEW / MATERIALIZED VIEW

Основное ускорение даёт не `VIEW`, а индексы по базовым таблицам. `VIEW` нужен как стабильный read-model и способ скрыть сложные `JOIN` от API/CLI. `MATERIALIZED VIEW` полезен там, где нужен заранее собранный тяжёлый read-model.

Рекомендуемые производные представления:

- `v_catalog_lamps_enriched`
  - `catalog_lamps`
  - `join categories`
  - `left join catalog_lamp_documents`
  - `left join aggregated sku`
  - используется для API-ответов и сборки `corp_search_docs`
- `mv_catalog_lamp_filter_facets` (опционально)
  - предрасчитанные facets/counts по low-cardinality полям (`mounting_type`, `ingress_protection`, `supply_voltage_kind`, `warranty_years`, `color_rendering_index_ra`, `is_explosion_protected`)
  - обновляется после сидирования/реиндексации
- `v_spheres_with_categories`
  - `spheres` + `sphere_categories` + `categories`
  - нужен для поиска и ответа по сферам без ручной сборки списков в рантайме

Hybrid search: data model and SQL
---------------------------------

Требование: гибридный поиск по основным полям/таблицам “как в KB”, то есть FTS + vector + trigram + RRF.

Рекомендуемая схема (v1): **единый поисковый слой** поверх всех сущностей.

Основные runtime-сценарии v1:

- `kb_search`: поиск ответа и доказательной базы по `knowledge_chunks` для вопросов формата “как/что/почему/какой регламент”.
- `entity_resolver`: неточный поиск сущности, когда пользователь помнит только часть названия или код: лампа, категория, сфера, объект портфолио, ETM/Oracle код, тип крепления.
- `candidate_generation`: поиск кандидатов по описанию задачи и признакам (`IP65`, `5000K`, `25Вт`, “подвесной”, “для склада”) до или вместе со структурной фильтрацией.
- `related_evidence`: добор связанных KB chunk’ов, объектов портфолио и вариантов крепления после того, как основная сущность уже найдена.

Служебная таблица:

- `corp_search_docs`:
  - `entity_type text` (enum-like: `lamp`, `category`, `sku`, `portfolio`, `sphere`, `mounting_type`, `category_mounting`, `kb_chunk`)
  - `entity_id text` (PK исходной сущности; для ламп `catalog_lamps.id`, для kb_chunk можно использовать `knowledge_chunks.id`)
  - `title text`
  - `content text`
  - `aliases text` (search-only токены: коды, slug, альтернативные короткие имена, нормализованные числовые/текстовые варианты)
  - `metadata jsonb` (минимальные поля для UI/фильтрации, без дубля “всего подряд”; для KB содержит `source_file` и `document_title`)
  - `fts tsvector GENERATED ALWAYS AS (...) STORED` (русский FTS по `title + content + aliases`)
  - `embedding vector(1536)` (эмбеддинг считается только по semantic-friendly `title + content`, без raw кодов и slug)
  - `source_hash text` (инкрементальная переиндексация)

Индексы:

- `GIN(fts)`
- `GIN(title gin_trgm_ops)`, `GIN(content gin_trgm_ops)`, `GIN(aliases gin_trgm_ops)`
- `HNSW(embedding vector_cosine_ops)`
- `BTREE(entity_type)`, `BTREE(entity_id)`

### Состав документов `corp_search_docs` (что индексируем)

Правило v1: `title` и `content` — это короткие user-facing поля, пригодные для ответа пользователю. Search-only токены (коды, slug, альтернативные имена, нормализованные значения параметров) складываются в `aliases` и по умолчанию не показываются пользователю.

- `entity_type=lamp`:
  - `title`: `catalog_lamps.name`
  - `content`: `categories.name`, ключевые параметры (`luminous_flux_lm`, `power_w`, `color_temperature_k`, `ingress_protection`, `mounting_type`, `operating_temperature_*`, `supply_voltage_*`), короткие user-friendly поля из SKU (если есть)
  - `aliases`: связанные коды и короткие названия из SKU (`etm_code`, `oracl_code`, `catalog_1c`, `short_box_name_wms`, `box_name`), slug-токены из URL, нормализованные токены параметров (`25Вт`, `5000K`, `IP65`, `AC230`)
  - `metadata`: `lamp_id`, `category_id`, `category_name`, опционально `sku_codes[]`
- `entity_type=sku`:
  - `title`: `etm_code / oracl_code` (из доступных кодов)
  - `content`: связанное `catalog_lamps.name`, `box_name`, `description`, `catalog_1c`, `short_box_name_wms`
  - `aliases`: raw code variants, `comments`, дополнительные короткие кодовые/коробочные обозначения
  - `metadata`: `lamp_id`, `etm_code`, `oracl_code`, `is_active`
- `entity_type=category`:
  - `title`: `categories.name`
  - `content`: связанные `sphere_name[]`
  - `aliases`: slug-токены из URL
  - `metadata`: `category_id`
- `entity_type=portfolio`:
  - `title`: `portfolio.name`
  - `content`: `group_name`, `sphere_name` (если денормализовано)
  - `aliases`: slug-токены из URL
  - `metadata`: `sphere_id`
- `entity_type=sphere`:
  - `title`: `spheres.name`
  - `content`: список `category_name` (top N) и несколько примеров `portfolio.name`
  - `aliases`: slug-токены из URL
  - `metadata`: `sphere_id`
- `entity_type=mounting_type`:
  - `title`: `mounting_types.name`
  - `content`: `mark`, `description`
  - `aliases`: дополнительные токены из `mark` и URL
  - `metadata`: `mounting_type_id`, `mark`
- `entity_type=category_mounting`:
  - `title`: `series`
  - `content`: `categories.name`, `mounting_type.name`, `mounting_type.mark`, `is_default`
  - `metadata`: `category_id`, `mounting_type_id`, `is_default`
- `entity_type=kb_chunk`:
  - `title`: `knowledge_chunks.heading`
  - `content`: `knowledge_chunks.content`
  - `aliases`: `document_title`, basename/source_file tokens
  - `metadata`: `source_file`, `document_title` (обязательный `H1` исходного wiki-документа)

### Search profiles (runtime presets)

Одна и та же таблица `corp_search_docs` используется в нескольких профилях рантайма:

- `kb_search`: по умолчанию ищет только по `kb_chunk`, с более сильным весом `semantic + FTS`; покрывает только promoted subset wiki-файлов, попавших в БД по manifest, тогда как полный файловый корпус wiki продолжает обслуживаться `corp-wiki-md-search`.
- `entity_resolver`: по умолчанию ищет по `lamp`, `sku`, `category`, `portfolio`, `sphere`, `mounting_type`, `category_mounting`, с приоритетом exact/trigram совпадений.
- `candidate_generation`: по умолчанию ищет по `lamp`, `category`, `mounting_type`, `sphere`, балансирует `FTS + trigram + semantic` и используется перед структурной фильтрацией или вместе с ней.
- `related_evidence`: вызывается после резолва основной сущности и добирает `kb_chunk`, `portfolio`, `category_mounting` и другие связанные entity types для обоснованного ответа.

### Coexistence with `corp-wiki-md-search`

`corp_db` и `corp_wiki` сосуществуют, а не заменяют друг друга:

- `corp-wiki-md-search` остаётся поиском по полному файловому корпусу wiki, включая документы, ещё не структурированные для БД;
- `corp_db_search` работает по структурированным таблицам и promoted subset wiki, загруженному в `knowledge_chunks`;
- обычный жизненный цикл знания: сначала текст появляется в wiki, затем при необходимости включается в manifest и начинает индексироваться в БД;
- для сравнения качества поиска допускается debug/admin режим `wiki|db|compare`, но production runtime не должен по умолчанию делать лишний dual-read.

SQL-функция (аналог [db/init.sql](/home/admin/totosha.feature-db/db/init.sql)):

- `corp_hybrid_search(query_text text, query_embedding vector(1536), match_count int, weights..., entity_types text[] default null)`
  - выполняет три подзапроса (FTS/semantic/fuzzy) по `corp_search_docs`;
  - опционально ограничивает по `entity_types`;
  - вызывается runtime-слоем в разных профилях (`kb_search`, `entity_resolver`, `candidate_generation`, `related_evidence`), которые задают default `entity_types` и веса без изменения схемы;
  - собирает RRF score и возвращает топ N, включая `debug_info` (в v1 можно оставить как опциональный флаг для диагностики).

Заметка по эмбеддингам
----------------------

Для совместимости с текущим примером:

- модель эмбеддингов: `text-embedding-3-large`
- размерность: `1536` (как в [db/db.py](/home/admin/totosha.feature-db/db/db.py) и [db/init.sql](/home/admin/totosha.feature-db/db/init.sql))

Эмбеддинги в рантайме (для query_embedding) запрашиваются через `proxy`:

- `POST http://proxy:3200/v1/embeddings`

При сидировании `corp_search_docs.embedding` эмбеддинги также считаются через proxy (операторский скрипт), чтобы не размещать ключи в сервисах.

Runtime contract (public-safe)
------------------------------

Primary public runtime path:

- агент использует встроенный tool `corp_db_search`, а skill `corp-pg-db` только объясняет, когда и как его вызывать;
- backend этого tool переключается с Supabase/PostgREST на новый Postgres, но имя tool сохраняется ради совместимости и минимальной миграции;
- агент не должен использовать shell/CLI для доступа к корп. БД в публичном режиме.

Allowlisted runtime operations v1:

- hybrid/entity search;
- exact/suggest queries по лампам;
- поиск SKU по коду;
- фильтрация/листинг ламп;
- запросы по категориям, сферам, портфолио и креплениям.

Требования к tool output (LLM-friendly):

- по умолчанию возвращается компактный JSON:
  - `status: success|empty|error`
  - `query`, `filters`
  - `results[]` (top N, без больших текстов; для KB chunk’ов отдавать `heading`, `document_title` и короткий `preview`)
- лимиты всегда “зажимаются” (например `top<=10`, `offset<=200`);
- ошибки не раскрывают внутренние URL/SQL/DSN; только “база временно недоступна” + короткий код причины.

Operator CLI / worker commands:

- допускаются только в `corp-db-worker` для smoke tests и rebuild flow;
- не используются агентом и не считаются частью публичного runtime-контракта.

Фильтры по параметрам светильников (v1)
---------------------------------------

Минимальный набор фильтров для `lamps`/`search --entity lamp`:

- `--category "<text>"` (по `categories.name`, затем join на `catalog_lamps.category_id`)
- `--power-w <min>..<max>`
- `--flux-lm <min>..<max>`
- `--cct-k <min>..<max>`
- `--ip <text>` (например `IP65`)
- `--mounting "<text>"` (из `mounting_type` свойства)
- `--temp-c <min>..<max>` (по пересечению с `operating_temperature_min_c` / `operating_temperature_max_c`)
- `--voltage-kind <AC|DC|AC/DC>`
- `--explosion-protected <true|false>`

Важное правило: фильтрация выполняется только по **нормализованным колонкам** (а не по JSONB), чтобы были понятные индексы и предсказуемая производительность.

Integration / migration plan
----------------------------

1. Добавить shared skill `corp-pg-db` и синхронизацию в `workspace/_shared/skills`.
2. Добавить Postgres контейнер (pgvector) на базе [db/Dockerfile](/home/admin/totosha.feature-db/db/Dockerfile). Каноническая схема и search SQL живут в [db/init.sql](/home/admin/totosha.feature-db/db/init.sql) и попадают в `/docker-entrypoint-initdb.d/`.
3. Добавить отдельный `corp-db-worker` для operator-only команд `init/seed/reindex`, использующий `CORP_DB_RW_DSN`.
4. Переключить backend встроенного tool `corp_db_search` и [tools-api/src/routes/corp_db.py](/home/admin/totosha.feature-db/tools-api/src/routes/corp_db.py) с Supabase/PostgREST на новый Postgres, сохранив allowlisted runtime contract.
5. Вынести promotion config для KB в `db/knowledge_base_manifest.yaml` и добавить валидацию `H1` для ingest-имых wiki-файлов.
6. Обновить системный промпт агента: он должен использовать и `corp-wiki-md-search`, и `corp-pg-db`, с явными правилами маршрутизации между wiki- и db-поиском.
7. Удалить Supabase-specific config/secrets и код после миграции; fallback на старый backend не сохраняется.
8. В публичном режиме отключить local shell fallback при недоступном sandbox: shell должен fail-closed.

Error handling and UX
---------------------

- `DB down / timeout`: tool `corp_db_search` возвращает `status=error` и сообщение “Корпоративная база временно недоступна”.
- `empty results`: `status=empty`, `results=[]`, + рекомендация сузить запрос (в SKILL.md).
- `validation errors`: понятные сообщения (“нужно указать ровно один из `--etm/--oracl`”, “диапазон power-w некорректен”).
- `KB manifest / H1 invalid`: operator flow завершается ошибкой валидации до сидирования, чтобы не создавать полусломанный индекс.

Update cadence / Lifecycle
--------------------------

v1:

- ручной запуск оператором:
  - `corp-db-worker rebuild --reset|--incremental`
  - при необходимости: `seed-json`, `seed-kb`, `build-search-docs` как отдельные подкоманды worker

Будущий шаг:

- расписание через scheduler (ночная переиндексация), при этом:
  - JSON дампы обновляются отдельным “fetch” скриптом (по API компании);
  - incremental определяется по `sha256` исходников, manifest и `source_hash` в таблицах.

Future-proofing
---------------

- Поддержка дополнительных JSON источников без изменения контракта поиска (добавлением новых `entity_type`).
- Улучшение ранжирования (пер-табличные веса, boosts по полям, “freshness” при появлении дат).
- Расширение фильтров (CRI, PF, диапазон температур, взрывозащита).
- Кэширование эмбеддингов запросов (LRU) в `tools-api` для ускорения.

Implementation outline
----------------------

1. SQL:
   - расширить [db/init.sql](/home/admin/totosha.feature-db/db/init.sql): добавить нормализованные таблицы из JSON-источников (`catalog_lamps`, `catalog_lamp_documents`, `catalog_lamp_properties_raw`, `categories`, `etm_oracl_catalog_sku`, `category_mountings`, `mounting_types`, `portfolio`, `spheres`, `sphere_categories`), `knowledge_chunks`, индексы, `corp_search_docs`, `corp_hybrid_search`;
   - не держать второй SQL-источник внутри skill.
2. Data ingestion:
   - использовать [db/transform_catalog_json.py](/home/admin/totosha.feature-db/db/transform_catalog_json.py) как канонический normalizer для `catalog.json`;
   - загрузка JSON → нормализованные таблицы (валидирует схему, upsert);
   - ingest promoted wiki-файлов → `knowledge_chunks` по manifest и с обязательной валидацией `H1`.
3. Index build:
   - сбор `corp_search_docs` из базовых таблиц, включая `aliases` и `document_title` для KB;
   - эмбеддинги через proxy; incremental по `source_hash`.
   - опциональный refresh materialized views (`mv_catalog_lamp_filter_facets` и др.).
4. Runtime:
   - `tools-api` endpoints для поиска/фильтрации (allowlisted), с preset-профилями `kb_search`, `entity_resolver`, `candidate_generation`, `related_evidence` или эквивалентной внутренней маршрутизацией;
   - встроенный tool `corp_db_search` вызывает эти endpoints;
   - `corp-wiki-md-search` продолжает обслуживать полный wiki corpus.
5. Migration:
   - обновить системный промпт и документацию;
   - сохранить имя tool `corp_db_search`, но заменить его backend на Postgres;
   - удалить Supabase-specific backend и конфигурацию;
   - в публичном режиме перевести shell execution в fail-closed при отсутствии sandbox.

Testing approach
----------------

Unit tests (pytest):

- парсинг/валидация JSON структур (минимальные fixtures);
- нормализация свойств светильников в типизированные поля;
- построение payload’ов/фильтров для API и clamp лимитов;
- валидация `knowledge_base_manifest.yaml` и обязательного `H1` в ingest-имых wiki-файлах.

Integration tests:

- поднятие `pgvector/pgvector:pg17` тестовой БД (docker-compose/testcontainers);
- применение SQL схемы + сидирование small fixtures через worker flow;
- проверка `corp_hybrid_search` (FTS + trigram + semantic) с **моком эмбеддингов**:
  - `embeddings.py` в тестах возвращает детерминированный вектор (например, хэш-основной генератор длины 1536), чтобы не ходить в proxy.
- проверка, что promoted wiki-файл без `H1` отклоняется до сидирования.

Mocks:

- мок HTTP клиента proxy (эмбеддинги);
- мок Postgres/worker orchestration при unit-тестах operator scripts;
- мок `tools-api` клиента для runtime tool-контракта.

Acceptance criteria
-------------------

- В репозитории есть shared skill `corp-pg-db` и он синхронизируется в `workspace/_shared/skills` без ошибок.
- [db/init.sql](/home/admin/totosha.feature-db/db/init.sql) является единственным источником истины для схемы и search SQL, а [db/transform_catalog_json.py](/home/admin/totosha.feature-db/db/transform_catalog_json.py) — каноническим нормализатором каталога.
- Postgres поднимается с расширениями `vector` и `pg_trgm`, и создаёт нормализованные таблицы из JSON-источников, включая минимум `catalog_lamps`, `catalog_lamp_documents`, `catalog_lamp_properties_raw`, `categories`, `etm_oracl_catalog_sku`, `category_mountings`, `mounting_types`, `portfolio`, `spheres`, `sphere_categories`, а также `knowledge_chunks`.
- Operator flow умеет инициализировать и обновлять БД из `/data/corp_pg_db/sources` и promoted subset wiki из `/data/skills/corp-wiki-md-search/wiki`, используя `knowledge_base_manifest.yaml`, `--sources-dir`, `--wiki-dir`, `--kb-manifest`, `--reset` и `--incremental`.
- Отдельный `/data/corp_pg_db/knowledge_base/` в v1 отсутствует; wiki остаётся единственным источником истины для Markdown-контента.
- Есть слой hybrid search, реализованный по принципам из [/home/admin/totosha.feature-db/docs/kb-hybrid-search.md](/home/admin/totosha.feature-db/docs/kb-hybrid-search.md), и он покрывает минимум сценарии `kb_search`, `entity_resolver`, `candidate_generation`; для запроса по названию лампы результаты могут включать связанные `sku`, а `kb_chunk.metadata` содержит `source_file` и `document_title`.
- Встроенный tool `corp_db_search` использует новый Postgres backend и умеет:
  - искать по тексту (hybrid);
  - фильтровать светильники по `power_w`, `flux_lm`, `cct_k`, `ip`, `category`, `mounting_type`, `temp_c`, `voltage_kind`.
- Системный промпт агента обновлён и явно задаёт routing policy между `corp-wiki-md-search` и `corp_db_search`.
- Тесты:
  - юнит-тесты нормализации и валидации проходят;
  - интеграционный тест гибридного поиска проходит на тестовой БД с мок-эмбеддингами.
- В sandbox/agent отсутствуют DB credentials и любые внешние ключи; эмбеддинги берутся только через proxy; в публичном режиме shell execution не падает обратно в local mode для доступа к корп. данным.
