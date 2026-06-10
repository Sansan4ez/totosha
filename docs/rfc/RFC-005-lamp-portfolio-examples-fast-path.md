RFC-005 Lamp Portfolio Examples Fast Path
=========================================

Status
------

Proposed

Date
----

2026-04-02

Context and motivation
----------------------

Запросы вида "примеры реализации объектов для светильника `R500-9-30-6-650LZD`" являются реальным и повторяемым сценарием, но текущий retrieval path не покрывает его как отдельную бизнес-операцию.

Сейчас backend умеет по отдельности:

- точно резолвить модель через `lamp_exact`;
- получать категории светильников;
- получать сферы через `sphere_categories`;
- получать объекты портфолио через `portfolio_by_sphere`.

Но отсутствует один детерминированный server-side path `lamp -> category -> sphere -> portfolio`. Из-за этого агент начинает собирать цепочку через несколько LLM/tool шагов, делает лишние `hybrid_search`, иногда уходит в wiki/shell fallback и может упираться в пользовательский timeout.

Триггер для работы:

- инцидент с запросом "примеры реализации объектов для светильника `R500-9-30-6-650LZD`" завершился успешным ответом в `core`, но слишком поздно для `bot`;
- triage показал, что `corp-db` как источник данных жив и быстрый, а деградация вызвана orchestration overhead;
- цепочка данных уже есть в БД, значит нужен специальный fast path, а не более сложный prompt.

Goals:

- Добавить один server-side RPC для сценария "найти примеры реализации по точной модели светильника".
- Убрать для этого сценария зависимость от `hybrid_search`, wiki и shell fallback.
- Вернуть компактный, объяснимый payload, пригодный для почти прямой трансляции в ответ пользователю.
- Сделать path быстрым, предсказуемым и наблюдаемым в logs/traces/metrics.
- Сохранить существующий public contract `corp_db_search`, добавив новый `kind`, а не новый разрозненный tool.

Non-goals for first implementation (v1)
---------------------------------------

- Полный rework agent loop и общей стратегии retrieval для всех domain-сценариев.
- Materialized view или отдельный denormalized cache для `lamp -> portfolio`.
- Автоматический rerank или ML-модель поверх найденных объектов портфолио.
- Решение для неточных/грязных model-code запросов без `lamp_exact`.
- Расширение сценария до документов, сертификатов, креплений и wiki-контекста в одном RPC.

Implementation considerations
-----------------------------

- Самый дешёвый и стабильный path здесь не semantic, а relational:
  - `lamp_exact` уже умеет точно найти модель;
  - `lamp_exact` уже возвращает `category_id` и `category_name`;
  - `sphere_categories` и `portfolio_by_sphere` уже опираются на таблицы `sphere_categories` и `portfolio`;
  - RFC-001 уже фиксирует связь `sphere_id -> category_id` и наличие сущностей `portfolio`, `spheres`, `sphere_categories`.
- Проблема не в отсутствии данных, а в отсутствии одного composed backend operation.
- Новый RPC должен быть idempotent, read-only и дешёвым:
  - без embeddings;
  - без `corp_hybrid_search`;
  - без shell;
  - без зависимости от внешних сервисов кроме PostgreSQL.
- Контракт должен быть достаточно компактным, чтобы не раздувать агентный контекст, в отличие от текущих больших payload-ов `hybrid_search`.
- Важно явно зафиксировать ambiguity:
  - у одной категории может быть несколько сфер;
  - у одной сферы может быть много объектов портфолио;
  - итоговый ответ должен показывать, по какой сфере найден каждый объект.

High-level behavior
-------------------

Новый retrieval path работает так:

1. Агент видит запрос вида:
   - "примеры реализации объектов для светильника `R500-9-30-6-650LZD`"
   - "портфолио для модели `LAD LED R500-9-30-6-650LZD`"
   - "какие объекты есть по светильнику `R500-9-30-6-650LZD`"
