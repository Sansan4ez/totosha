RFC-008 Application-Driven Lighting Recommendation Fast Path
=============================================================

Status
------

Proposed

Date
----

2026-04-05

Context and motivation
----------------------

Разбор проблемных ответов от `2026-04-03` показал, что сценарии вида:

- "подбери мощный светильник для карьера";
- "подбери освещение для спортивного стадиона";
- "подбери освещение для аэропорта и площадки стоянок авиапарка";

ломаются не из-за отсутствия корпоративных данных, а из-за отсутствия детерминированного retrieval path для broad-object запросов.

На момент инцидента в системе уже были:

- сферы применения с URL на страницы сайта;
- связи `sphere -> category`;
- карточки светильников с `url`, `image_url`, `agent_summary`, `facts`;
- объекты портфолио со ссылками и изображениями.

Но агент не использовал эти связи как обязательный pipeline и вместо этого отвечал из общего `hybrid_search`-шума. Это привело к заметным сбоям качества:

- для стадиона был предложен `LAD LED LINE-1000-10-40B`, то есть заведомо слабый и нерелевантный сценарий для мощного спортивного прожекторного освещения;
- для карьера агент ушёл в частный `R320 Ex`-вариант без внятного обоснования, без ссылок на сферу, без альтернативных серий и без примеров реализации;
- пользователь не получил ни ссылок на карточки, ни изображения, ни URL страниц категорий, ни ссылок на релевантные объекты портфолио, хотя эти данные уже были в БД.

Текущий backend уже умеет по отдельности:

- искать сущности и кандидатов через `hybrid_search`;
- получать категории по сфере через `sphere_categories`;
- получать светильники по категории через `category_lamps`;
- получать объекты портфолио по сфере через `portfolio_by_sphere`.

Но отсутствуют:

- один server-side path для сценария `object query -> resolved application sphere -> categories -> lamps -> portfolio`;
- жёсткое routing-правило для object-based подбора;
- compact answer contract, который заставляет агент выводить ссылки, изображения и 1 уточняющий вопрос;
- ranking policy, которая отделяет broad-object подбор от свободного fuzzy-поиска по всему каталогу.

Goals
-----

- Добавить детерминированный fast path для подбора светильников по объекту / сфере применения.
- Убрать зависимость качества broad-object ответов от случайного результата `hybrid_search`.
- Возвращать компактный, agent-friendly payload, уже содержащий:
  - распознанную сферу;
  - подходящие категории;
  - рекомендованные светильники;
  - ссылки на сайт;
  - изображения;
  - примеры объектов портфолио.
- Сделать первый ответ быстрым и полезным без лишних tool-итераций.
- Стандартизовать answer contract: короткая рекомендация, материалы для просмотра, затем один уточняющий вопрос.
- Добавить bench и observability, чтобы регрессии по таким запросам не возвращались.

Non-goals for first implementation (v1)
---------------------------------------

- Полный rework общего agent loop для всех типов каталоговых вопросов.
- Автоматический светотехнический расчёт, подбор по люксам и нормативам.
- Геометрический расчёт схемы расстановки прожекторов на объекте.
- ML-based reranking поверх всех сущностей каталога.
- Полная замена существующих `sphere_categories`, `category_lamps`, `portfolio_by_sphere`.
- Автоматическая генерация rich Telegram media groups на backend-слое.

Implementation considerations
-----------------------------

- Для object-based подбора cheapest and safest path является не semantic retrieval, а compositional relational path.
- Бизнес-логика здесь начинается не с модели светильника, а с application intent:
  - стадион;
  - карьер;
  - аэропорт / перрон;
  - склад;
  - АЗС;
  - нефтегаз;
  - тяжёлые условия эксплуатации.
- У broad-object запросов почти всегда есть business expectation по классу решения:
  - стадион -> мощные прожекторы / high-power sport series;
  - карьер -> тяжёлые условия эксплуатации / высокая мощность / наружное применение;
  - аэропорт -> мощные наружные прожекторы / мачты / большие площадки.
- Поэтому broad-object path должен:
  - сначала резолвить application sphere;
  - затем работать только внутри narrowed subset, а не по всему индексу.
