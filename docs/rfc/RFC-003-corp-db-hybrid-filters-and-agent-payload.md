RFC: `corp_db` hybrid search по всем нормализованным полям + agent-friendly payload
=================================================================================

Status
------

Draft (2026-03-29)

Context and motivation
----------------------

Текущий `corp_db` уже умеет:

- резолвить точные модели через `lamp_exact`;
- делать гибридный поиск по `corp_search_docs`;
- фильтровать часть каталога через `lamp_filters`.

Но фактически поиск и ответы покрывают только подмножество характеристик ламп. Последний инцидент с `weight_kg` показал системную проблему: данные есть в `catalog_lamps`, но не всегда доходят до:

- поискового индекса;
- allowlisted runtime-контракта `corp_db_search`;
- ответа в форме, удобной для агента.

Это приводит к типовым сбоям:

- агент находит сущность, но не получает нужное поле;
- agent уходит в лишние fallback-поиски по wiki;
- bench-кейсы по характеристикам нестабильны или не покрывают часть каталога;
- добавление каждого нового поля превращается в точечный патч вместо расширяемого контракта.

Нужен простой следующий шаг:

1. сделать все **нормализованные** поля `catalog_lamps` доступными для фильтрации в гибридном поиске;
2. вернуть результаты в стабильной, понятной агенту форме;
3. не усложнять архитектуру новыми сервисами или новым алгоритмом ранжирования;
4. сохранить быстрый ответ и текущий allowlisted runtime-path.

Goals
-----

- Поддержать фильтрацию в `hybrid_search` по всем нормализованным полям `corp.catalog_lamps`.
- Сохранить существующий публичный tool-контракт: агент по-прежнему использует только `corp_db_search`.
- Добавить единый канонический слой сериализации лампы, чтобы:
  - `lamp_exact`,
  - `lamp_filters`,
  - `category_lamps`,
  - `hybrid_search`
  отдавали согласованный payload.
- Добавить agent-friendly представление результата:
  - короткий `agent_summary`;
  - структурированный `facts` / `fact_text`;
  - сохраняемый `preview` для backward compatibility.
- Расширить `bench/golden/v1.jsonl` кейсами по разным характеристикам, чтобы bench ловил регрессии не только по весу.

Non-goals for first implementation (v1)
---------------------------------------

- Поддержка произвольных raw-property фильтров по `catalog_lamp_properties_raw`.
- Natural-language-to-SQL или произвольный язык запросов поверх фильтров.
- Новый поисковый сервис, новый vector store или вынесение search logic из Postgres.
- Переписывание алгоритма `FTS + trigram + semantic + RRF`.
- Полная унификация всех сущностей (`lamp`, `sku`, `category`, `kb_chunk`) в один сверх-универсальный rich payload.

Implementation considerations
-----------------------------

- **Простота:**
  - не добавляем новый сервис;
  - не меняем tool name;
  - не вводим новый “язык фильтров”, если можно обойтись allowlisted flat-полями.
- **Скорость:**
  - гибридный алгоритм остаётся текущим;
  - фильтры добавляются как дополнительный SQL `WHERE` по `catalog_lamps` / view;
  - используем индексы только там, где они реально помогают фильтрации.
- **Единый источник формата:**
  - текст для индекса и текст/факты для агента должны собираться из одного канонического представления лампы, а не дублироваться в нескольких местах.
- **Совместимость:**
  - старые поля `preview`, `metadata`, `results[]` сохраняются;
  - новые поля добавляются без ломающего изменения контракта.

Current gaps
------------

На момент написания RFC поиск и runtime не покрывают существенную часть характеристик ламп:

- `beam_pattern`
- `explosion_protection_marking`
- `is_explosion_protected`
- `color_rendering_index_ra`
- `power_factor_operator`
- `power_factor_min`
- `climate_execution`
- `operating_temperature_min_c`
- `operating_temperature_max_c`
- `electrical_protection_class`
- `supply_voltage_nominal_v`
- `supply_voltage_min_v`
- `supply_voltage_max_v`
- `supply_voltage_tolerance_minus_pct`
- `supply_voltage_tolerance_plus_pct`
- `dimensions_raw`
- `length_mm`
- `width_mm`
- `height_mm`
- `warranty_years`

Из-за этого агент не может стабильно отвечать на типовые вопросы вроде:

- “Какой угол светораспределения?”
- “Какой CRI / Ra?”
- “Какой класс защиты от поражения током?”
- “Какие габариты?”
- “Какая гарантия?”
- “Какой диапазон питания?”
- “Какая маркировка взрывозащиты?”

Proposed solution
-----------------

### 1. Один канонический view для ламп

Добавляется plain view:

`corp.v_catalog_lamps_agent`

Он строится над `corp.catalog_lamps` и возвращает:

- все allowlisted нормализованные колонки лампы;
- `agent_summary text`
- `agent_facts jsonb`
- `search_text text`
- `search_aliases text`