2. Вместо цепочки `lamp_exact -> hybrid_search -> sphere_categories -> portfolio_by_sphere -> wiki` агент вызывает один RPC:
   - `corp_db_search(kind=portfolio_examples_by_lamp, name=<точная модель>)`
3. `tools-api` внутри одного route:
   - точно резолвит лампу по логике `lamp_exact`;
   - извлекает `lamp_id`, `category_id`, `category_name`;
   - находит связанные сферы через `sphere_categories`;
   - находит объекты портфолио по этим сферам;
   - возвращает сгруппированный ответ.
4. Агент отвечает на основе компактного structured payload без дополнительных поисков.
5. Если модель не найдена или у категории нет сфер/портфолио, RPC возвращает `empty` с диагностируемыми `filters` и без перехода в дорогое fallback-поведение.

Happy path:

- точная модель найдена;
- категория определена;
- есть одна или несколько сфер;
- по хотя бы одной сфере есть объекты портфолио;
- ответ пользователю строится напрямую по `portfolio_examples[]`.

Edge cases:

- модель не найдена: `status=empty`, `reason=lamp_not_found`;
- категория у лампы отсутствует: `status=empty`, `reason=category_missing`;
- сферы для категории не найдены: `status=empty`, `reason=spheres_not_found`;
- объекты портфолио по найденным сферам не найдены: `status=empty`, `reason=portfolio_not_found`;
- для категории найдено несколько сфер: payload возвращает все, с отдельным полем `spheres[]`.

RPC design
----------

### Public contract

В `corp_db_search` добавляется новый `kind`:

- `portfolio_examples_by_lamp`

Новый kind остаётся частью существующего tool contract, а не отдельным tool:

- проще prompt-routing;
- единая авторизация;
- единая observability-модель;
- не нужно дублировать thin client в `core`.

### Request schema

Обязательные поля:

- `kind="portfolio_examples_by_lamp"`
- `name="<точное или почти точное имя модели>"`

Опциональные поля:

- `limit`
  - ограничивает число объектов портфолио в финальном ответе;
  - v1 default = `10`, hard cap = `30`
- `offset`
  - стандартный offset для списка `portfolio_examples[]`
- `fuzzy`
  - v1 default = `False`
  - может использоваться только на этапе match по category/sphere, но не должен заменять `lamp_exact`

Пример запроса:

```json
{
  "kind": "portfolio_examples_by_lamp",
  "name": "R500-9-30-6-650LZD",
  "limit": 10
}
```

### Response schema

Успешный ответ содержит:

- `status`
- `kind`
- `query`
- `filters`
- `lamp`
- `spheres`
- `portfolio_examples`

Поле `lamp`:

- краткая карточка лампы, достаточно компактная для ответа агенту:
  - `lamp_id`
  - `name`
  - `category_id`
  - `category_name`
  - `url`
  - `preview`
  - `agent_summary`
  - `facts`

Поле `spheres`:

- список найденных сфер для категории:
  - `sphere_id`
  - `sphere_name`

Поле `portfolio_examples`:

- плоский список объектов с привязкой к сфере:
  - `portfolio_id`
  - `name`
  - `url`
  - `group_name`
  - `image_url`
  - `sphere_id`
  - `sphere_name`

Пример успешного ответа:

```json
{
  "status": "success",
  "kind": "portfolio_examples_by_lamp",
  "query": "R500-9-30-6-650LZD",
  "filters": {
    "lamp_match": "exact",
    "category_id": 68,
    "category_name": "LAD LED R500-9 LZD",
    "sphere_count": 2,
    "portfolio_count": 7
  },
  "lamp": {
    "lamp_id": 1998,
    "name": "LAD LED R500-9-30-6-650LZD",
    "category_id": 68,
    "category_name": "LAD LED R500-9 LZD",
    "preview": "LAD LED R500-9 LZD | 557 Вт | 78537 лм | 30° | IP65 | 18.3 кг",
    "agent_summary": "Светильник LAD LED R500-9-30-6-650LZD. Мощность 557 Вт. Световой поток 78537 лм. Светораспределение 30°. IP65. Вес 18.3 кг."
  },
  "spheres": [
    {
      "sphere_id": 4,
      "sphere_name": "Нефтегазовый комплекс"
    },
    {
      "sphere_id": 7,
      "sphere_name": "Промышленность и склады"
    }
  ],
  "portfolio_examples": [
    {
      "portfolio_id": 102,
      "name": "Освещение резервуарного парка",
      "url": "https://...",
      "group_name": "Нефтегаз",
      "image_url": "https://...",
      "sphere_id": 4,
      "sphere_name": "Нефтегазовый комплекс"
    }
  ]
}
```