- Первый ответ должен быть compact, но не "голый":
  - пользователю сразу нужны 2-3 подходящие серии или модели;
  - хотя бы 1-2 ссылки;
  - хотя бы 1 иллюстрация/изображение;
  - хотя бы 1 пример реализованного объекта;
  - 1 уточняющий вопрос, который помогает сделать второй ответ точнее.
- Контракт результата должен быть компактнее текущего общего `hybrid_search`, иначе агент снова начнёт тратить итерации на "осмысление" большого retrieval dump.

Observed root causes
--------------------

### 1. No first-class routing for broad-object recommendation

В системном prompt уже есть special-case path для:

- `lamp_exact`;
- `portfolio_examples_by_lamp`;
- company facts.

Но нет аналогичного special-case path для вопросов вида:

- "подбери освещение для стадиона";
- "подбери светильник для карьера";
- "что предложить для аэропорта".

В результате модель использует общий `hybrid_search`, хотя сценарий должен идти по более жёсткой business цепочке.

### 2. Existing toolset is composable but not composed

Текущие tools уже позволяют собрать нужный ответ:

- `sphere_categories`;
- `category_lamps`;
- `portfolio_by_sphere`.

Но это требует нескольких последовательных шагов, которые агент должен сам выбрать и правильно склеить. Для broad-object вопросов это слишком хрупко.

### 3. Search index metadata is not rich enough for final presentation

Для `category` и `portfolio` в search index не хватает presentation-friendly metadata:

- у category в metadata нет `image_url`;
- у portfolio в metadata нет `image_url`.

Из-за этого даже при успешном резолве агенту нечего вставлять в ответ, кроме названия и URL.

### 4. Category traversal breaks on parent categories

`sphere_categories` возвращает категории сферы, включая родительские узлы. Но `category_lamps` фактически ищет по `l.category_name`, то есть по leaf category rows каталога. Поэтому связка:

- `sphere_categories -> category_lamps`

частично возвращает `empty` для категорий вроде:

- `LAD LED R500-10`;
- `LAD LED R500 SPORT`;
- `LAD LED R700 HT`.

Это делает текущую multi-step цепочку нестабильной без дополнительных правил.

### 5. There is no domain synonym and typo normalization layer

Object-based формулировки часто приходят в непрямом виде:

- "карьерна" вместо "карьера";
- "перрон", "стоянка авиапарка", "аэропортовый комплекс";
- "арена", "спорткомплекс", "футбольное поле" вместо "стадион".

Без нормализации search path либо уходит в semantic fallback, либо ловит нерелевантные сущности.

### 6. No answer contract for links, images, and clarifying question

Даже если backend возвращает `url` и `image_url` для lamp rows, нигде не зафиксировано правило:

- broad-object answer must include direct links;
- must include at least one visual reference;
- must include at least one relevant portfolio example;
- must end with one clarifying question.

Из-за этого полезные данные остаются в payload, но не доходят до пользователя.

Analysis of `docs/questions.md`
-------------------------------

Файл [docs/questions.md](/home/admin/totosha/docs/questions.md) полезен как источник реальных формулировок от внутренних пользователей. Но для benchmark по application-driven retrieval его нужно разбирать по intent, а не включать вопросы "как есть" в один общий набор.

### Questions that fit application recommendation

Следующие вопросы из ТЗ хорошо соответствуют новому path `application_recommendation`, потому что они начинаются от объекта, среды или сценария применения, а не от точной модели или документа:

- [docs/questions.md](/home/admin/totosha/docs/questions.md):7
  - "Какой светильник применить на складе?"
  - canonical intent: warehouse / storage lighting
  - expected resolved sphere: складские помещения
- [docs/questions.md](/home/admin/totosha/docs/questions.md):9
  - "Какие светильники подходят для кабинетов?"
  - canonical intent: office / cabinet lighting
  - expected resolved sphere: офисное, торговое, ЖКХ и АБК освещение
- [docs/questions.md](/home/admin/totosha/docs/questions.md):11
  - "У вас имеются светильники для высоких пролетов?"
  - canonical intent: high-bay / industrial hall lighting
  - expected resolved sphere: промышленное освещение или смежный industrial subset
