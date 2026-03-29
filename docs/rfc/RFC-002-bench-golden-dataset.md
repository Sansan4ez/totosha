RFC: Bench по `docs/questions.md` (Golden Dataset + Runner + Eval + Observability)
===============================================================================

Status
------

Draft (2026-03-29)

Context and motivation
----------------------

В репозитории есть список типовых вопросов бизнеса в [docs/questions.md](/home/admin/totosha.feature-benchmark/docs/questions.md) (техотдел, продажи, маркетинг). Сейчас качество ответов агента по этим вопросам проверяется вручную и нерепродуцируемо:

- сложно сравнивать изменения промпта/skills/БД между версиями;
- нет стабильного “эталона” (ground truth), на который можно опираться;
- нет единого артефакта результата (jsonl), который можно хранить/сравнивать между прогонами;
- observability-стек есть, но нет стандартного способа коррелировать “плохой ответ” с trace/logs и быстро находить root cause (пустой corp_db_search, таймаут proxy, неправильный tool-routing и т.д.).

Цель этого RFC: добавить в репозиторий **bench harness**, который позволяет:

1) поддерживать **golden dataset** (вопрос → ожидаемые факты/ответ) на основе текущих источников правды (wiki Markdown + catalog JSON/DB),
2) прогонять датасет через агента по API и писать **результаты в jsonl** с метриками (latency/tokens/cost),
3) оценивать ответы (deterministic eval) и получать summary,
4) использовать существующий VictoriaMetrics/VictoriaLogs/VictoriaTraces + harness для быстрой диагностики и улучшений.

Goals
-----

- Добавить golden dataset `bench/golden/v1.jsonl`:
  - каждый кейс содержит `question` (возможно адаптированный к реальным данным из `db/`/wiki),
  - `golden.answer` и/или `golden.fields` (структурная истина),
  - `golden.checks[]` (детерминированные проверки: contains/regex/number),
  - `origin` (ссылка на исходную формулировку из `docs/questions.md`) и `evidence` (файл/URL/указание источника).
- Добавить runner-скрипт `scripts/bench_run.py`:
  - отправляет вопросы в Core Agent (`POST /api/chat`),
  - пишет `bench/results/*.jsonl` с `question`, `answer`, `status`, `duration_ms`, `tokens`, `estimated_cost_usd`, `request_id`.
- Добавить eval-скрипт `scripts/bench_eval.py`:
  - читает golden dataset и результаты,
  - считает pass/fail по `golden.checks`,
  - печатает summary и (опционально) пишет `bench/reports/*.md|.json`.
- Минимально расширить Core API/agent, чтобы runner мог получить `tokens` и инструментальные метрики на каждый запрос:
  - вернуть `meta` по флагу `return_meta` (без изменения поведения по умолчанию),
  - прокинуть `X-Request-Id` в запросы к `proxy` и `tools-api` для корреляции по request_id.
- Описать, как использовать observability stack + harness для triage (по `request_id`, trace graph, метрики latency/errors).

Non-goals for first implementation (v1)
---------------------------------------

- LLM-as-a-judge (оценка ответов второй моделью) и любые недетерминированные scorers.
- Полное покрытие всех вопросов из `docs/questions.md`:
  - в v1 добавляются только кейсы с проверяемым ground truth из текущих источников (`shared_skills/.../wiki/*.md`, `db/catalog.json`, ссылки на документы).
- “Реальный бизнес-диалог” (многоходовка с контекстом, перепиской, вложениями):
  - в v1 каждый кейс независим, с очищенной сессией.
- Прогоны нагрузочного теста на высоком QPS.
- Публикация результатов наружу (внешние дашборды/сервисы).

Implementation considerations
-----------------------------

- **Детерминизм и воспроизводимость:**
  - golden dataset хранится в git как JSONL (версионируемый артефакт),
  - в каждом результате фиксируются `run_id`, версия датасета, конфиг модели (минимум: `model`, `temperature`, `max_iterations`).
- **Изоляция и независимость кейсов:**
  - перед каждым кейсом вызывается `POST /api/clear` (или используется уникальный `chat_id`), чтобы история не влияла на ответ.
