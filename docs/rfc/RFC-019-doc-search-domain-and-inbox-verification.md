RFC-019 Doc Search Domain And Inbox Verification
================================================

Status
------

Proposed

Date
----

2026-04-08

Related RFCs
------------

- RFC-007, RFC-009 и RFC-010 развивали document search, но всё ещё описывали его как fallback слишком часто.
- Этот RFC фиксирует `doc_search` как отдельный домен и задаёт проверку на текущем inbox-документе.

Context and motivation
----------------------

`doc_search` не является запасным шагом `на всякий случай`. У него свой corpus, свои маршруты и свой operator workflow.

На 2026-04-08 в репозитории уже есть новый документ в inbox:

- `doc-corpus/inbox/part_440.1325800.2023.doc`

Наблюдаемое состояние:

- это binary legacy Word `.doc`, а не `.docx`;
- размер около `611K`;
- `15` страниц;
- sidecar metadata для него пока отсутствует;
- canonical operator workflow уже описан через `doc-worker`;
- при этом текущий `doc-worker` build path требует отдельной проверки и починки.

Problem statement
-----------------

Система пока не зафиксировала три важных решения:

1. `doc_search` должен считаться самостоятельным route domain, а не fallback после `corp_db`.
2. Для inbox-документа нужен конкретный verification RFC, а не только общая архитектура.
3. Не решено, нужен ли отдельный SQL/table layer для document routes или достаточно manifests + parsed sidecars + route index.

Goals
-----

- Закрепить `doc_search` как отдельный домен.
- Определить end-to-end verification для текущего inbox-документа.
- Зафиксировать минимально достаточную архитектуру document indexing без преждевременного выделения новой таблицы.
- Согласовать использование LiteParse и Unix search utilities с runtime contract.

Non-goals
---------

- Автоматический promotion документа в corporate DB.
- Новая универсальная SQL-схема для всех documents в первой итерации.
- Semantic vector search по document corpus как обязательный v1.

Decision
--------

Для v1 `doc_search` использует собственный document substrate:

- repo inbox;
- runtime manifests;
- parsed sidecars;
- route index;
- Unix/LiteParse-backed normalization and search.

Отдельная SQL-таблица для document routes в этом RFC не обязательна.

Она может появиться позже только если возникнет чёткая необходимость в:

- сложной аналитике;
- cross-document joins;
- ACL/reporting поверх corpus;
- тяжёлых ranking queries, которые неудобно делать по manifests и sidecars.

До этого достаточно:

- route index для routing;
- parsed sidecars как search substrate;
- manifests как source of truth для document metadata.

Role of Unix utilities and LiteParse
------------------------------------

Исходная идея остаётся правильной:

- heavy parsing и normalization делает `doc-worker`;
- поиск использует нормализованные sidecars;
- стандартные Unix utilities и LiteParse являются implementation detail `doc-worker` / `doc_search`, а не отдельными агентскими tool-ами.

Это даёт:

- простую поддержку legacy Office;
- прозрачный operator workflow;
- отсутствие shell chaos в agent loop.

Inbox verification scope
------------------------

Отдельная проверка должна быть выполнена именно на текущем документе:

- `doc-corpus/inbox/part_440.1325800.2023.doc`

Ожидаемый домен:

- нормы освещённости для спортивных объектов и связанная тематика документа.

Verification plan
-----------------

### Phase 1. Prepare metadata

Рядом с файлом создаётся:

- `doc-corpus/inbox/part_440.1325800.2023.doc.meta.json`

В sidecar рекомендуется явно зафиксировать:

- `title`
- `summary`
- `tags`
- `route_family`
- `topics`

Минимальный смысловой набор:

- спорт
- спортивные объекты
- нормы освещённости
- освещённость спортивных залов / арен / стадионов

### Phase 2. Restore write path

Перед verification нужно восстановить рабочий operator path:

- `doc-worker` должен собираться;
- `sync-repo` должен публиковать live manifest;
- `rebuild-parsed` должен создавать current parsed sidecar;
- `rebuild-routes` должен публиковать route index.

### Phase 3. Publish the document

После восстановления write path оператор выполняет:

```bash
docker compose --profile operator run --rm doc-worker sync-repo
docker compose --profile operator run --rm doc-worker rebuild-parsed --force
docker compose --profile operator run --rm doc-worker rebuild-routes
```

### Phase 4. Verify runtime retrieval

Проверяются минимум три запроса:

1. `Какие нормы освещенности для спортивных объектов?`
2. `Найди в документе нормы освещенности для спортивного зала`
3. `Какие требования к освещению спортивных сооружений указаны в документе?`

Ожидаемое поведение:

- selected route family относится к `doc_search`;
- найден именно этот document domain;
- ответ опирается на snippets из опубликованного документа;
- `corp_db` не является обязательным первым шагом для таких document-domain запросов.

Prompt and telemetry changes
---------------------------

Prompt и skill descriptions должны перестать описывать `doc_search` как fallback.

Нужно зафиксировать:

- `doc_search` выбирается по document-domain signal;
- `doc_search` выбирается по explicit request на фрагмент/цитату/документ;
- `doc_search` может быть secondary route после KB miss, но это только один из вариантов использования, а не его смысл.

Telemetry должна отражать именно domain routing:

- `selected_source=doc_search`
- `selected_route_kind=doc_domain`
- `selected_route_family=<document family>`

Acceptance criteria
-------------------

1. Для текущего inbox-файла существует metadata sidecar с route metadata.
2. `doc-worker` успешно публикует:
   - live manifest;
   - parsed sidecar;
   - route index entry.
3. Document-domain запросы по спортивным нормам выбирают `doc_search` как primary route.
4. Ответы содержат факты из опубликованного документа, а не случайный secondary route.
5. В prompt и skill docs `doc_search` больше не описан как просто fallback.
6. Для v1 не вводится отдельная SQL-таблица без отдельного обоснования.

Implementation outline
----------------------

1. Починить `doc-worker` build/runtime path.
2. Добавить repo-side metadata для inbox-документа.
3. Выполнить sync/parsing/route publication.
4. Добавить smoke test на три document-domain запроса.
5. Обновить prompt, skills и docs под first-class `doc_search` domain.
