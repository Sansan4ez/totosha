RFC-021 Runtime LLM-Led Orchestration Simplification
====================================================

Status
------

Proposed

Date
----

2026-04-10

Related RFCs
------------

- RFC-015 разделил runtime и benchmark pipelines, но runtime всё ещё содержит benchmark-oriented control flow.
- RFC-016 зафиксировал, что финальный ответ пользователю в happy-path должен формироваться через LLM.
- RFC-018 ввёл единый routing catalog, но orchestration layer по-прежнему перегружен hard-coded route logic.

Context and motivation
----------------------

Проект использует сильную модель `gpt-5.4` в runtime. Проверка живого конфига и метаданных подтверждает, что запросы действительно идут в `gpt-5.4`, а не в упрощённую или подменённую модель.

Значит основная проблема production-поведения заключается не в качестве LLM, а в том, что runtime слишком много решает за неё.

Сейчас orchestration размазана по нескольким слоям:

- длинный системный prompt со жёсткими маршрутами и fallback rules;
- Python-эвристики для intent detection, route hints и argument rewriting;
- runtime guardrail-ы, которые блокируют некоторые tool attempts;
- deterministic finalization paths, которые частично заменяют normal LLM answer step.

Эта схема сложнее, чем нужно для production.

Желаемый production-алгоритм проще:

1. LLM читает запрос пользователя.
2. LLM выбирает один или несколько подходящих tools/skills.
3. Tools/skills возвращают данные или ошибки.
4. LLM анализирует результаты, при необходимости делает следующий релевантный вызов.
5. Когда данных достаточно, LLM формирует финальный ответ в нужном tone of voice.
6. Если все релевантные пути исчерпаны, LLM честно сообщает, что данных недостаточно, и просит уточнение.

Детерминированные ответы допустимы только в benchmark mode и в редких degraded runtime scenarios вроде empty completion или transport failure.

Problem statement
-----------------

Production runtime нарушает принцип "LLM is the orchestrator" и вместо этого использует смешанную модель:

- часть решения принимает LLM;
- часть решения принимает hard-coded Python control flow;
- часть ответов рендерится без normal final LLM step;
- benchmark-oriented logic частично проникает в runtime path.

Это создаёт три класса проблем:

1. Избыточная сложность.
2. Трудная отладка из-за большого количества derived state и guardrail branches.
3. Риск скрытых regressions, когда корректный tool payload интерпретируется не по общей схеме, а по одной из специальных веток.

Goals
-----

- Сделать LLM единственным production orchestrator для tool/skill usage.
- Сократить runtime-specific branching в `core/agent.py`.
- Упростить system prompt до policy и приоритетов источников, а не до дерева исполнения.
- Оставить deterministic rendering только для benchmark mode и degraded fallback.
- Сохранить observability, но убрать низкоценные derived flags из canonical runtime state.
- Сделать поведение агента ближе к естественному ReAct workflow.

Non-goals
---------

- Удалять benchmark harness.
- Удалять routing catalog целиком.
- Отказываться от safety guardrails, которые защищают security boundary.
- Переписывать все tools или contracts за один шаг.
- Менять качество ответов за счёт ослабления source-of-truth policy.

Decision
--------

Production runtime переходит на LLM-led orchestration model.

Код runtime оставляет за собой только четыре обязанности:

1. Безопасное выполнение tools/skills.
2. Нормализацию tool results в единый contract: `success`, `empty`, `error`.
3. Базовые retry/iteration limits и observability.
4. Degraded fallback, если LLM вообще не смогла завершить ответ.

Все нормальные решения о том, какой tool вызвать дальше, когда остановиться и как сформулировать ответ, принимает LLM.

Target runtime algorithm
------------------------

Happy-path
~~~~~~~~~~