Пример empty-ответа:

```json
{
  "status": "empty",
  "kind": "portfolio_examples_by_lamp",
  "query": "R500-9-30-6-650LZD",
  "filters": {
    "reason": "portfolio_not_found",
    "lamp_id": 1998,
    "category_id": 68,
    "category_name": "LAD LED R500-9 LZD",
    "sphere_count": 2
  },
  "results": []
}
```

Route and SQL behavior
----------------------

### Route-level design

В [tools-api/src/routes/corp_db.py](/home/admin/totosha/tools-api/src/routes/corp_db.py) добавляется:

- новый `Literal` kind в `CorpDbSearchRequest`
- новый handler:
  - `_portfolio_examples_by_lamp(conn, req, limit, offset)`
- новый dispatch branch в основном route

В [tools-api/src/tools/corp_db.py](/home/admin/totosha/tools-api/src/tools/corp_db.py) добавляется новый `enum` value и описание для tool schema.

В [core/tools/corp_db.py](/home/admin/totosha/core/tools/corp_db.py) специальных изменений по transport layer не требуется, так как новый kind идёт через существующий HTTP client.

### SQL execution shape

v1 должен оставаться простым: без materialized view и без нового storage layer.

Рекомендуемый runtime порядок:

1. Вызвать shared internal helper exact lamp resolve:
   - использовать ту же логику normalize/match, что и `lamp_exact`
   - получить максимум один canonical lamp row
2. Если exact lamp row не найден:
   - вернуть `empty(reason=lamp_not_found)`
3. Если у lamp row нет `category_id`:
   - вернуть `empty(reason=category_missing)`
4. Запросить связанные сферы:
   - `categories -> sphere_categories -> spheres`
5. Если сферы не найдены:
   - вернуть `empty(reason=spheres_not_found)`
6. Запросить объекты портфолио:
   - `portfolio` по массиву `sphere_id`
7. Если объекты не найдены:
   - вернуть `empty(reason=portfolio_not_found)`
8. Собрать grouped response и вернуть `success`

Ориентировочная SQL-структура:

```sql
WITH resolved_lamp AS (
  SELECT l.lamp_id, l.name, l.category_id, l.category_name, l.url, l.preview, l.agent_summary, l.agent_facts
  FROM corp.v_catalog_lamps_agent l
  WHERE ...
  LIMIT 1
),
linked_spheres AS (
  SELECT s.sphere_id, s.name AS sphere_name
  FROM resolved_lamp rl
  JOIN corp.sphere_categories sc ON sc.category_id = rl.category_id
  JOIN corp.spheres s ON s.sphere_id = sc.sphere_id
),
portfolio_rows AS (
  SELECT p.portfolio_id, p.name, p.url, p.group_name, p.image_url, s.sphere_id, s.sphere_name
  FROM linked_spheres s
  JOIN corp.portfolio p ON p.sphere_id = s.sphere_id
)
SELECT ...
```

### Why not a materialized view in v1

Materialized view `lamp -> category -> sphere -> portfolio` теоретически ускорит runtime ещё сильнее, но в v1 не нужен:

- текущие SQL join’ы уже дешёвые;
- проблема в orchestration, а не в raw SQL cost;
- materialized view добавит lifecycle complexity:
  - refresh strategy
  - invalidation
  - extra debugging surface

Если позже этот сценарий станет top-N route по нагрузке, можно добавить:

