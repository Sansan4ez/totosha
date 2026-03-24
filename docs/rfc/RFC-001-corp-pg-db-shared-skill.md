RFC: Shared Skill `corp-pg-db` для корпоративных данных (Postgres + Hybrid Search)
===============================================================================

Status
------

Draft (2026-03-23)

Context and motivation
----------------------

Сейчас доступ к корпоративным данным каталога реализован через tool `corp_db_search` и тонкий клиент в [core/tools/corp_db.py](/home/admin/totosha.feature-db/core/tools/corp_db.py), который проксирует запросы в `tools-api` и далее в Supabase/PostgREST. Это:

- усложняет инфраструктуру (внешняя Supabase, ключи, PostgREST RPC);
- не совпадает с целевой моделью “корпоративные источники внутри периметра”;
- слабо расширяемо под гибридный поиск и фильтрацию по параметрам светильников.

Цель этого RFC: добавить в проект новый **shared skill** (доступный как `/data/skills/...` в sandbox), который даёт агенту единый CLI-интерфейс для поиска/фильтрации по корпоративной базе данных, работающей на **PostgreSQL** и наполненной данными из JSON/Markdown источников.

Goals
-----

- Добавить shared skill `corp-pg-db` (kebab-case) с:
  - основной CLI-утилитой для поиска и фильтрации;
  - набором вспомогательных скриптов для инициализации/сидирования/переиндексации.
- Развернуть PostgreSQL (pgvector + pg_trgm + FTS) с данными:
  - 7 таблиц, каждая соответствует JSON-дампу из [/home/admin/totosha.feature-db/db](/home/admin/totosha.feature-db/db);
  - 1 таблица по Markdown из [/home/admin/totosha.feature-db/docs/knowledge_base](/home/admin/totosha.feature-db/docs/knowledge_base) (chunking по `###`).
- Реализовать **гибридный поиск** (FTS + pgvector + trigram + RRF) по основным полям/таблицам в соответствии с [/home/admin/totosha.feature-db/docs/kb-hybrid-search.md](/home/admin/totosha.feature-db/docs/kb-hybrid-search.md).
- Поддержать фильтрацию по “основным полям” и параметрам светильников (поток, мощность, CCT, IP и т.д.) с предсказуемыми правилами нормализации.
- Предусмотреть тесты и моки (включая мок эмбеддингов).

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
  - любые запросы ограничены allowlist’ом операций и лимитами (limit/offset/clamp).
- **Determinism и воспроизводимость:**
  - схема и индексы должны быть описаны SQL-инициализацией (база поднимается “с нуля”);
  - сидирование из исходников (JSON/MD) должно быть идемпотентным и поддерживать incremental.
- **Hybrid search:**
  - как в [db/init.sql](/home/admin/totosha.feature-db/db/init.sql): `vector(1536)`, `hnsw`, `tsvector` + GIN, `pg_trgm` + GIN, и RRF-фьюжн.
- **Operational simplicity:**
  - одна команда для оператора: “init + seed + reindex”;
  - одна команда для агента: “search/filter”.

High-level behavior
-------------------

1. Оператор поднимает `postgres` контейнер (pgvector) с базовой схемой и расширениями (на базе [db/Dockerfile](/home/admin/totosha.feature-db/db/Dockerfile) и [db/init.sql](/home/admin/totosha.feature-db/db/init.sql)).
2. Скрипты сидирования загружают 7 JSON-дампов и Markdown KB в таблицы (v1: full reset и incremental по hash).
3. Скрипт индексации строит “поисковый слой” (см. раздел Data model и Hybrid search).
4. Во время диалога агент:
  - загружает инструкцию skill `corp-pg-db` (через `/data/skills/...`);
  - вызывает CLI для поиска/фильтрации;
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
  scripts/
    corpdb.py                 # основной CLI (search/filter)
    http_client.py            # вызов tools-api (no secrets)
    seed_json.py              # загрузка 7 JSON в таблицы (operator-only)
    seed_kb_md.py             # chunking и загрузка MD KB (operator-only)
    build_search_docs.py      # построение/обновление слоя hybrid search (operator-only)
    embeddings.py             # клиент эмбеддингов через proxy (operator-only + runtime для hybrid)
  sql/
    01-extensions.sql
    02-schema.sql
    03-functions.sql