1. LLM получает user message и system policy.
2. LLM выбирает первый релевантный tool или skill.
3. Runtime исполняет вызов и возвращает полный payload обратно в conversation.
4. LLM либо:
   - формирует ответ пользователю, если данных достаточно;
   - либо вызывает следующий релевантный tool;
   - либо просит уточнение, если данные неполны;
   - либо честно сообщает об отсутствии данных после исчерпания релевантных путей.

Error-path
~~~~~~~~~~

1. Tool возвращает `error`.
2. LLM получает текст ошибки и сама решает:
   - повторить тот же путь с изменённым запросом;
   - перейти к другому релевантному tool;
   - остановиться и попросить уточнение.

Empty-path
~~~~~~~~~~

1. Tool возвращает `empty`.
2. LLM трактует это как отсутствие результата, а не как fatal failure.
3. LLM либо пробует другой релевантный path, либо уточняет запрос.

Degraded fallback
~~~~~~~~~~~~~~~~~

Deterministic fallback допускается только если:

- модель вернула empty completion;
- transport/LLM call завершился ошибкой;
- включён explicit benchmark mode;
- включён explicit safe fallback mode для оператора.

Этот fallback не является default happy-path.

Architectural changes
---------------------

### 1. Make runtime LLM finalization canonical

В production happy-path финальный ответ всегда проходит через LLM.

Следствия:

- `deterministic_primary` больше не должен использоваться в normal runtime flow;
- `_render_deterministic_tool_output()` не должен быть основным путем ответа пользователю;
- `finalizer_mode` в normal runtime должен быть `llm`, а не `deterministic_primary`.

### 2. Keep deterministic rendering only behind explicit mode boundaries

Нужно ввести явный execution mode:

- `runtime`
- `benchmark`

В `runtime`:

- полные tool payloads передаются обратно модели;
- benchmark compactors не участвуют в final answer path;
- deterministic renderers разрешены только как degraded fallback.

В `benchmark`:

- разрешены compact artifacts;
- deterministic renderers и direct-tool validations допустимы ради скорости и стоимости.

### 3. Downgrade route logic from hard control flow to hints

`route_hint`, intent heuristics и routing catalog остаются полезными, но их роль меняется:

- они помогают модели выбрать likely-best first tool;
- они не должны жёстко заменять tool plan модели;
- они не должны блокировать все альтернативные tool attempts кроме security-sensitive cases.

Допускаются только два класса hard guardrail:

1. security guardrails;
2. anti-loop guardrails по лимиту итераций и повторяющихся одинаковых вызовов.

Source-preference guardrails должны стать мягкими:

- через prompt guidance;
- через tool error hints;
- через loop protection against duplicate retries.

### 4. Reduce runtime state to minimal canonical fields

Текущий `routing_state` содержит слишком много derived fields.

Canonical runtime state должен быть сокращён примерно до:

- `intent_hint`
- `explicit_document_request`
- `attempted_tools`
- `attempted_routes`
- `last_tool_error`
- `last_tool_status`
- `iteration_count`
- `finalizer_mode`

Допустимы ещё observability fields, но они не должны участвовать в принятии большинства runtime decisions.

### 5. Simplify the system prompt

Системный prompt должен формулировать policy, а не исполняемый сценарий.

Prompt должен требовать от модели:

- выбирать релевантный authoritative source first;
- после `error` или `empty` пробовать другой разумный путь;
- не придумывать факты;
- отвечать кратко и по делу;
- просить уточнение, если нужных данных нет.

Prompt не должен содержать длинное дерево вида:

- "если 2.0.3aa то только этот tool";
- "если 2.0.3ab то блокируй все остальные";
- "если 2.0.7 и 2.0.8 то route closure происходит так-то".

Такие правила лучше переводить в короткие source-priority principles.

### 6. Preserve the tool contract and improve error semantics

Tools должны продолжать возвращать единый честный контракт:

- `success`
- `empty`
- `error`

При этом:

- runtime payload остаётся full-fidelity;
- ошибки не маскируются как `success`;
- LLM получает достаточно контекста, чтобы сделать второй шаг самостоятельно.