- `v_lamp_portfolio_examples`
- или `mv_lamp_portfolio_examples`

без изменения public API.

Payload design
--------------

### Minimal agent-facing payload

Новый RPC не должен возвращать:

- полный список ламп категории;
- большие гибридные ranking payload;
- debug blobs по умолчанию;
- сырой SQL-shaped response.

Принцип:

- лампа одна;
- сферы короткие;
- портфолио компактное;
- всё, что нужно для ответа пользователю, уже есть в payload.

### Stable response model

Поля `lamp.preview`, `lamp.agent_summary`, `lamp.facts` должны повторно использовать existing allowlisted serializer из `lamp_exact`, а не собираться заново вручную.

Это важно, потому что:

- сериализация уже стабилизирована RFC-003;
- агент уже умеет работать с `preview/agent_summary/facts`;
- уменьшается риск drift между `lamp_exact` и новым RPC.

Agent routing
-------------

В [core/src/agent/system.txt](/home/admin/totosha/core/src/agent/system.txt) добавляется отдельное правило:

- если пользователь спрашивает про:
  - `примеры реализации`
  - `объекты`
  - `портфолио`
  - `где применялся`
  - `какие проекты были`
  и при этом в запросе есть точная модель светильника,
  сначала использовать `corp_db_search(kind=portfolio_examples_by_lamp, name=<model>)`

Новое правило должно стоять раньше generic retry/fallback цепочек по `hybrid_search`.

Желаемое поведение агента:

- не делать `hybrid_search`, если новый RPC дал `success`;
- не вызывать `sphere_categories` и `portfolio_by_sphere` руками, если новый RPC доступен;
- переходить к wiki только если новый RPC вернул `empty` и пользователь явно просит расширенный текстовый контекст.

Observability
-------------

### Metrics

Для нового RPC нужны отдельные метрики на route и фазах:

- route-level:
  - `http_server_duration_milliseconds{service_name="tools-api",route="/corp-db/search",kind="portfolio_examples_by_lamp"}` через existing metric model
- phase-level:
  - `corp_db_search_phase_duration_milliseconds{kind="portfolio_examples_by_lamp",phase="lamp_exact"}`
  - `corp_db_search_phase_duration_milliseconds{kind="portfolio_examples_by_lamp",phase="sphere_lookup"}`
  - `corp_db_search_phase_duration_milliseconds{kind="portfolio_examples_by_lamp",phase="portfolio_lookup"}`
  - `corp_db_search_phase_duration_milliseconds{kind="portfolio_examples_by_lamp",phase="response_build"}`

### Trace spans

В `tools-api` внутри `api.request` должны появиться child spans:

- `corp_db.portfolio_examples.lamp_exact`
- `corp_db.portfolio_examples.sphere_lookup`
- `corp_db.portfolio_examples.portfolio_lookup`

В `core` trace на `tool.corp_db_search` уже должен позволять видеть этот вызов как отдельный tool path.

### Logs

В logs должны попадать:

- `request_id`
- `kind=portfolio_examples_by_lamp`
- `lamp_id`
- `category_id`
- `sphere_count`
- `portfolio_count`
- `status`

Это нужно, чтобы triage по `request_id` быстро показывал:

- была ли найдена лампа;
- сломалась ли цепочка на сферах;
- или просто нет портфолио по найденным сферам.

Error handling and UX
---------------------

Пользовательское поведение:

- если модель подтверждена, но объектов нет, ответ должен быть честным:
  - модель найдена;
  - категория/сферы определены;
  - в портфолио подходящие объекты не найдены
- если модель не найдена, ответ не должен притворяться, что "объектов нет"; он должен говорить именно про отсутствие модели

Операторское поведение:

- `empty` не считается ошибкой;
- `error` используется только для transport/DB/runtime failures;
- empty-path должен быть диагностируем через `filters.reason`

v1 error mapping:

- `lamp_not_found` -> `empty`
- `category_missing` -> `empty`
- `spheres_not_found` -> `empty`
- `portfolio_not_found` -> `empty`
- SQL/runtime exception -> `error`

