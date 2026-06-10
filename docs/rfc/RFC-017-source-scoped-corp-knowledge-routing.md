RFC-017 Source-Scoped Corp Knowledge Routing
============================================

Status
------

Proposed

Date
----

2026-04-08

Related RFCs
------------

- RFC-006 и RFC-014 правильно усиливали приоритет `corp_db_search`, но всё ещё описывали routing слишком intent-centric.
- Этот RFC фиксирует желаемую предметную модель: один corporate KB substrate с route-ами по `source_file`.

Context and motivation
----------------------

Текущий runtime пытается распознавать company facts через узкие keyword sets и high-level route cards. Это не соответствует фактической структуре corporate knowledge.

Целевая модель, которую нужно зафиксировать:

- существует один основной KB substrate в corporate DB;
- routing к нему идёт через `source_file`-scoped routes;
- внутри одного route family LLM сначала должна сделать один запрос в authoritative route;
- только если route не дал достаточного ответа, можно идти в другие routes.

Problem statement
-----------------

Сейчас routing знает слишком мало о реальных доменах данных. В результате:

- phrasing variations ломают попадание в нужный route;
- company/common queries случайно смешиваются с lamp retrieval;
- search по Luxnet и search по нормам освещённости не описаны как самостоятельные authoritative families;
- fallback в другие routes может случиться раньше, чем исчерпан основной KB route.

Goals
-----

- Зафиксировать source-scoped route families поверх одного corporate KB substrate.
- Убрать зависимость от узких `_company_fact_intent_type()` эвристик как единственного входа в routing.
- Сделать первый retrieval attempt всегда route-authoritative и source-scoped.
- Исключить lamp filters и другие нерелевантные structured filters из таких route families.
- Сделать routing понятным для voice, paraphrase и свободной формулировки.

Non-goals
---------

- Полная замена `corp_db_search`.
- Отдельный embeddings-router.
- Перенос `doc_search` в corp DB.

Authoritative route families
----------------------------

### 1. `corp_kb.company_common`

Authoritative source:

- один и тот же KB substrate;
- фильтр по `source_file=common_information_about_company.md`

Эта route family покрывает вопросы о:

- компании;
- доступных сериях светильников;
- качестве продукции и комплектующих;
- сертификации, декларациях, независимых экспертизах;
- новостях компании;
- правовой информации;
- контактах;
- реквизитах;
- социальных сетях;
- прайсе;
- расчёте освещения;
- классификации пожароопасных зон.

### 2. `corp_kb.luxnet`

Authoritative source:

- тот же KB substrate;
- фильтр по `source_file=about_Luxnet.md`

Покрывает:

- всё, что относится к Luxnet;
- описание продукта/системы;
- связанный служебный и коммерческий контекст.

### 3. `corp_kb.lighting_norms`

Authoritative source:

- тот же KB substrate;
- фильтр по `source_file=normy_osveschennosty.md`

Покрывает:

- определения;
- правила;
- нормы естественного и искусственного освещения;
- нормативные таблицы и интерпретации в пределах этого документа.

Routing model
-------------

Routing больше не должен начинаться с вопроса `какой intent это по старой эвристике?`.

Он должен начинаться с вопроса:

- `какой authoritative route family вероятнее всего владеет ответом?`

Алгоритм:

1. Router выбирает route family:
   - `corp_kb.company_common`
   - `corp_kb.luxnet`
   - `corp_kb.lighting_norms`
   - другая table/script/doc route family
2. Выполняется один primary query именно в эту family.
3. Если route дал `sufficient`, retrieval закрывается.
4. Если route дал `weak` или `empty`, допускается один retry внутри той же family.
5. Только после этого разрешается переход в другой route family.

Voice and paraphrase handling
-----------------------------

Для voice-style сообщений проблема должна решаться не расширением бесконечного списка keyword phrases, а через нормальный pre-routing normalization step:

1. снять telegram/voice wrapper;
2. извлечь чистый пользовательский запрос;
3. выбрать route family по смыслу;
4. при необходимости определить facet внутри family.

Примеры:

- `Расскажи сначала о самой компании` -> `corp_kb.company_common`
- `Что такое Luxnet` -> `corp_kb.luxnet`
- `Какие нормы освещенности для спортивных объектов` -> `corp_kb.lighting_norms`

Facet model inside a route family
---------------------------------

Внутри `corp_kb.company_common` допустимы topic facets, но они не создают отдельные таблицы. Они помогают ranking и query rewrite:

- `about_company`
- `series`
- `quality`
- `certification`
- `news`
- `legal`
- `contacts`
- `requisites`
- `socials`
- `price`
- `lighting_calculation`
- `fire_hazard_zones`

Facet должен влиять на:

- query rewrite;
- heading aliases;
- sufficiency checks;

но не на выбор другого storage substrate.

Tool contract
-------------

Рекомендуемый contract для `corp_db_search`:

- либо новый аргумент `knowledge_route_id`
- либо explicit `source_files`
- либо оба варианта с приоритетом `knowledge_route_id`

Пример:

```json
{
  "kind": "hybrid_search",
  "profile": "kb_route_lookup",
  "knowledge_route_id": "corp_kb.company_common",
  "query": "контакты компании",
  "topic_facets": ["contacts"]
}
```

Runtime обязан преобразовать route id в жёсткий source filter. Модель не должна импровизировать SQL-like детали.

Filter safety
-------------

Для source-scoped KB routes запрещены lamp-specific structured filters, если пользователь не находится в catalog route family.

В частности, такие поля не должны попадать в `corp_kb.company_common` / `corp_kb.luxnet` / `corp_kb.lighting_norms`:

- `voltage_kind`
- `beam_pattern`
- `mounting_type`
- диапазоны размеров и прочие lamp filters

Если они появились из LLM-generated args, runtime должен их отбросить до вызова tool.

Indexing rules
--------------

Route quality зависит не только от router, но и от alias/index layer.

Для каждого `source_file` и heading нужны:

- source-scoped aliases;
- facet tags;
- title normalization;
- явные route-family labels.

Это позволяет улучшать поиск без разрастания prompt heuristics.

Acceptance criteria
-------------------

1. Запросы про компанию, Luxnet и нормы освещённости сначала идут в соответствующую source-scoped route family.
2. Для каждого такого вопроса выполняется не более:
   - `1` primary attempt;
   - `1` retry внутри той же family;
   - затем, при необходимости, переход в secondary route family.
3. Voice/paraphrase формулировки маршрутизируются по смыслу, а не через узкий keyword список.
4. Lamp filters не загрязняют source-scoped KB routes.
5. В метаданных видно:
   - `retrieval_route_family`
   - `knowledge_route_id`
   - `source_file_scope`
   - `topic_facets`
6. Secondary route не вызывается, пока не исчерпан budget текущей authoritative family.

Implementation outline
----------------------

1. Ввести route family catalog для KB source files.
2. Добавить pre-routing normalization для voice/telegram wrapper.
3. Расширить `corp_db_search` contract route-aware аргументами.
4. Добавить source-scoped aliasing и facet metadata в индекс.
5. Обновить guardrails и tests под новую модель.