Proposed implementation phases
------------------------------

Phase 1: Separate runtime from benchmark mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Ввести явный mode flag для agent execution.
2. Запретить `deterministic_primary` в normal runtime.
3. Оставить deterministic rendering только в benchmark mode и degraded fallback.
4. Упростить метаданные так, чтобы `finalizer_mode` отражал реальный production path.

Phase 2: Remove hard-coded runtime finalizers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

5. Убрать production happy-path ветки, которые рендерят ответ напрямую из `corp_db_search` или `doc_search` payload.
6. После успешного tool call всегда возвращать payload в LLM loop для нормальной finalization.
7. Сохранить только bounded anti-loop protection и error handling.

Phase 3: Convert routing from hard guardrails to hints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

8. Сохранить routing catalog как source-priority suggestion layer.
9. Ослабить source-preference guardrails, которые блокируют корректные alternate tool attempts.
10. Оставить только:
    - security guardrails;
    - duplicate-tool/loop guardrails;
    - explicit mode boundaries.

Phase 4: Simplify prompt and runtime state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

11. Переписать `core/src/agent/system.txt` в более короткую policy-driven форму.
12. Сократить `routing_state` и derived telemetry fields.
13. Перенести observability на level of facts about execution, а не shadow decision tree.

Why this is the right simplification
------------------------------------

Эта схема лучше соответствует реальному предназначению сильной LLM:

- модель умеет выбирать следующий шаг;
- модель умеет интерпретировать ошибки tools;
- модель умеет синтезировать финальный ответ по payload;
- runtime не должен дублировать reasoning модели там, где безопасность этого не требует.

Это также снижает риск, что очередной special-case fast path сломает общий алгоритм работы агента.

Acceptance criteria
-------------------

1. В production happy-path ответы после успешных `corp_db_search` и `doc_search` формируются через normal LLM finalization.
2. `deterministic_primary` не используется в normal runtime mode.
3. Benchmark mode по-прежнему может использовать compact artifacts и deterministic rendering без влияния на production.
4. После `error` или `empty` модель может сделать следующий релевантный tool call без жёсткой блокировки со стороны source-preference guardrails.
5. Runtime по-прежнему предотвращает бесконечные циклы и security violations.
6. Системный prompt становится заметно короче и не дублирует большую часть orchestration logic из Python.
7. Для вопросов о company facts, сериях, документах и broad recommendations агент работает по одной общей схеме, а не по отдельным production fast paths.

Testing approach
----------------

Unit tests
~~~~~~~~~~

- mode separation between `runtime` and `benchmark`
- no `deterministic_primary` in runtime happy-path
- tool `error` remains visible to the model
- duplicate retry guard still stops obvious loops

Integration tests
~~~~~~~~~~~~~~~~~

- company facts: `Подскажи контакты компании`
- series info: `Расскажи о серии LAD LED LINE`
- document-domain question
- broad recommendation question

Manual verification
~~~~~~~~~~~~~~~~~~~

- confirm `return_meta=true` shows `llm_models=["gpt-5.4"]`
- confirm production answers still use full tool payloads
- confirm benchmark runs still produce compact artifacts

Code impact
-----------

Primary files:

- `core/agent.py`
- `core/src/agent/system.txt`
- `core/api.py`
- `core/run_meta.py`
- `core/tool_output_policy.py`
- `core/tests/test_routing_guardrail.py`

Likely supporting files:

- `core/tools/corp_db.py`
- `core/tools/doc_search.py`
- benchmark harness files only where explicit mode wiring is needed

Open questions
--------------

1. Нужен ли отдельный env flag, или execution mode должен передаваться через API request/meta only.
2. Какие observability fields остаются canonical, а какие становятся debug-only.
3. Нужен ли очень узкий deterministic fallback для operator safe-mode помимо benchmark mode.