Update cadence / Lifecycle
--------------------------

- Новый RPC разворачивается вместе с prompt-routing изменением.
- После deploy запускается ручной smoke на типовом сценарии:
  - exact model -> portfolio examples
  - exact model without portfolio
  - unknown model
- Если позже будет введён denormalized view, public contract нового kind не меняется.

Future-proofing
---------------

- Позже можно добавить `search_strategy`:
  - `exact_chain`
  - `exact_chain_then_related_evidence`
- Можно добавить optional `group_by="sphere"` для UI/API потребителей без breaking change.
- Можно добавить `include_related_categories=true`, если появится потребность искать не только по прямой category, но и по семейству/серии.
- Можно вынести chain в SQL function или DB RPC, если потребуется переиспользование вне `tools-api`.
- Можно добавить materialized view, если route станет высоконагруженным.

Implementation outline
----------------------

1. `tools-api`: new kind and route branch
   - добавить `portfolio_examples_by_lamp` в schema enum
   - добавить dispatch в main `/corp-db/search`

2. `tools-api`: backend chain handler
   - выделить reusable helper exact lamp resolve
   - реализовать `_portfolio_examples_by_lamp(...)`
   - собрать compact response model

3. `tools-api`: observability
   - добавить phase spans
   - добавить phase metrics
   - логировать `sphere_count` и `portfolio_count`

4. `core`: tool schema propagation
   - обновить tool definition в `tools/corp_db.py`
   - при необходимости обновить tests на сериализацию

5. `core`: agent routing
   - обновить `system.txt` под новый special-case path
   - запретить уход в `hybrid_search` при success нового RPC

6. Tests and smoke
   - unit/integration tests на success/empty/error paths
   - manual smoke на реальном сценарии с моделью `R500-9-30-6-650LZD`

Testing approach
----------------

Unit:

- handler возвращает `empty(reason=lamp_not_found)`, если exact lamp resolve пустой
- handler возвращает `empty(reason=spheres_not_found)`, если у категории нет сфер
- handler возвращает `empty(reason=portfolio_not_found)`, если сферы есть, а портфолио пусто
- handler возвращает `success` с корректным `lamp/category/spheres/portfolio_examples`

Integration:

- `POST /corp-db/search` с `kind=portfolio_examples_by_lamp` возвращает корректный JSON contract
- `request_id` проходит через logs/traces
- phase spans и phase metrics видны в observability stack

Manual:

- запрос:
  - "примеры реализации объектов для светильника R500-9-30-6-650LZD"
- ожидаемое поведение:
  - один вызов `corp_db_search(kind=portfolio_examples_by_lamp, ...)`
  - без `hybrid_search`
  - без wiki
  - без shell

Latency validation:

- `tools-api /corp-db/search kind=portfolio_examples_by_lamp` должен быть ближе к обычному SQL path, а не к `hybrid_search`
- целевой порядок времени для warm path:
  - `tools-api` p95 < `500 ms`
  - `core` tool call p95 < `1 s`

Acceptance criteria
-------------------

- В `corp_db_search` появляется новый `kind=portfolio_examples_by_lamp`.
- Запрос с точной моделью светильника возвращает один compact response без вызова `hybrid_search`.
- Новый RPC server-side проходит цепочку `lamp -> category -> sphere -> portfolio` внутри одного backend operation.
- В успешном ответе присутствуют `lamp`, `spheres`, `portfolio_examples`.
- В empty-path присутствует `filters.reason` с одной из фиксированных причин:
  - `lamp_not_found`
  - `category_missing`
  - `spheres_not_found`
  - `portfolio_not_found`
- Агент использует новый RPC для запросов про "примеры реализации / объекты / портфолио" при наличии точной модели.
- Для этого сценария агент не вызывает wiki/shell fallback, если новый RPC дал `success`.
- В logs/traces/metrics можно увидеть новый path по `request_id`.
- Warm-path latency нового RPC существенно ниже текущего многошагового agent orchestration path.