- [docs/questions.md](/home/admin/totosha/docs/questions.md):13
  - "Объект стадион, какие прожекторы применить?"
  - canonical intent: stadium / sports high-power lighting
  - expected resolved sphere: спортивное и освещение высокой мощности
- [docs/questions.md](/home/admin/totosha/docs/questions.md):29
  - "Какой светильник использовать для агрессивных сред?"
  - canonical intent: harsh / aggressive environment lighting
  - expected resolved sphere: тяжёлые условия эксплуатации или иной explicit heavy-duty path

Эти вопросы подходят для golden set, потому что проверяют ровно тот класс поведения, который описывает данный RFC:

- корректный резолв application sphere;
- сужение поиска до релевантного subset;
- возврат не одной случайной модели, а объяснимой рекомендации;
- вывод ссылок, изображений и, где уместно, портфолио.

### Questions that should not be mixed into this benchmark

Следующие вопросы из того же ТЗ не являются application-recommendation сценариями и должны оставаться в других benchmark baskets:

- [docs/questions.md](/home/admin/totosha/docs/questions.md):5
  - "У вас есть взрывозащита?"
  - intent: feature / catalog capability lookup
- [docs/questions.md](/home/admin/totosha/docs/questions.md):15
  - "Какой вес у светильников серии LAD LED R500"
  - intent: exact-model or exact-series fact lookup
- [docs/questions.md](/home/admin/totosha/docs/questions.md):17
  - "У вас есть светильники с БАП?"
  - intent: feature / accessory lookup
- [docs/questions.md](/home/admin/totosha/docs/questions.md):21
  - "Нужна схема подключения БАП к светильнику"
  - intent: document lookup
- [docs/questions.md](/home/admin/totosha/docs/questions.md):23
  - "Какой кронштейн необходим для установки ваших светильников?"
  - intent: mounting / compatibility lookup
- [docs/questions.md](/home/admin/totosha/docs/questions.md):27
  - "На каких приборах устанавливают закаленное стекло?"
  - intent: series capability lookup
- [docs/questions.md](/home/admin/totosha/docs/questions.md):31
  - "Подскажите информацию по пусковым токам"
  - intent: technical document / characteristic lookup

Причина разделения простая: если смешать эти intents с object-based подбором, benchmark перестанет проверять именно fast path по сфере применения и начнёт штрафовать/поощрять unrelated retrieval behavior.

### Additional signal from sales requirements

Вопрос из блока продаж:

- [docs/questions.md](/home/admin/totosha/docs/questions.md):49
  - "Реализованные объекты (со структурированием на складские, промышленные, уличные, офисные, спортивные)"

не является прямым пользовательским вопросом на подбор модели, но он подтверждает, что для бизнеса критичен ещё один adjacent scenario:

- `portfolio_by_application`

То есть для bench имеет смысл проверять не только recommendation path, но и способность системы быстро показать объекты портфолио в разрезе сферы:

- складские;
- промышленные;
- уличные;
- офисные;
- спортивные.

Этот сценарий связан с данным RFC, но не идентичен ему. Поэтому в benchmark его лучше учитывать как отдельный sibling track, а не как часть базовой проверки `application_recommendation`.

High-level behavior
-------------------

После внедрения RFC broad-object подбор работает так:

1. Пользователь задаёт запрос вида:
   - "подбери освещение для спортивного стадиона";
   - "подбери мощный светильник для открытого карьера";
   - "подбери освещение для аэропорта и площадки стоянок авиапарка".
2. Агент распознаёт это как `application_recommendation` intent.
3. Вместо свободного `hybrid_search` по всему каталогу агент вызывает один deterministic backend operation:
   - `corp_db_search(kind=application_recommendation, query=<user text>)`
4. Backend:
   - нормализует query;
   - резолвит application sphere;
   - выбирает связанные категории;
   - находит top lamp candidates внутри этих категорий;
   - добирает примеры портфолио по resolved sphere;
   - возвращает compact payload.
5. Агент строит короткий, но насыщенный ответ:
   - какая сфера распознана;
   - 2-3 серии / модели;
   - ссылки на карточки;
   - 1-2 изображения;
   - 1-2 объекта портфолио;
   - 1 уточняющий вопрос.

