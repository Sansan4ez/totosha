RFC-004 Corp DB Search Latency And Observability Hardening
==========================================================

Context and motivation
----------------------

Каталожные запросы по светильникам сейчас решаются корректнее, чем раньше, но path остаётся медленным и местами нестабильным.

Наблюдаемые симптомы:

- В `core` встречается пустая ошибка `corp_db_search error:` при первом вызове `hybrid_search`.
- `POST /api/chat` и `POST /corp-db/search` по данным VictoriaMetrics упираются в верхний bucket `10000 ms`, поэтому текущая телеметрия не показывает реальный p50/p95.
- `hybrid_search` с explicit lamp filters остаётся слишком дорогим относительно `lamp_filters`.
- Трассировка request path неполная: в VictoriaTraces уверенно видны `tools-api` spans для `/corp-db/search`, но `core` traces для `/api/chat` и triage через VictoriaLogs сейчас не дают надёжного workflow.

Почему сейчас:

- после RFC-003 поиск стал богаче по полям, поэтому filter-heavy кейсы теперь важнее оптимизировать как отдельный fast path;
- bench smoke уже показывает pass rate, но latency и triage path всё ещё недостаточно предсказуемы;
- observability stack уже поднят, поэтому есть смысл закрепить измеримый latency contract, а не гадать по `docker logs`.

Наблюдения из Victoria stack и локального triage:

- VictoriaMetrics:
  - `histogram_quantile(0.5, ... http_server_duration_milliseconds_bucket ...)` для `core POST /api/chat` = `10000 ms`
  - `histogram_quantile(0.95, ... http_server_duration_milliseconds_bucket ...)` для `core POST /api/chat` = `10000 ms`
  - `histogram_quantile(0.5, ... http_server_duration_milliseconds_bucket ...)` для `tools-api POST /corp-db/search` = `10000 ms`
  - `histogram_quantile(0.95, ... http_server_duration_milliseconds_bucket ...)` для `tools-api POST /corp-db/search` = `10000 ms`
  - `histogram_quantile(0.5, ... corp_db_search_duration_milliseconds_bucket ...)` для `hybrid_search/entity_resolver` = `10000 ms`
  - `histogram_quantile(0.95, ... corp_db_search_duration_milliseconds_bucket ...)` для `hybrid_search/entity_resolver` = `10000 ms`
  - `lamp_filters` на том же горизонте держится существенно ниже: p50 около `75 ms`, p95 около `227.5 ms`
- VictoriaTraces:
  - для `tools-api /corp-db/search` видны spans в диапазоне примерно `1.3s .. 2.0s`, и есть выброс до `6.4s`
  - traces для `core /api/chat` в текущем виде не дают такой же надёжной выборки
- Локальные замеры на проблемных retrieval-кейсах:
  - cold embedding в `tools-api -> proxy` занимал около `10.4s`, warm embedding около `0.69s .. 0.74s`
  - `lamp_filters` через HTTP стабильно около `0.18s .. 0.44s`
  - `EXPLAIN ANALYZE` по SQL-фильтру на `corp.v_catalog_lamps_agent` даёт около `0.23 ms`
  - `corp_hybrid_search(...)` без semantic path на длинном запросе даёт около `654 ms`
  - полный `hybrid_search` с explicit filters и token fallback в warm path даёт около `7.6s .. 15.5s`
  - один из реальных запросов `tech-016` обработан `tools-api` за `26.5s`, после чего `core` оборвал вызов своим `20s` timeout и показал пустую ошибку

Goals:

- Убрать ложные ошибки `corp_db_search error:` на долгих, но корректных retrieval-запросах.
- Сделать filter-heavy catalog запросы быстрыми без усложнения архитектуры поиска.
- Снизить latency `hybrid_search` с explicit lamp filters до уровня, который не требует long-tail timeout в `core`.
- Сделать observability пригодной для реального triage: по route, фазам поиска и request path.
- Сохранить текущий API contract `corp_db_search` и не ломать агентский workflow.