- **Метрики tokens/cost:**
  - tokens берутся из `usage` ответов OpenAI-compatible backend (если usage отсутствует, tokens = null),
  - cost вычисляется runner’ом по локальной таблице цен (`bench/pricing.json`, USD per 1M tokens); при наличии `usage.prompt_tokens_details.cached_tokens` cached input учитывается отдельной ставкой.
- **Security:**
  - benchmark не должен раскрывать секреты; в `meta` нельзя возвращать сырой system prompt, ключи, env,
  - запрещено использовать высококардинальные метки в Prometheus (request_id только в logs/traces, не в labels).
- **Naming:**
  - избегаем слова `benchmark` в именах файлов/команд, т.к. оно встречается в security blocked patterns для `run_command`.

High-level behavior
-------------------

1) Оператор/CI запускает стек (опционально с observability overlay).
2) `scripts/bench_run.py`:
   - читает `bench/golden/v1.jsonl`,
   - для каждого кейса:
     - генерирует `request_id = bench/<run_id>/<case_id>`,
     - очищает сессию (`/api/clear`),
     - вызывает `/api/chat` с `return_meta=true`,
     - пишет строку результата в `bench/results/<run_id>.jsonl`.
3) `scripts/bench_eval.py`:
   - читает golden dataset и results jsonl,
   - оценивает каждый кейс по `golden.checks`,
   - печатает summary (pass rate, latency, tokens, cost) и список фейлов с `request_id`.
4) Для фейлов:
   - по `request_id` ищем trace/logs в Victoria (или локально в docker logs),
   - фиксируем root cause (не тот tool, empty from corp_db_search, таймаут proxy, model hallucination),
   - патчим (system prompt/skills/DB/tools),
   - повторяем прогон.

Data format and validation
--------------------------

### Golden dataset: `bench/golden/v1.jsonl`

Одна строка = один кейс:

```json
{
  "id": "mk-001-founded-year",
  "tags": ["marketing", "wiki"],
  "origin": {
    "file": "docs/questions.md",
    "section": "Вопросы из отдела маркетинга",
    "raw": "Сколько лет компании?"
  },
  "question": "Сколько лет компании ЛАДзавод светотехники? Назови год основания.",
  "golden": {
    "answer": "Компания основана в 2006 году.",
    "fields": { "founded_year": 2006 },
    "checks": [
      { "type": "contains_any", "value": ["основан", "основана"] },
      { "type": "number", "value": 2006, "tolerance": 0 }
    ]
  },
  "evidence": [
    {
      "type": "file",
      "path": "shared_skills/skills/corp-wiki-md-search/wiki/common_information_about_company.md",
      "hint": "Основанная в 2006 году"
    }
  ]
}
```

Поддерживаемые `checks` в v1:
- `contains_all`: все подстроки присутствуют (case-insensitive)
- `contains_any`: хотя бы одна подстрока присутствует
- `regex`: регулярка (Python `re`, default flags: IGNORECASE|MULTILINE)
- `number`: в ответе есть число в пределах `tolerance` от `value` (поддержка `,` и `.`)

### Results: `bench/results/<run_id>.jsonl`

Одна строка = один кейс в одном прогоне:

```json
{
  "run_id": "20260329_150501Z_ab12cd",
  "dataset": "bench/golden/v1.jsonl",
  "case_id": "mk-001-founded-year",
  "request_id": "bench/20260329_150501Z_ab12cd/mk-001-founded-year",
  "started_at": "2026-03-29T15:05:01.123Z",
  "duration_ms": 842.2,
  "status": "ok",
  "question": "...",
  "answer": "...",
  "meta": {
    "model": "gpt-oss-120b",
    "temperature": 0.2,
    "iterations": 2,
    "tools_used": ["corp_db_search"],
    "llm_usage": { "prompt_tokens": 1234, "completion_tokens": 456, "total_tokens": 1690 },
    "llm_time_ms": 700.1,
    "tools_time_ms": 90.4
  },
  "estimated_cost_usd": 0.0
}
```

Runner обязан писать строку результата даже при ошибках:
- `status=timeout|access_denied|error`
- `answer` может быть пустой строкой
- `meta` может отсутствовать или иметь `llm_usage=null`

Bench runner
------------

Скрипт: `scripts/bench_run.py`.