Happy path:

- sphere resolved confidently;
- there are linked categories;
- there are lamps in those categories;
- there are portfolio examples for the same sphere;
- answer is produced in one tool call and one response.

Edge cases:

- application sphere is ambiguous:
  - backend returns top 2 spheres with confidence;
  - agent asks a single disambiguation question.
- sphere resolved but lamp candidates are too broad:
  - backend returns categories and asks for one missing business parameter;
  - agent does not hallucinate final recommendation.
- no direct sphere match:
  - backend falls back to domain synonym map and related evidence;
  - only after that returns `empty`.

RPC design
----------

### New public contract

В `corp_db_search` добавляется новый `kind`:

- `application_recommendation`

Это остаётся частью существующего tool-а, а не отдельным новым tool:

- проще prompt-routing;
- единая авторизация;
- единый thin client;
- единая observability-модель.

### Request schema

Required:

- `kind="application_recommendation"`
- `query="<user broad-object query>"`

Optional:

- `limit_categories`
  - default `5`, hard cap `10`
- `limit_lamps`
  - default `6`, hard cap `12`
- `limit_portfolio`
  - default `3`, hard cap `6`
- `power_class`
  - optional enum for future narrowing:
    - `standard`
    - `high_power`
    - `ultra_high_power`
- `mounting_type`
- `explosion_protected`
- `beam_pattern`
- `fuzzy`
  - default `true` for intent normalization only

Example:

```json
{
  "kind": "application_recommendation",
  "query": "подбери освещение для спортивного стадиона",
  "limit_categories": 4,
  "limit_lamps": 6,
  "limit_portfolio": 3
}
```

### Response schema

Successful response contains:

- `status`
- `kind`
- `query`
- `filters`
- `resolved_application`
- `categories`
- `recommended_lamps`
- `portfolio_examples`
- `follow_up_question`

Field `resolved_application`:

- `sphere_id`
- `sphere_name`
- `url`
- `image_url`
- `confidence`
- `resolution_strategy`

Field `categories`:

- `category_id`
- `category_name`
- `url`
- `image_url`
- `reason`

Field `recommended_lamps`:

- `lamp_id`
- `name`
- `category_id`
- `category_name`
- `url`
- `image_url`
- `preview`
- `agent_summary`
- `facts`
- `recommendation_reason`

Field `portfolio_examples`:

- `portfolio_id`
- `name`
- `url`
- `image_url`
- `group_name`
- `sphere_id`
- `sphere_name`

Field `follow_up_question`:

- short string with exactly one business clarifier

Example:

```json
{
  "status": "success",
  "kind": "application_recommendation",
  "query": "подбери освещение для спортивного стадиона",
  "filters": {
    "resolution_strategy": "direct_sphere_match",
    "category_count": 4,
    "lamp_count": 3,
    "portfolio_count": 2
  },
  "resolved_application": {
    "sphere_id": 6,
    "sphere_name": "Спортивное и освещение высокой мощности",
    "url": "https://ladzavod.ru/catalog/sportivnoe-osveshchenie",
    "image_url": "https://...",
    "confidence": 0.98,
    "resolution_strategy": "direct_sphere_match"
  },
  "categories": [
    {
      "category_id": 169,
      "category_name": "LAD LED R500 SPORT",
      "url": "https://ladzavod.ru/catalog/sportivnoe-osveshchenie-lad-led-r500-sport",
      "image_url": "https://...",
      "reason": "specialized_sport_series"
    },
    {
      "category_id": 96,
      "category_name": "LAD LED R700-10 ST",
      "url": "https://ladzavod.ru/catalog/r700-10-st",
      "image_url": "https://...",
      "reason": "high_power_stadium_projection"
    }
  ],
  "recommended_lamps": [
    {
      "lamp_id": 1855,
      "name": "LAD LED R500-10-10-6-500L",
      "url": "https://ladzavod.ru/catalog/r500-10-500w/lad-led-r500-10-10-6-500l",
      "image_url": "https://...",
      "recommendation_reason": "entry_high_power_outdoor_projector"
    }
  ],
  "portfolio_examples": [
    {
      "portfolio_id": "portfolio:...",
      "name": "Освещение стадиона «Газовик»",
      "url": "https://ladzavod.ru/portfolio/sportivnoe-osveshchenie/osveshchenie-stadiona-gazovik",
      "image_url": "https://..."
    }
  ],
  "follow_up_question": "Для какой высоты мачт нужен подбор: до 20 м или выше?"
}
```

