RFC-016 Authoritative Route Completion And LLM Finalization
===========================================================

Status
------

Proposed

Date
----

2026-04-08

Related RFCs
------------

- RFC-014 уточнял company-fact fast path, но предлагал deterministic rendering как happy-path.
- RFC-015 разделил runtime и benchmark pipelines и зафиксировал, что финальный ответ пользователю должен формироваться LLM.

Context and motivation
----------------------

В текущем runtime смешаны две разные задачи:

1. понять, что authoritative retrieval уже дал достаточно данных;
2. сформировать финальный пользовательский ответ.

Из-за этого агент ведёт себя неустойчиво:

- после `corp_db_search` со статусом `success` и релевантным payload он иногда продолжает tool loop;
- в метаданных одновременно встречаются `company_fact_payload_relevant=true`, `company_fact_fast_path=false` и `company_fact_finalizer_mode=llm`;
- понятие `fast_path` стало двусмысленным: оно частично описывает завершённость retrieval, а частично способ рендеринга ответа.

Для production это неверная модель. Финальный ответ пользователю действительно должен отправлять LLM. Но это не означает, что LLM должна продолжать делать новые tool calls после того, как retrieval уже закрыл основной вопрос.

Problem statement
-----------------

После одного или нескольких успешных `corp_db_search` агент не фиксирует состояние `доказательств уже достаточно`.

В результате возможен неверный сценарий:

1. tool возвращает правильные данные;
2. runtime помечает источник как `selected_source=corp_db`;
3. но tool loop остаётся открытым;
4. модель продолжает искать дополнительные источники;
5. появляется лишний `doc_search` или другой route;
6. финальный ответ либо замедляется, либо становится противоречивым.

Root cause
----------

Текущий runtime не различает:

- `retrieval is sufficient`
- `answer is rendered`

Нужен явный contract:

- retrieval может быть закрыт;
- final answer всё равно остаётся `LLM finalization`;
- после закрытия retrieval model не должна открывать новые нерелевантные маршруты.

Goals
-----

- Разделить `retrieval completion` и `final answer generation`.
- Остановить лишние tool calls после того, как authoritative route дал достаточные данные.
- Сохранить финальный пользовательский ответ через LLM.
- Ввести bounded retry policy внутри одного маршрута.
- Сделать метрики и логи понятными для RCA.

Non-goals
---------

- Возврат к deterministic rendering как стандартному happy-path.
- Удаление fallback paths.
- Полный rework всех agent intents за один этап.

Decision
--------

В runtime вводится двухфазная модель:

1. `retrieval phase`
2. `llm finalization phase`

Успешный authoritative retrieval завершает только первую фазу. После этого:

- новые tool calls по этому вопросу больше не допускаются, кроме явно разрешённых post-answer routes;
- LLM получает уже собранные evidence и пишет финальный ответ пользователю;
- `finalizer_mode=llm` остаётся нормой.

State model
-----------

Вместо текущей пары `company_fact_fast_path` / `company_fact_rendered` вводятся или становятся canonical следующие поля:

- `retrieval_route_id`
- `retrieval_route_family`
- `retrieval_phase=open|retry|closed`
- `retrieval_evidence_status=empty|weak|sufficient|error`
- `retrieval_retry_count`
- `retrieval_close_reason`
- `finalizer_mode=llm|deterministic_fallback`

Для обратной совместимости старые поля могут временно заполняться как derived aliases, но не должны больше быть источником истины.

Authoritative route closure
---------------------------

Route считается закрытым, если одновременно выполнены условия:

1. выбран authoritative route;
2. tool вернул `success`;
3. payload прошёл route-specific sufficiency check;
4. пользователь не просил явно дополнительный документный или multi-source context.

Примеры sufficiency:

- company facts: найден нужный chunk / heading / факт по authoritative KB route;
- contacts: извлечён хотя бы один подтверждённый канал связи;
- requisites: найдены юридические реквизиты;
- lighting norms: найден релевантный документный или KB fragment по нужной теме.

