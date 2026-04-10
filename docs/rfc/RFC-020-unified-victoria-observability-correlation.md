RFC-020 Unified Victoria Observability Correlation
==================================================

Status
------

Proposed

Date
----

2026-04-08

Related RFCs
------------

- RFC-013 уже описывал проблему с неактивной OTEL wiring.
- Этот RFC фиксирует целевую operational contract: Victoria Traces, Logs и Metrics должны работать как один связанный процесс observability.

Context and motivation
----------------------

Метрики сами по себе не решают RCA. Логи без trace linkage тоже недостаточны. Трейсы без общих business ids плохо помогают при разборе agent routing.

Для этого проекта observability должна отвечать на один операторский вопрос:

- `как один пользовательский запрос прошёл через bot, core, proxy, tools-api, workers и retrieval routes?`

Сейчас такой ответ получить нельзя стабильно, если:

- сервисы запущены без OTEL env;
- не пробрасывается `traceparent`;
- логи не содержат route/tool identifiers;
- метрики не связываются с тем же запросом через общие labels и exemplars.

Goals
-----

- Включить текущий production/runtime path в Victoria Traces, Logs и Metrics одновременно.
- Ввести единый correlation contract для request id, trace id, route id и tool call id.
- Сделать observability пригодной для RCA по routing/retrieval проблемам.
- Обеспечить smoke verification свежих traces, logs и metrics после деплоя.

Non-goals
---------

- Замена Victoria stack.
- Полная переделка logging framework.
- Хранение user message body целиком в telemetry по умолчанию.

Unified correlation contract
----------------------------

Для каждого запроса должны существовать и согласованно передаваться:

- `request_id`
- `trace_id`
- `span_id`
- `session_id` или chat/session surrogate, если доступен
- `selected_route_id`
- `selected_route_family`
- `selected_route_kind`
- `tool_call_id`
- `tool_name`
- `document_id` или `knowledge_route_id`, если применимо

Propagation rules
-----------------

На каждом внутреннем HTTP hop обязательно передаются:

- `traceparent`
- `tracestate`, если есть
- `X-Request-Id`

Это относится к цепочке:

- `bot -> core`
- `core -> proxy`
- `core -> tools-api`
- `core -> any worker-facing HTTP API`, если такой появится

Structured logging contract
---------------------------

Каждый service log event, относящийся к запросу, должен содержать:

- `service`
- `request_id`
- `trace_id`
- `span_id`
- `route_id`
- `route_family`
- `route_kind`
- `selected_source`
- `tool_name`
- `tool_call_seq`
- `tool_status`

Для retrieval-specific событий добавляются:

- `knowledge_route_id`
- `source_file_scope`
- `topic_facets`
- `document_id`
- `match_mode`
- `retrieval_phase`
- `retrieval_evidence_status`

Metrics contract
----------------

Метрики не должны быть просто счётчиками HTTP.

Нужны:

- request counters and latency histograms по сервисам;
- tool latency histograms;
- route selection counters;
- blocked-guardrail counters;
- document-route and KB-route success counters.

Где возможно, нужно использовать exemplars или эквивалентную связку с trace id.

Trace model
-----------

Один пользовательский запрос должен строить trace tree, в котором видны:

- ingress span;
- route selection span;
- LLM spans;
- tool spans;
- downstream HTTP spans;
- finalization span.

Отдельно должны быть видны события:

- route closed;
- guardrail blocked extra tool call;
- secondary route opened;
- fallback finalizer activated.

Deployment contract
-------------------

Production и operator startup не должны допускать запуск app services без OTEL wiring.

Допустимые варианты:

1. объединить service-side `OTEL_*` env в base compose;
2. сделать observability compose обязательной частью всех documented startup flows.

В любом случае operator не должен случайно получить ситуацию:

- метрики есть;
- traces/logs для текущих запросов отсутствуют.

Smoke verification
------------------

После каждого деплоя должна выполняться связанная проверка:

1. отправить synthetic request с фиксированным `X-Request-Id`;
2. проверить свежий metric increment;
3. найти тот же `request_id` в VictoriaLogs;
4. найти trace для того же запроса в VictoriaTraces;
5. проверить, что логи и trace share один `trace_id`;
6. убедиться, что в логах присутствуют `selected_route_id` и `tool_name`.

Минимальные сценарии smoke:

1. короткий KB route query;
2. document-domain query;
3. запрос с хотя бы одним tool call в `tools-api`.

Acceptance criteria
-------------------

1. Все production-critical сервисы стартуют с активной OTEL wiring.
2. Один новый запрос наблюдаем одновременно в Victoria Metrics, Logs и Traces.
3. Для одного запроса можно связать:
   - `request_id`
   - `trace_id`
   - `selected_route_id`
   - `tool_name`
4. По логам и traces можно восстановить:
   - какой route был выбран;
   - почему он закрылся;
   - был ли fallback;
   - какие downstream вызовы выполнялись.
5. Отсутствие traces/logs после деплоя считается smoke failure.

Implementation outline
----------------------

1. Починить default deployment wiring для OTEL.
2. Включить `traceparent` propagation на всех внутренних HTTP клиентах.
3. Унифицировать structured fields в логах сервисов.
4. Добавить route/tool correlation labels в spans и logs.
5. Добавить smoke checks для свежих metrics, logs и traces.