Application resolution layer
----------------------------

### Domain synonym map

v1 вводит explicit application lexicon для top business scenarios.

Examples:

- `стадион`, `арена`, `спорткомплекс`, `футбольное поле`, `спортивная арена`
  - -> `Спортивное и освещение высокой мощности`
- `карьер`, `открытый карьер`, `ГОК`, `рудник`, `добыча`, `шахта`
  - -> `Тяжелые условия эксплуатации`
- `аэропорт`, `перрон`, `стоянка авиапарка`, `аэропортовый комплекс`
  - -> `Наружное, уличное и дорожное освещение` + high-power boost

The synonym map is deterministic and versioned in code/config.

### Resolution order

Backend resolves application in this order:

1. direct normalized sphere-name match;
2. deterministic synonym map match;
3. related-evidence search over sphere/portfolio entities;
4. ambiguity result;
5. `empty`.

The first successful stage becomes authoritative.

### Ambiguity handling

Если две сферы близки по score, backend не выдаёт псевдо-точную рекомендацию. Он возвращает:

- top 2 resolved applications;
- short ambiguity reason;
- one follow-up question.

Это лучше, чем случайный выбор одной серии.

Category and lamp candidate generation
-------------------------------------

### Leaf-category requirement

Broad-object recommendation должен работать с выдачей реальных lamp rows, а не только родительских category labels.

v1 делает одно из двух:

1. `sphere_categories` начинает возвращать признак `is_leaf` и `image_url`;
2. новый RPC сам внутри backend разворачивает родительские узлы в leaf categories.

Целевое поведение:

- в recommendation path в `recommended_lamps` попадают только категории, из которых реально можно получить lamp rows.

### Ranking rules

v1 вводит explicit rule-based ranking поверх narrowed subset.

For sports stadium:

- boost:
  - `high power`;
  - `IP67`;
  - `Лира`;
  - sport / ST high-power categories;
- penalize:
  - low-power lamps;
  - office / indoor categories;
  - architectural linear products.

For open pit / quarry:

- boost:
  - heavy-duty sphere;
  - outdoor / high-power;
  - high IP;
  - wide operating temperature range;
- penalize:
  - explosion protection unless explicitly requested;
  - low-power or indoor products.

For airport apron / parking stand:

- boost:
  - high-power projector categories;
  - large-area outdoor suitability;
  - lira mounting;
  - higher beam-pattern flexibility.

### Candidate count

First response should stay compact:

- `2-4` categories max;
- `2-3` recommended lamps max;
- `1-2` portfolio examples max for the first answer;
- one follow-up question only.

Presentation contract for the agent
-----------------------------------

После успешного `application_recommendation` агент должен отвечать по фиксированному шаблону.

Required elements:

1. Short opening:
   - "Для такого объекта ориентируюсь на сферу `<sphere_name>`."
2. Recommendation block:
   - `2-3` модели;
   - мощность;
   - IP;
   - тип монтажа;
   - короткое business reason.
3. Materials block:
   - прямые ссылки на карточки;
   - по возможности изображения.
4. Portfolio block:
   - `1-2` объекта со ссылками.
5. One follow-up question.

Forbidden behaviors after successful response payload:

- не уходить в общий `hybrid_search`;
- не уходить в `doc_search`;
- не спрашивать сразу 3-4 уточнения;
- не отвечать одной моделью без ссылок и альтернатив;
- не предлагать внутренние/архитектурные серии в сценариях high-power, если payload уже дал подходящие outdoor candidates.

Data model and indexing changes
-------------------------------

### Tools-api changes

In [tools-api/src/routes/corp_db.py](/home/admin/totosha/tools-api/src/routes/corp_db.py):

- add `kind="application_recommendation"` to request schema;
- add route branch in main dispatcher;
- add helper for application resolution;
- add helper for leaf category expansion;
- add ranking function for lamp candidates;
- add compact serializer for recommendation payload.