Non-goals for first implementation (v1)
---------------------------------------

- Полная переработка алгоритма `corp_hybrid_search` или смена storage engine.
- Введение отдельного search-сервиса или внешнего ranker.
- Полный rework agent loop и общей LLM orchestration в `core`.
- Высококардинальные metric labels с `request_id`.

Implementation considerations
-----------------------------

- Решение должно быть простым и эффективным: при наличии явных структурированных фильтров нужно использовать дешёвый path, а не всегда ходить в embedding + hybrid + token fallback.
- Основной выигрыш уже доступен без архитектурных перестроек:
  - `lamp_filters` быстрый;
  - SQL path по `v_catalog_lamps_agent` уже индексируется и работает за миллисекунды;
  - медленный path концентрируется в hybrid orchestration и cold embedding.
- Observability должна различать:
  - timeout/transport errors в `core`;
  - latency фаз поиска в `tools-api`;
  - end-to-end route latency без clipping на `10000 ms`.

High-level behavior
-------------------

Новый retrieval path для catalog вопросов работает так:

1. Агент по-прежнему вызывает `corp_db_search`, передавая structured lamp filters.
2. `tools-api` для `hybrid_search` сначала оценивает, есть ли explicit lamp filters.
3. Если filters есть:
   - сначала выполняется authoritative `lamp_filters`;
   - если `lamp_filters` вернул достаточно релевантные результаты, ответ возвращается сразу;
   - embedding и token fallback не запускаются.
4. Если `lamp_filters` пустой или слишком широкий:
   - запускается дешёвый lexical-only hybrid path;
   - semantic embedding вызывается только как поздний fallback, а не как обязательный первый шаг.
5. `core` при timeout или transport failure возвращает диагностируемую ошибку с типом исключения и route context.
6. Observability по route и по фазам поиска показывает:
   - где время потрачено;
   - был ли вызван embedding;
   - был ли вызван token fallback;
   - какой search strategy выбран.

Search strategy and routing
---------------------------

### 1. Fast path for explicit lamp filters

В [corp_db.py](/home/admin/totosha/tools-api/src/routes/corp_db.py) `hybrid_search` меняет порядок принятия решения:

- `lamp_filters` вызывается до expensive hybrid stages;
- если `lamp_filters` вернул `1..limit` результатов, `hybrid_search` завершает запрос сразу с `search_strategy=filters_only`;
- если `lamp_filters` вернул небольшой набор, например `<= limit * 3`, backend может вернуть его без rerank;
- token fallback не запускается, если authoritative filter path уже вернул результаты.

Это сохраняет existing contract `hybrid_search`, но перестаёт платить за semantic/fallback там, где вопрос уже хорошо формализован.

### 2. Delayed semantic path

Semantic embedding перестаёт быть первым обязательным шагом для filter-heavy retrieval.

Правила v1:

- при explicit lamp filters и generic query (`"модель по характеристикам"`, `"подбери светильник"` и т.п.) embedding не вызывается;
- при explicit lamp filters и непустом query сначала выполняется lexical-only hybrid без embeddings;
- embeddings вызываются только если:
  - `lamp_filters` пустой;
  - lexical hybrid не дал устойчивого результата;
  - query действительно несёт неструктурированную смысловую нагрузку.

### 3. Fuzzy gating

Fuzzy stage в `corp_hybrid_search` не нужен на длинных generic/filter-heavy запросах и создаёт лишнюю стоимость.

В v1:

- fuzzy weight = `0` для explicit lamp filters;
- fuzzy weight = `0` для query длиннее заданного порога, например `> 24` символов или `> 5` strong terms;
- fuzzy остаётся только для коротких entity-resolution запросов и typo-like name matching.

Core-side error handling
------------------------

В [corp_db.py](/home/admin/totosha/core/tools/corp_db.py) исправляется поведение transport layer:

- текст ошибки включает класс исключения:
  - `TimeoutError`
  - `ClientConnectorError`
  - `ClientPayloadError`
- сообщение содержит route context и timeout budget, например:
  - `corp_db_search error: TimeoutError after 20s calling /corp-db/search`
- timeout на вызов `tools-api` разделяется на:
  - `connect timeout`
  - `sock_read timeout`
  - `total timeout`

Для v1 допустимо увеличить `total timeout` до `35s`, но это не является основным способом ускорения. Главный выигрыш должен прийти от backend fast path.

Agent routing and prompt overhead
---------------------------------

Часть latency теряется до поиска: агент делает лишние `list_directory` и `read_file` по skill-файлам перед `corp_db_search`.

В v1:

- краткие retrieval-правила для catalog вопросов дублируются в [system.txt](/home/admin/totosha/core/src/agent/system.txt);
- tool schema `corp_db_search` получает более прямое описание fast path по характеристикам;
- агенту явно рекомендуется вызывать `corp_db_search` сразу, без предварительного чтения skill-файлов, если вопрос про подбор светильника по параметрам.

Это не требует новой архитектуры skills, но уменьшает число tool/LLM итераций в типовом retrieval-сценарии.

Observability design
--------------------

### 1. Latency buckets

Текущие общие buckets `5 .. 10000 ms` недостаточны для длинных route-ов.

В v1:

- `http_server_duration_milliseconds` получает верхние buckets минимум до `60000 ms`;
- `corp_db_search_duration_milliseconds` получает такие же buckets;
- dashboard и alert rules обновляются так, чтобы `POST /api/chat` и `POST /corp-db/search` больше не clip-ились на `10000 ms`.

### 2. Phase metrics

В `tools-api` добавляется фазовая телеметрия:

- `corp_db_search_phase_duration_milliseconds{phase=embedding}`
- `corp_db_search_phase_duration_milliseconds{phase=lamp_filters}`
- `corp_db_search_phase_duration_milliseconds{phase=hybrid_primary}`
- `corp_db_search_phase_duration_milliseconds{phase=token_fallback}`
- `corp_db_search_phase_duration_milliseconds{phase=alias_fallback}`
- `corp_db_search_phase_duration_milliseconds{phase=merge}`

И отдельный counter:

- `corp_db_search_phase_total{phase,status}`

### 3. Trace spans

В `tools-api` добавляются child spans внутри `api.request`:

- `corp_db.embedding`
- `corp_db.lamp_filters`
- `corp_db.hybrid_primary`
- `corp_db.token_fallback`
- `corp_db.alias_fallback`

В `core` добавляется span вокруг tool call:

- `tool.corp_db_search`

Это даёт trace graph по фазам поиска и позволяет сравнивать `core` vs `tools-api`.

### 4. Observability gaps

По результатам triage v1 должен отдельно закрыть два operational gap:

- VictoriaLogs query по `request_id` сейчас не даёт надёжного результата;
- в VictoriaTraces route-level traces для `core /api/chat` недостаточно наблюдаемы по текущему workflow.

RFC не требует менять backend Victoria stack, если проблема окажется в query/retention/config, но acceptance criteria должны подтверждать, что triage workflow из runbook реально работает:

1. найти `request_id`,
2. найти log line,
3. открыть trace,
4. увидеть фазовую разбивку.

Error handling and UX
---------------------

Пользовательское поведение:

- если backend жив, но медленный, агент не должен показывать пустую ошибку;
- если `hybrid_search` timeout-ится, но filter path может помочь, система использует fallback;
- если transport failure реальный, ошибка должна быть диагностируемой в logs/traces и понятной оператору.

Операторское поведение:

- метрики показывают отдельный рост latency по `embedding` и `token_fallback`;
- traces показывают, был ли slow request вызван cold embedding, long fallback chain или agent overhead;
- logs по `request_id` должны находиться через VictoriaLogs.

Update cadence / Lifecycle
--------------------------