Аргументы v1:
- `--dataset bench/golden/v1.jsonl`
- `--out bench/results/<run_id>.jsonl`
- `--user-id` / `--chat-id` (по умолчанию `ADMIN_USER_ID`)
- `--core-url` (если Core порт проброшен наружу) или `--docker-exec` (через `docker exec core ...`)
- `--pricing bench/pricing.json`
- `--limit N` (опционально)

Поведение:
- по умолчанию последовательный прогон (concurrency=1) для стабильности и простоты triage;
- перед каждым кейсом очищает сессию;
- для корреляции всегда устанавливает `X-Request-Id` и дублирует его в jsonl.

Bench eval
----------

Скрипт: `scripts/bench_eval.py`.

Аргументы v1:
- `--dataset bench/golden/v1.jsonl`
- `--results bench/results/<run_id>.jsonl`
- `--report bench/reports/<run_id>.md` (опционально)

Summary v1:
- общий pass rate
- pass rate по `tags`
- средняя/медианная latency
- суммарные tokens/cost (если доступны)
- топ фейлов (case_id, request_id, почему не прошёл)

Observability integration
-------------------------

### Корреляция

- Runner генерирует стабильный `request_id` на кейс и отправляет его как `X-Request-Id`.
- Core возвращает тот же `X-Request-Id` в ответе и прокидывает `X-Request-Id` в `proxy` и `tools-api`.
- Traces/Logs экспортируются через OTEL collector (см. `docker-compose.observability.yml`).

### Triage workflow (рекомендуемый)

1) В `bench_eval` найти `request_id` для failing case.
2) В VictoriaLogs найти строки `HTTP request completed` по `request_id` и посмотреть `trace_id`.
3) В VictoriaTraces открыть trace и посмотреть:
   - где потеря времени: core vs proxy vs tools-api
   - были ли ошибки tool calls / таймауты
4) В Grafana:
   - `http_server_duration_milliseconds` по сервисам
   - `corp_db_search_duration_milliseconds` (tools-api) и `corp_db_search_requests_total`
5) Фикс:
   - если routing: патч `core/src/agent/system.txt` или skill-инструкций
   - если DB: сидирование/индексы/manifest
   - если tool: описание tool, timeouts, output trimming
6) Повторный прогон и сравнение отчётов.

Future-proofing
---------------

- Добавить check types:
  - `json`/`schema` (если ответы станут структурированными),
  - `list_contains` для списков кандидатов,
  - `no_hallucination` (запрет “лишних” фактов).
- Добавить режим сравнения 2-х конфигураций (`--baseline-results`, diff отчётов).
- Добавить CI job, который:
  - поднимает compose + observability overlay,
  - гоняет маленький smoke subset датасета,
  - сохраняет jsonl + markdown отчёт как artifact.

Implementation outline
----------------------

1. Создать `bench/` структуру (`golden/`, `results/`, `reports/`) и добавить `.gitignore` для результатов.
2. Реализовать `bench/golden/v1.jsonl` (10-30 детерминированных кейсов).
3. Добавить core-side `return_meta`:
   - накопление `llm_usage` по всем `call_llm` внутри `run_agent`,
   - измерение времени LLM/tool,
   - список `tools_used`.
4. Добавить `scripts/bench_run.py` (jsonl writer).
5. Добавить `scripts/bench_eval.py` (checks + summary).
6. Обновить observability docs/harness при необходимости (если добавятся новые метрики).

Testing approach
----------------

- Unit:
  - парсинг golden dataset (валидатор схемы),
  - проверки `contains/regex/number` на наборе фикстур.
- Integration (manual):
  - поднять compose (желательно с `docker-compose.observability.yml`),
  - прогнать `scripts/bench_run.py --limit 5`,
  - прогнать `scripts/bench_eval.py`,
  - проверить, что `request_id` виден в core/proxy logs и trace цепочка строится.

Acceptance criteria
-------------------

- В репозитории есть `bench/golden/v1.jsonl` с детерминированными кейсами, связанными с `docs/questions.md`.
- `scripts/bench_run.py` создаёт jsonl результатов, где для каждого кейса есть `duration_ms`, `request_id` и (если backend даёт usage) `tokens`.
- `scripts/bench_eval.py` детерминированно оценивает результаты и печатает summary + failing cases.
- При включённом observability overlay failing case можно найти по `request_id` в VictoriaLogs и открыть связанный trace в VictoriaTraces.