### Search-index changes

In [db/search_docs.py](/home/admin/totosha/db/search_docs.py):

- add `image_url` to `category` metadata;
- add `image_url` to `portfolio` metadata;
- optionally add normalized application aliases to sphere/category documents.

### Catalog and relation support

If needed, add one helper view or query path that resolves:

- parent category -> leaf categories -> lamps

without requiring the agent to understand catalog hierarchy.

This can remain internal to tools-api in v1.

Prompt and skill changes
------------------------

In [core/src/agent/system.txt](/home/admin/totosha/core/src/agent/system.txt):

- add a new special-case rule for broad-object recommendation;
- require `application_recommendation` before generic `hybrid_search` for prompts like:
  - "для стадиона";
  - "для карьера";
  - "для аэропорта";
  - "для складов";
  - "для АЗС".

In [shared_skills/skills/corp-pg-db/SKILL.md](/home/admin/totosha/shared_skills/skills/corp-pg-db/SKILL.md):

- document the new `kind`;
- define the output expectation for links, images, portfolio, and follow-up question;
- document the "do not continue searching after successful application recommendation" rule.

Observability
-------------

New metrics and spans are needed for the new fast path.

Route-level:

- `http_server_duration_milliseconds{service_name="tools-api",route="/corp-db/search",kind="application_recommendation"}`

Phase-level:

- `corp_db_search_phase_duration_milliseconds{kind="application_recommendation",phase="application_resolution"}`
- `corp_db_search_phase_duration_milliseconds{kind="application_recommendation",phase="category_resolution"}`
- `corp_db_search_phase_duration_milliseconds{kind="application_recommendation",phase="lamp_ranking"}`
- `corp_db_search_phase_duration_milliseconds{kind="application_recommendation",phase="portfolio_lookup"}`
- `corp_db_search_phase_duration_milliseconds{kind="application_recommendation",phase="response_build"}`

Structured logs should include:

- resolved sphere id/name;
- category count;
- lamp count;
- portfolio count;
- resolution strategy;
- ambiguity flag.

Bench and test strategy
-----------------------

### Unit tests

Add tools-api tests for:

- direct sphere match for stadium;
- synonym match for quarry / `карьер`;
- typo-tolerant normalization for `карьерна`;
- ambiguity response;
- leaf category expansion;
- payload includes `url` and `image_url`;
- follow-up question is present.

### Integration tests

Add end-to-end tests that verify:

- agent routes broad-object prompts to `application_recommendation`;
- after successful payload agent does not call extra retrieval tools;
- final answer includes at least one link and one portfolio example.

### Bench dataset

Add new golden cases:

- `tech-020-application-stadium-high-power`
- `tech-021-application-open-pit-quarry`
- `tech-022-application-airport-apron`
- `tech-023-application-quarry-typo`

Также benchmark должен включать вопросы, напрямую происходящие из ТЗ [docs/questions.md](/home/admin/totosha/docs/questions.md), если они соответствуют application intent.

Recommended benchmark additions from `docs/questions.md`:

- `tech-024-application-warehouse`
  - source question:
    - [docs/questions.md](/home/admin/totosha/docs/questions.md):7
  - user wording:
    - "Какой светильник применить на складе?"
  - expected behavior:
    - resolve warehouse sphere;
    - recommend warehouse / industrial candidates;
    - include product links;
    - ask one narrowing question such as mounting height or IP requirement.
- `tech-025-application-office-cabinets`
  - source question:
    - [docs/questions.md](/home/admin/totosha/docs/questions.md):9
  - user wording:
    - "Какие светильники подходят для кабинетов?"
  - expected behavior:
    - resolve office/cabinet lighting;
    - do not return stadium/high-power/outdoor series;
    - include at least one category or product link;
    - ask one narrowing question about ceiling type or form factor.
- `tech-026-application-high-bay`
  - source question:
    - [docs/questions.md](/home/admin/totosha/docs/questions.md):11
  - user wording:
    - "У вас имеются светильники для высоких пролетов?"
  - expected behavior:
    - resolve industrial/high-bay scenario;
    - bias to industrial powerful luminaires;
    - no office / decorative products;
    - ask one clarifier about installation height.