Пример `agent_facts`:

```json
{
  "power_w": { "label": "Мощность", "text": "557 Вт", "value": 557, "unit": "Вт" },
  "luminous_flux_lm": { "label": "Световой поток", "text": "78537 лм", "value": 78537, "unit": "лм" },
  "beam_pattern": { "label": "Светораспределение", "text": "30°", "value": "30°" },
  "dimensions_raw": { "label": "Габариты", "text": "774 x 428 x 406 мм", "value": "774 x 428 x 406" },
  "warranty_years": { "label": "Гарантия", "text": "5 лет", "value": 5, "unit": "лет" }
}
```

Пример `agent_summary`:

```text
Светильник LAD LED R500-9-30-6-650LZD. Мощность 557 Вт. Световой поток 78537 лм. Светораспределение 30°. IP65. Вес 18.3 кг. Габариты 774 x 428 x 406 мм. Гарантия 5 лет.
```

Зачем нужен view:

- одна точка правды для текста индекса и для ответа агенту;
- меньше дублирования в `db/search_docs.py` и `tools-api/src/routes/corp_db.py`;
- изменение формулировки/порядка полей делается в одном месте.

### 2. Расширение allowlisted фильтров до всех нормализованных полей

Публичный runtime-контракт остаётся flat и agent-friendly. Не вводится DSL и не требуется составлять вложенные операторы.

Предлагаемая модель:

- текстовые поля:
  - `beam_pattern`
  - `mounting_type`
  - `ingress_protection`
  - `climate_execution`
  - `electrical_protection_class`
  - `explosion_protection_marking`
  - `supply_voltage_raw`
  - `dimensions_raw`
  - `power_factor_operator`
- boolean:
  - `explosion_protected`
- точные / диапазонные numeric-поля:
  - `power_w_min/max`
  - `flux_lm_min/max`
  - `cct_k_min/max`
  - `weight_kg_min/max`
  - `cri_ra_min/max`
  - `power_factor_min_min/max`
  - `temp_c_min/max`
  - `voltage_nominal_v_min/max`
  - `voltage_min_v_min/max`
  - `voltage_max_v_min/max`
  - `voltage_tol_minus_pct_min/max`
  - `voltage_tol_plus_pct_min/max`
  - `length_mm_min/max`
  - `width_mm_min/max`
  - `height_mm_min/max`
  - `warranty_years_min/max`

Принцип:

- используем явные allowlisted поля;
- не даём агенту произвольные SQL-операторы;
- нормализация значений происходит в `tools-api`.

### 3. Гибридный поиск с фильтрами без нового алгоритма

Алгоритм гибридного поиска не меняется. Меняется только способ отбора ламп, если в запросе есть фильтры.

Поведение:

1. Если `hybrid_search` не содержит фильтров по лампе:
   - используется текущий путь.
2. Если `hybrid_search` содержит lamp-фильтры:
   - candidate generation остаётся на `corp_search_docs`;
   - для `entity_type=lamp` candidate rows join’ятся с `corp.v_catalog_lamps_agent`;
   - к joined rows применяется один allowlisted SQL `WHERE`;
   - final payload строится из `v_catalog_lamps_agent`.

Это означает:

- `FTS + trigram + semantic + RRF` остаются прежними;
- фильтры не требуют отдельной поисковой подсистемы;
- поведение `lamp_filters` и `hybrid_search + filters` использует один и тот же фильтрующий слой.

Для избежания потери recall:

- при наличии lamp-фильтров candidate limit увеличивается, например до `max(limit * 8, 40)` с верхней границей `120`;
- только для lamp-path;
- без изменения поведения остальных entity types.

Если profiling покажет, что candidate inflation недостаточен, следующим шагом может стать SQL helper для lamp-only path, но это не требуется в v1 RFC.

### 4. Agent-friendly response без лишней логики в модели

Все lamp-результаты начинают возвращать согласованный набор полей:

```json
{
  "entity_type": "lamp",
  "entity_id": "2014",
  "title": "LAD LED R500-9-30-6-650LZD",
  "preview": "LAD LED R500-9 LZD | 557 Вт | 78537 лм | 30° | IP65 | 18.3 кг",
  "agent_summary": "Светильник LAD LED R500-9-30-6-650LZD. Мощность 557 Вт. Световой поток 78537 лм. Светораспределение 30°. IP65. Вес 18.3 кг.",
  "facts": {
    "power_w": { "label": "Мощность", "text": "557 Вт", "value": 557, "unit": "Вт" },
    "beam_pattern": { "label": "Светораспределение", "text": "30°", "value": "30°" }
  },
  "metadata": {
    "lamp_id": 2014,
    "category_id": 68,
    "category_name": "LAD LED R500-9 LZD",
    "url": "https://..."
  }
}
```

Почему это важно:

- агенту не нужно самому “угадывать”, как verbalize поле;
- короткие ответы пользователю становятся почти прямой трансляцией `agent_summary` или конкретного `facts[*].text`;
- снижается риск галлюцинаций при ответах на точные теххарактеристики.

### 5. Что индексируется в `corp_search_docs`

`search_docs.py` начинает брать ламповый текст не из hand-written набора Python-полей, а из канонического представления:

- `title` = `name`
- `content` = `search_text`
- `aliases` = `search_aliases`
- `metadata` = минимальный allowlisted срез + `facts`

Минимальный набор значений, который должен попадать в `search_text`:

- мощность
- световой поток
- CCT
- вес
- CRI / `Ra`
- светораспределение / угол
- IP
- монтаж
- климатическое исполнение
- класс электрозащиты
- диапазон температур
- напряжение питания
- габариты
- гарантия
- взрывозащита / маркировка

Indexes and view strategy
-------------------------

Чтобы не усложнять архитектуру, в v1 используется:

- один plain view `corp.v_catalog_lamps_agent`;
- индексы на базовой таблице `corp.catalog_lamps`;
- существующая таблица `corp.corp_search_docs` остаётся materialized runtime-layer в виде обычной таблицы, собираемой worker’ом.

Рекомендуемые дополнительные индексы:

- `GIN TRGM`:
  - `beam_pattern`
  - `climate_execution`
  - `electrical_protection_class`
  - `explosion_protection_marking`
  - `dimensions_raw`
- `BTREE`:
  - `weight_kg`
  - `color_rendering_index_ra`
  - `power_factor_min`
  - `supply_voltage_nominal_v`
  - `supply_voltage_min_v`
  - `supply_voltage_max_v`
  - `supply_voltage_tolerance_minus_pct`
  - `supply_voltage_tolerance_plus_pct`
  - `length_mm`
  - `width_mm`
  - `height_mm`
  - `warranty_years`

Индексы для low-cardinality boolean/text:

- `is_explosion_protected`
- `power_factor_operator`

добавляются только при необходимости по результатам `EXPLAIN ANALYZE` и bench latency.

Migration and rollout
---------------------

1. Добавить `corp.v_catalog_lamps_agent` в [db/init.sql](/home/admin/totosha/db/init.sql).
2. Добавить новые индексы в [db/init.sql](/home/admin/totosha/db/init.sql).
3. Обновить `db/search_docs.py`, чтобы использовать канонический agent/search payload.
4. Расширить request model и allowlisted filters в [tools-api/src/routes/corp_db.py](/home/admin/totosha/tools-api/src/routes/corp_db.py).
5. Протянуть новый payload в `lamp_exact`, `lamp_filters`, `category_lamps`, `hybrid_search`.
6. Пересобрать `corp_search_docs` через `corp-db-worker build-search-docs`.
7. Прогнать bench.

Bench dataset additions
-----------------------

В `bench/golden/v1.jsonl` добавляются кейсы минимум по следующим характеристикам:

- `beam_pattern`
- `color_rendering_index_ra`
- `electrical_protection_class`
- `dimensions_raw`
- `warranty_years`
- `climate_execution`
- `supply_voltage_*`
- `power_factor_min`
- `operating_temperature_range_raw`
- `explosion_protection_marking`

Цель bench-расширения:

- проверять, что агент не только нашёл лампу, но и получил конкретное поле;
- ловить регрессии в индексе, фильтрах и response serialization;
- оценивать, не сломалась ли краткая вербализация результата для пользователя.

Testing approach
----------------

- Unit:
  - нормализация allowlisted filters;
  - сериализация `agent_summary` / `facts`;
  - построение search docs для лампы со всеми ключевыми характеристиками.
- Integration:
  - `lamp_exact` по точной модели возвращает `agent_summary` и `facts`;
  - `hybrid_search` с query + filters возвращает нужную лампу и правильные `facts`;
  - `lamp_filters` и `hybrid_search + filters` используют одинаковую фактическую сериализацию.
- Bench:
  - новый набор кейсов в `bench/golden/v1.jsonl`;
  - прогоны через `bench/bench_run.py` и `bench/bench_eval.py`.

Acceptance criteria
-------------------

- Все нормализованные user-facing поля `catalog_lamps` allowlisted для фильтрации в `hybrid_search` или прямом lamp-path.
- Lamp results возвращают единый agent-friendly payload:
  - `preview`
  - `agent_summary`
  - `facts`
  - `metadata`
- `corp_search_docs` индексирует те же характеристики, которые агент ожидает увидеть в ответе.
- Новые bench-кейсы по характеристикам проходят без ручного prompt workaround.
- Медианная latency для catalog-вопросов не деградирует существенно относительно текущего пути; допустимое отклонение для v1: не более `+20%` на p50 и не более `+30%` на p95 по подмножеству catalog-кейсов.