Tool loop policy
----------------

Для каждого route действует bounded execution contract:

1. Primary attempt:
   - выполняется основной tool call выбранного route.
2. Route-local retry:
   - допускается только если результат `empty`, `error` или `weak`;
   - retry должен оставаться в том же route family.
3. Route closure:
   - как только evidence становится `sufficient`, route закрывается.
4. Secondary route:
   - допускается только после исчерпания route-local retry budget.

Для company/common KB route рекомендуемый budget:

- `1` primary attempt;
- `1` retry внутри того же route family;
- затем только secondary route.

LLM finalization contract
------------------------

После `retrieval_phase=closed` модель обязана:

- сформировать ответ по уже собранным evidence;
- не вызывать новые инструменты для того же базового вопроса.

Runtime guardrail обязан блокировать попытки сделать после closure:

- `doc_search`
- другой `corp_db_search` вне разрешённого retry policy
- shell/document browse инструменты

Исключения:

- пользователь явно просит дополнительный источник;
- route policy разрешает post-answer enrichment;
- основной route закрыл факт, но не закрыл явно запрошенную вторую задачу.

Why the current behavior is wrong
---------------------------------

Сценарий "два успешных `corp_db_search`, затем ещё один поиск" не является признаком осторожности. Это признак отсутствия terminal decision в orchestration layer.

Если второй `corp_db_search` уже дал достаточные данные, дальнейшие действия должны быть запрещены runtime guardrail-ом. Модель не должна самостоятельно решать, нужен ли ещё один случайный route.

Proposed runtime changes
------------------------

### 1. Close retrieval on sufficient evidence

После route-specific validator:

- выставлять `retrieval_evidence_status=sufficient`;
- выставлять `retrieval_phase=closed`;
- сохранять `retrieval_close_reason=authoritative_payload_sufficient`.

### 2. Keep LLM final answer as the default

При закрытом retrieval:

- `finalizer_mode=llm`
- `deterministic_fallback` используется только при transport/LLM failure.

### 3. Add runtime guardrail after closure

Если LLM пытается вызвать новый tool после `retrieval_phase=closed`, runtime:

- не выполняет этот tool;
- возвращает в модель системное напоминание вида:
  - `authoritative route is already closed; answer from collected evidence`

### 4. Replace misleading telemetry

Поля `company_fact_fast_path` и `company_fact_rendered` должны быть либо удалены, либо переопределены как compatibility-only.

Оператору нужны другие сигналы:

- какой route был выбран;
- сколько было попыток внутри route;
- в какой момент route закрылся;
- был ли заблокирован лишний tool call после closure;
- каков `finalizer_mode`.

Acceptance criteria
-------------------

1. Для company/common KB question после первого `success+sufficient` не происходит ни одного дополнительного tool call.
2. Если первый вызов `weak`, но второй вызов в том же route `success+sufficient`, дальнейшие tool calls не допускаются.
3. Финальный ответ пользователю в happy-path всё ещё приходит через LLM.
4. `deterministic_fallback` используется только при `empty_llm_completion`, transport failure или аналогичном degraded mode.
5. В метаданных одного запроса видно:
   - `retrieval_route_id`
   - `retrieval_phase`
   - `retrieval_evidence_status`
   - `retrieval_retry_count`
   - `retrieval_close_reason`
   - `finalizer_mode`
6. Попытка нового tool call после `retrieval_phase=closed` логируется как blocked guardrail event.

Implementation outline
----------------------

1. Перенести понятие sufficiency в явный runtime state.
2. После route-specific validator закрывать retrieval phase.
3. Оставить LLM finalization как обязательный normal path.
4. Добавить guardrail, блокирующий tool calls после closure.
5. Обновить tests, чтобы они проверяли не deterministic rendering, а bounded tool loop.