- `tech-027-application-stadium-projectors`
  - source question:
    - [docs/questions.md](/home/admin/totosha/docs/questions.md):13
  - user wording:
    - "Объект стадион, какие прожекторы применить?"
  - note:
    - this can replace or specialize `tech-020-application-stadium-high-power`
  - expected behavior:
    - resolve sports high-power sphere;
    - recommend projector-style models only;
    - include at least one portfolio example for sports lighting.
- `tech-028-application-aggressive-environment`
  - source question:
    - [docs/questions.md](/home/admin/totosha/docs/questions.md):29
  - user wording:
    - "Какой светильник использовать для агрессивных сред?"
  - expected behavior:
    - resolve heavy-duty / harsh-environment scenario;
    - prefer appropriate heavy-duty families;
    - ask one clarifier about chemistry / temperature / explosion-protection requirement.

Recommended sibling benchmark additions for portfolio-by-sphere:

- `sales-002-portfolio-warehouse`
- `sales-003-portfolio-industrial`
- `sales-004-portfolio-street`
- `sales-005-portfolio-office`
- `sales-006-portfolio-sports`

These should validate:

- fast retrieval of portfolio grouped by application sphere;
- presence of portfolio links;
- presence of portfolio images when available;
- no fallback to generic document search.

Checks should verify:

- selected source = `corp_db`;
- no `doc_search` / shell path;
- answer contains at least one product URL;
- answer contains at least one portfolio URL;
- answer contains a clarifying question;
- no obviously low-power indoor lamp for high-power scenarios.

For `docs/questions.md`-derived cases the benchmark should additionally verify intent separation:

- warehouse / office / high-bay cases do not resolve into sports or airport high-power spheres;
- stadium cases do not return indoor low-power linear products;
- aggressive-environment cases do not return office or decorative products;
- non-application technical questions remain outside this benchmark track.

Implementation outline
----------------------

1. Extend `corp_db_search` schema with `application_recommendation`.
2. Implement deterministic application resolver with synonym normalization.
3. Add backend traversal:
   - sphere -> categories -> leaf categories -> lamps -> portfolio.
4. Add rule-based candidate ranking per application class.
5. Extend payload with links, images, and follow-up question.
6. Enrich category/portfolio metadata with `image_url`.
7. Update system prompt and `corp-pg-db` skill.
8. Add unit/integration/bench coverage.
9. Roll out behind existing tool contract without adding a new tool name.

Migration and rollout
---------------------

Rollout should be incremental:

1. backend support and tests;
2. prompt / skill routing update;
3. bench coverage;
4. production observation for real broad-object prompts;
5. optional follow-up refinement of ranking rules.

Rollback is simple:

- prompt can stop calling the new kind;
- old generic retrieval path remains available.

Future-proofing
---------------

This RFC deliberately scopes v1 to deterministic recommendation for top broad-object scenarios.

Later extensions can add:

- `application_recommendation` with explicit business filters such as:
  - installation height;
  - beam angle;
  - target power band;
  - mounting type;
  - hazardous area / explosion protection;
- grouped answer payload by category;
- ready-made Telegram media cards;
- object-specific recommendation templates by industry.

Acceptance criteria
-------------------

- В `corp_db_search` появляется `kind="application_recommendation"`.
- Для запроса "подбери освещение для спортивного стадиона" backend возвращает resolved sport sphere, подходящие категории, recommended lamps, portfolio examples, links, and images.
- Для запроса "подбери мощный светильник для карьера" path не уходит в случайный общий retrieval по всему каталогу и не возвращает офисные / indoor кандидаты.
- Для broad-object high-power кейсов первый ответ содержит минимум:
  - одну ссылку на карточку светильника;
  - одну ссылку на портфолио;
  - один уточняющий вопрос.
- После успешного `application_recommendation` агент не вызывает `hybrid_search`, `doc_search`, `run_command`, `list_directory`, `read_file`.
- Search-index metadata для category и portfolio включает достаточно полей для выдачи ссылок и изображений.
- Bench получает не менее 4 новых application-recommendation кейсов и ловит регрессии по ссылкам, портфолио и маршрутизации.