- Изменения в route logic и observability применяются вместе.
- После deploy запускается smoke subset retrieval-кейсов и latency compare против baseline.
- Buckets и dashboards обновляются одновременно, иначе новые latency значения будут невидимы в Grafana.

Future-proofing
---------------

- Если позже понадобится rerank внутри filter result set, это можно сделать без изменения public API: `search_strategy=filters_then_rerank`.
- Если появятся дополнительные каталоги, phase metrics и trace spans уже дадут понятную breakdown модель.
- Если latency всё ещё будет упираться в embedding backend, можно добавить небольшой in-memory cache по нормализованному query без смены контракта.

Implementation outline
----------------------

1. `tools-api`: fast path and fallback pruning
   - вызвать `lamp_filters` первым при explicit lamp filters
   - не запускать token fallback, если `lamp_filters` уже вернул релевантные результаты
   - отложить embeddings до позднего fallback
   - выключать fuzzy на filter-heavy запросах

2. `core`: timeout and error diagnostics
   - сделать ошибку `corp_db_search` информативной
   - разделить timeout budget на connect/read/total
   - при необходимости поднять `total timeout` до безопасного значения после backend optimization

3. `core`: agent routing reduction
   - упростить catalog routing в system prompt и tool description
   - сократить число лишних skill discovery steps перед `corp_db_search`

4. Observability
   - расширить histogram buckets
   - добавить phase metrics
   - добавить child spans в `tools-api` и tool span в `core`
   - проверить VictoriaLogs/VictoriaTraces triage workflow по `request_id`

5. Dashboards and runbook
   - обновить queries/dashboards под новые buckets и phase metrics
   - обновить observability runbook и bench triage notes

Testing approach
----------------

Unit:

- `tools-api` tests на short-circuit:
  - given explicit lamp filters and successful `lamp_filters`, token fallback не запускается
  - given explicit lamp filters and empty `lamp_filters`, lexical/semantic fallback остаётся доступным
- `core` tests на формат ошибок:
  - `TimeoutError` отражается в `ToolResult.error`
  - route context присутствует в сообщении

Integration:

- `tools-api` integration на retrieval-кейсах `tech-016`..`tech-019`
- проверка, что explicit filter queries не вызывают embedding path в expected fast path
- проверка новых phase metrics в `/metrics`

Manual / smoke:

- прогон smoke subset retrieval bench с `return_meta=true`
- сравнение:
  - `duration_ms`
  - `llm_time_ms`
  - `tools_time_ms`
  - `tools_used`
- Victoria triage:
  - найти log line по `request_id`
  - найти trace по `request_id`
  - увидеть spans `tool.corp_db_search`, `corp_db.lamp_filters`, `corp_db.hybrid_primary`, `corp_db.embedding`

Acceptance criteria
-------------------

- Для retrieval-кейсов с explicit lamp filters `tools-api /corp-db/search` не запускает `token fallback`, если `lamp_filters` уже вернул результат.
- Для retrieval-кейсов класса `tech-016` fast path не вызывает embedding, если structured filters уже достаточно селективны.
- `lamp_filters` остаётся дешевле `hybrid_search` и не деградирует выше `500 ms` p95 на smoke subset.
- `corp_db_search error:` больше не бывает пустым; сообщение содержит тип исключения и timeout context.
- `http_server_duration_milliseconds` и `corp_db_search_duration_milliseconds` больше не clip-ятся на `10000 ms` для длинных route-ов.
- В VictoriaMetrics доступны phase metrics `corp_db_search_phase_duration_milliseconds`.
- В VictoriaTraces для `tools-api /corp-db/search` доступны child spans по фазам поиска.
- В VictoriaTraces для `core` доступен traceable span на tool call `tool.corp_db_search`.
- Runbook triage по `request_id` работает end-to-end через Victoria stack, а не только через `docker logs`.
- Smoke bench по retrieval subset после внедрения показывает улучшение latency относительно baseline, без ухудшения pass rate.