```

Примечание: скрипты сидирования/индексации запускаются **оператором** в доверенной среде (например, `docker exec tools-api ...` или отдельным job-контейнером), а CLI поиска запускается **в песочнице** и не хранит секретов.

PostgreSQL: schema and tables
-----------------------------

### Роли и подключение (security boundary)

Рекомендуемая модель доступа:

- `corp_rw` (writer): используется только сидерами (operator-only).
- `corp_ro` (read-only): используется только рантайм-эндпоинтами поиска/фильтрации.

DSN передаются сервисам через Docker secrets (аналогично Supabase key в текущем `tools-api`):

- `CORP_DB_RW_DSN` (secret) доступен только job/контейнеру сидирования.
- `CORP_DB_RO_DSN` (secret) доступен `tools-api` (или отдельному `corp-db-api`), который реализует allowlisted запросы.

Sandbox не содержит DSN и не подключается к Postgres напрямую.

### 7 таблиц из JSON (по 1 таблице на файл)

Источник: файлы в [/home/admin/totosha.feature-db/db](/home/admin/totosha.feature-db/db)

1. `catalog_lamps` ← `db/catalog.json` (`products[]`)
2. `categories` ← `db/categories.json` (`categories[]`)
3. `etm_oracl_catalog_sku` ← `db/etm_oracl_catalog_sku.json` (array)
4. `lamp_mountings` ← `db/lamp_mountings.json` (`lampMountings[]`)
5. `mounting_types` ← `db/mounting_types.json` (`mountingTypes[]`)
6. `portfolio` ← `db/portfolio.json` (`portfolio[]`)
7. `spheres` ← `db/spheres.json` (`spheres[]`)

### 1 таблица из Markdown KB

8. `knowledge_chunks` ← chunking файлов `docs/knowledge_base/*.md` по правилам из [/home/admin/totosha.feature-db/docs/kb-hybrid-search.md](/home/admin/totosha.feature-db/docs/kb-hybrid-search.md) (chunking по `###`, игнор до первой `###`, пустые chunk’и пропускать).

### Где лежат исходники JSON/MD в runtime

В production-контейнерах репозиторий (и папки `db/`, `docs/`) обычно не смонтирован. Поэтому источники должны быть доступны сидерам/индексаторам через shared volume (`/data`) или быть “упакованы” в skill.

Рекомендуемый вариант:

- хранить актуальные дампы в `workspace/_shared/corp_pg_db/sources/` (в контейнерах: `/data/corp_pg_db/sources/`);
- хранить KB Markdown в `workspace/_shared/corp_pg_db/knowledge_base/` (в контейнерах: `/data/corp_pg_db/knowledge_base/`).

Альтернатива (упаковка в skill, read-only):

- положить `sources/*.json` и `knowledge_base/*.md` внутрь `shared_skills/skills/corp-pg-db/` и использовать их как seed-источник.

Во всех скриптах сидирования предусмотреть флаги:

- `--sources-dir` (по умолчанию `/data/corp_pg_db/sources`)
- `--kb-dir` (по умолчанию `/data/corp_pg_db/knowledge_base`)

### Нормализация параметров светильников (filter fields)

В `catalog_lamps` v1 выделяются отдельные типизированные колонки (для фильтрации/сортировки), нормализуемые из `products[].properties[]`:

- `luminous_flux_lm int`
- `power_consumption_w int`
- `beam_angle text` (или `beam_angle_deg int NULL` при возможности извлечения)
- `diffuser text`
- `color_temperature_k int`
- `color_rendering_index int`
- `power_factor numeric`
- `climatic_execution_type text`
- `operating_temperature_min_c int`, `operating_temperature_max_c int`
- `ip_class text`
- `electric_shock_protection_class text`
- `nominal_voltage_v int`, `current_type text`
- `dimensions_mm int[]` (или `dimensions_text text`)
- `weight_kg numeric`
- `warranty_period_years int`
- `explosion_protection_marking text`
- `mounting_type text` (из свойства “Тип крепления”)

Остальные свойства сохраняются в `properties jsonb` (raw) как источник правды.

### Индексы для фильтров (v1)

Минимально необходимые индексы для `catalog_lamps`:

- `BTREE(category_id)`
- `BTREE(series)`
- `BTREE(power_consumption_w)`, `BTREE(luminous_flux_lm)`, `BTREE(color_temperature_k)`
- `BTREE(ip_class)`
- `BTREE(mounting_type)`

Для `etm_oracl_catalog_sku`:

- `UNIQUE(etm_code)` и/или `BTREE(etm_code)` (в зависимости от качества данных)
- `UNIQUE(oracl_code)` и/или `BTREE(oracl_code)`
- `BTREE(catalog_lamps_id)` (join на лампы)

Hybrid search: data model and SQL
---------------------------------

Требование: гибридный поиск по основным полям/таблицам “как в KB”, то есть FTS + vector + trigram + RRF.

Рекомендуемая схема (v1): **единый поисковый слой** поверх всех сущностей.

Служебная таблица:

- `corp_search_docs`:
  - `entity_type text` (enum-like: `lamp`, `category`, `sku`, `portfolio`, `sphere`, `mounting_type`, `lamp_mounting`, `kb_chunk`)
  - `entity_id text` (PK исходной сущности; для ламп `catalog_lamps.id`, для kb_chunk можно использовать `knowledge_chunks.id`)
  - `title text`
  - `content text`
  - `metadata jsonb` (минимальные поля для UI/фильтрации, без дубля “всего подряд”)
  - `fts tsvector GENERATED ALWAYS AS (...) STORED` (русский FTS)
  - `embedding vector(1536)`
  - `source_hash text` (инкрементальная переиндексация)

Индексы:

- `GIN(fts)`
- `GIN(title gin_trgm_ops)`, `GIN(content gin_trgm_ops)`
- `HNSW(embedding vector_cosine_ops)`
- `BTREE(entity_type)`, `BTREE(entity_id)`

### Состав документов `corp_search_docs` (что индексируем)

Правило v1: `title` и `content` собираются только из “основных полей”, пригодных для ответа пользователю.

- `entity_type=lamp`:
  - `title`: `catalog_lamps.name`
  - `content`: `series`, `category_name`, ключевые параметры (поток/мощность/CCT/IP/крепление), короткие описательные поля из SKU (если есть)
  - `metadata`: `lamp_id`, `series`, `category_id`, `category_name`
- `entity_type=sku`:
  - `title`: `etm_code` или `oracl_code`
  - `content`: `box_name`, `description`, `catalog_1c`, `short_box_name_wms`
  - `metadata`: `lamp_id`, `etm_code`, `oracl_code`, `is_active`
- `entity_type=category`:
  - `title`: `categories.name`
  - `content`: `power_description`, `parent_name`
  - `metadata`: `category_id`, `parent_id`
- `entity_type=portfolio`:
  - `title`: `portfolio.name`
  - `content`: `group_name`, `sphere_name` (если денормализовано)
  - `metadata`: `sphere_id`
- `entity_type=sphere`:
  - `title`: `spheres.name`
  - `content`: список `category_name` (по mapping из spheres → categories)
  - `metadata`: `sphere_id`
- `entity_type=mounting_type`:
  - `title`: `mounting_types.name` (и/или `mark`)
  - `content`: `description`
  - `metadata`: `mounting_type_id`, `mark`
- `entity_type=lamp_mounting`:
  - `title`: `series` + `category_name`
  - `content`: `mounting_type.name`, `is_default`
  - `metadata`: `category_id`, `mounting_type_id`, `is_default`
- `entity_type=kb_chunk`:
  - `title`: `knowledge_chunks.heading`
  - `content`: `knowledge_chunks.content`
  - `metadata`: `source_file`

SQL-функция (аналог [db/init.sql](/home/admin/totosha.feature-db/db/init.sql)):

- `corp_hybrid_search(query_text text, query_embedding vector(1536), match_count int, weights..., entity_types text[] default null)`
  - выполняет три подзапроса (FTS/semantic/fuzzy) по `corp_search_docs`;
  - опционально ограничивает по `entity_types`;
  - собирает RRF score и возвращает топ N, включая `debug_info` (в v1 можно оставить как опциональный флаг для диагностики).

Заметка по эмбеддингам
----------------------

Для совместимости с текущим примером:

- модель эмбеддингов: `text-embedding-3-large`
- размерность: `1536` (как в [db/db.py](/home/admin/totosha.feature-db/db/db.py) и [db/init.sql](/home/admin/totosha.feature-db/db/init.sql))

Эмбеддинги в рантайме (для query_embedding) запрашиваются через `proxy`:

- `POST http://proxy:3200/v1/embeddings`

При сидировании `corp_search_docs.embedding` эмбеддинги также считаются через proxy (операторский скрипт), чтобы не размещать ключи в сервисах.

CLI contract (search + filter)
------------------------------

Основной CLI (агентский entrypoint):

```bash
python3 /data/skills/corp-pg-db/scripts/corpdb.py search "<query>" --top 5 --entity lamp,sku,kb_chunk
python3 /data/skills/corp-pg-db/scripts/corpdb.py lamps --category "LAD LED R500-1" --power-w 15..40 --ip IP65 --top 10
python3 /data/skills/corp-pg-db/scripts/corpdb.py sku --etm LINE1132
```

Требования к CLI output (LLM-friendly):

- по умолчанию печатает компактный JSON:
  - `status: success|empty|error`
  - `query`, `filters`
  - `results[]` (top N, без больших текстов; для KB chunk’ов отдавать `heading` и короткий `preview`)
- лимиты всегда “зажимаются” (например `top<=10`, `offset<=200`)
- ошибки не раскрывают внутренние URL/SQL/DSN; только “база временно недоступна” + короткий код причины.

Фильтры по параметрам светильников (v1)
---------------------------------------

Минимальный набор фильтров для `lamps`/`search --entity lamp`:

- `--series "<text>"`
- `--category "<text>"` (по `categories.name`, затем join на `catalog_lamps.category_id`)
- `--power-w <min>..<max>`
- `--flux-lm <min>..<max>`
- `--cct-k <min>..<max>`
- `--ip <text>` (например `IP65`)
- `--mounting "<text>"` (из `mounting_type` свойства)

Важное правило: фильтрация выполняется только по **нормализованным колонкам** (а не по JSONB), чтобы были понятные индексы и предсказуемая производительность.

Integration / migration plan
----------------------------

1. Добавить shared skill `corp-pg-db` и синхронизацию в `workspace/_shared/skills`.
2. Добавить Postgres контейнер (pgvector) на базе [db/Dockerfile](/home/admin/totosha.feature-db/db/Dockerfile). Вынести расширенную схему/функции (см. выше) в SQL, который попадает в `/docker-entrypoint-initdb.d/`.
3. (Рекомендуется) В `tools-api` добавить allowlisted HTTP-эндпоинты для выполнения:
   - гибридного поиска;
   - “канонических” запросов (lamp_exact, sku_by_code и т.д.) как в текущем [tools-api/src/routes/corp_db.py](/home/admin/totosha.feature-db/tools-api/src/routes/corp_db.py), но поверх нового Postgres.
4. CLI `corpdb.py` в skill обращается к `tools-api` (а не напрямую к БД), чтобы sandbox не имел DB credentials.
5. Обновить системный промпт агента: заменить ссылку на несуществующий `supabase-corp-db` в [core/src/agent/system.txt](/home/admin/totosha.feature-db/core/src/agent/system.txt) на `corp-pg-db`.
6. Депрекейт и удаление: `corp_db_search` и [core/tools/corp_db.py](/home/admin/totosha.feature-db/core/tools/corp_db.py) удаляются после стабилизации (или остаются как fallback за feature-flag).

Error handling and UX
---------------------

- `DB down / timeout`: CLI возвращает `status=error` и сообщение “Корпоративная база временно недоступна”.
- `empty results`: `status=empty`, `results=[]`, + рекомендация сузить запрос (в SKILL.md).
- `validation errors`: понятные сообщения (“нужно указать ровно один из `--etm/--oracl`”, “диапазон power-w некорректен”).

Update cadence / Lifecycle
--------------------------

v1:

- ручной запуск оператором:
  - `seed_json.py --reset|--incremental`
  - `seed_kb_md.py --reset|--incremental`
  - `build_search_docs.py --reset|--incremental`

Будущий шаг:

- расписание через scheduler (ночная переиндексация), при этом:
  - JSON дампы обновляются отдельным “fetch” скриптом (по API компании);
  - incremental определяется по `sha256` исходников и `source_hash` в таблицах.

Future-proofing
---------------

- Поддержка дополнительных JSON источников без изменения контракта поиска (добавлением новых `entity_type`).
- Улучшение ранжирования (пер-табличные веса, boosts по полям, “freshness” при появлении дат).
- Расширение фильтров (CRI, PF, диапазон температур, взрывозащита).
- Кэширование эмбеддингов запросов (LRU) в `tools-api` для ускорения.

Implementation outline
----------------------

1. SQL:
   - расширить пример из [db/init.sql](/home/admin/totosha.feature-db/db/init.sql): добавить 7+1 таблиц, индексы, `corp_search_docs`, `corp_hybrid_search`.
2. Data ingestion:
   - скрипт загрузки 7 JSON → таблицы (валидирует схему, нормализует поля, upsert);
   - скрипт chunking MD → `knowledge_chunks` (по правилам KB doc).
3. Index build:
   - сбор `corp_search_docs` из базовых таблиц;
   - эмбеддинги через proxy; incremental по `source_hash`.
4. Runtime:
   - `tools-api` endpoints для поиска/фильтрации (allowlisted);
   - CLI skill вызывает endpoints и форматирует ответ.
5. Migration:
   - обновить системный промпт и документацию;
   - оставить старый `corp_db_search` на время как fallback.

Testing approach
----------------

Unit tests (pytest):

- парсинг/валидация JSON структур (минимальные fixtures);
- нормализация свойств светильников в типизированные поля;
- построение payload’ов/фильтров для API и clamp лимитов.

Integration tests:

- поднятие `pgvector/pgvector:pg17` тестовой БД (docker-compose/testcontainers);
- применение SQL схемы + сидирование small fixtures;
- проверка `corp_hybrid_search` (FTS + trigram + semantic) с **моком эмбеддингов**:
  - `embeddings.py` в тестах возвращает детерминированный вектор (например, хэш-основной генератор длины 1536), чтобы не ходить в proxy.

Mocks:

- мок HTTP клиента proxy (эмбеддинги);
- мок `tools-api` клиента для CLI (на уровне unit тестов CLI).

Acceptance criteria
-------------------

- В репозитории есть shared skill `corp-pg-db` и он синхронизируется в `workspace/_shared/skills` без ошибок.
- Postgres поднимается с расширениями `vector` и `pg_trgm`, и создаёт 7 JSON-таблиц + `knowledge_chunks`.
- Сидеры/индексатор читают источники из `/data/corp_pg_db/sources` и `/data/corp_pg_db/knowledge_base` (или из упакованного skill) и поддерживают `--reset` и `--incremental`.
- Есть слой hybrid search, реализованный по принципам из [/home/admin/totosha.feature-db/docs/kb-hybrid-search.md](/home/admin/totosha.feature-db/docs/kb-hybrid-search.md), и он возвращает результаты минимум по `lamp` и `kb_chunk`.
- CLI умеет:
  - искать по тексту (hybrid);
  - фильтровать светильники по `power_w`, `flux_lm`, `cct_k`, `ip`, `category/series`.
- Тесты:
  - юнит-тесты нормализации и валидации проходят;
  - интеграционный тест гибридного поиска проходит на тестовой БД с мок-эмбеддингами.
- В sandbox/agent отсутствуют DB credentials и любые внешние ключи; эмбеддинги берутся только через proxy.
