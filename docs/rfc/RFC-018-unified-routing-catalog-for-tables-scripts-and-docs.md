RFC-018 Unified Routing Catalog For Tables, Scripts, And Documents
==================================================================

Status
------

Implemented

Date
----

2026-04-08

Last updated
------------

2026-05-03

Implementation note
-------------------

This RFC is now implemented in the current routing architecture. Runtime catalog loading, merged route-manifest handling, selector payload construction, schema validation, and route ownership boundaries are documented and enforced through `core/documents/routing.py`, `core/documents/route_schema.py`, the runtime catalog path under `/data/corp_docs`, and the living architecture note in `docs/architecture/routing.md`. The body below is preserved as the original proposal context.

Related RFCs
------------

- RFC-009 ввёл index-driven routing, но текущий runtime по-прежнему живёт на упрощённом built-in catalog.
- RFC-017 задаёт source-scoped KB families; этот RFC определяет единый каталог для всех route kinds.

Context and motivation
----------------------

Сейчас `core/documents/routing.py` фактически держит упрощённый builtin catalog:

- несколько hard-coded route cards;
- document routes добавляются только из live corpus;
- script routes и multi-table workflows туда не входят;
- scoring остаётся простым keyword/pattern matching.

Это не соответствует целевой архитектуре, где routing должен быть согласован между:

- route-ами по отдельным таблицам;
- source-scoped KB route families;
- script route-ами для multi-table случаев;
- document-domain route-ами.

Problem statement
-----------------

Пока каталог routing не является единым источником истины, система будет дрейфовать:

- часть логики останется в prompt;
- часть в `core/agent.py`;
- часть в `core/documents/routing.py`;
- часть в scripts и workers;
- часть в operator manifests.

В результате нельзя надёжно ответить на вопрос:

- почему был выбран именно этот route;
- какие другие route-ы были кандидатами;
- какой route работает через table lookup, а какой через script orchestration.

Goals
-----

- Сделать единый versioned routing catalog.
- Представить в нём table routes, script routes и document routes одинаковой моделью.
- Убрать рассинхрон между built-in route cards и реальными retrieval domains.
- Дать runtime explainable route selection.
- Поддержать cases, где ответ требует скрипта и чтения нескольких таблиц одновременно.

Non-goals
---------

- Полная ML-переобучаемая router model.
- Сведение всех retrieval механизмов к одному SQL endpoint.
- Удаление prompt-level guidance полностью.

Route catalog model
-------------------

Каждая route card должна описывать не intent, а authoritative execution path.

Минимальный contract:

- `route_id`
- `route_family`
- `route_kind=corp_table|corp_script|doc_domain`
- `authority=primary|secondary`
- `title`
- `summary`
- `topics`
- `keywords`
- `patterns`
- `preconditions`
- `retry_policy`
- `executor`
- `executor_args_template`
- `observability_labels`

Route kinds
-----------

### 1. `corp_table`

Использует `corp_db_search` напрямую.

Примеры:

- `corp_kb.company_common`
- `corp_kb.luxnet`
- `corp_kb.lighting_norms`
- catalog lookup

### 2. `corp_script`

Использует именованный runtime script/orchestrator для cases, где нужно:

- читать несколько таблиц;
- делать controlled multi-step lookup;
- формировать compound result.

Примеры:

- lighting calculation helper;
- cross-table portfolio synthesis;
- complex application recommendation pipeline.

### 3. `doc_domain`

Использует `doc_search` и связанные document-domain manifests.

Примеры:

- документы по спортивным нормам освещённости;
- сертификаты и паспорта;
- другие самостоятельные документные домены.

Selection algorithm
-------------------

Selection должен учитывать:

1. candidate score;
2. authority;
3. route kind;
4. explicit user signal;
5. retry state текущего запроса.

Правила:

- explicit document request повышает `doc_domain`;
- если у `corp_table` route есть явный authoritative scope и score не ниже порога, он выигрывает у secondary routes;
- `corp_script` route выбирается только если вопрос действительно multi-table или требует доменной orchestration;
- после выбора одного route family действует bounded retry policy из RFC-016.

Single source of truth
----------------------

Каталог должен публиковаться как versioned runtime artifact, а не жить только в коде.

Рекомендуемые источники:

- repo-side route specs;
- generated manifests from workers;
- runtime-published merged catalog.

`core` может держать минимальный bootstrap catalog только на случай пустого индекса, но не как основную production truth.

Coordination with workers
------------------------

Каталог должны уметь публиковать:

- `corp-db-worker` для table/source-scoped routes;
- `doc-worker` для document-domain routes;
- отдельный route build step для script routes, если они не являются статическими.

В итоге runtime получает уже согласованный merged manifest.

Observability contract
----------------------

Каждый route selection event обязан логировать:

- `candidate_route_ids`
- `selected_route_id`
- `selected_route_kind`
- `selected_route_family`
- `selection_reason`
- `selection_score`
- `secondary_candidates`

Это нужно не только для observability, но и для bench/replay.

Acceptance criteria
-------------------

1. В runtime существует единый merged routing catalog.
2. `core/documents/routing.py` больше не является единственным production source of truth для route definitions.
3. В каталоге представлены:
   - source-scoped KB routes;
   - script routes;
   - document-domain routes.
4. Route selection можно объяснить по логам одного запроса без чтения prompt-а.
5. Новые route-ы добавляются через catalog publication, а не через ad hoc hard-coded ветки.
6. Built-in defaults используются только как bootstrap при отсутствии опубликованного каталога.

Implementation outline
----------------------

1. Ввести route schema и versioned manifest.
2. Перенести existing hard-coded routes в этот schema.
3. Добавить route publication для workers и static script routes.
4. Обновить selector и telemetry.
5. Покрыть tests для route selection, merge order и fallback-to-bootstrap.

