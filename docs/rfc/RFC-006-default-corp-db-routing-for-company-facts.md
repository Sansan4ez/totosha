RFC-006 Default Corp DB Routing For Company Facts
=================================================

Status
------

Proposed

Date
----

2026-04-05

Context and motivation
----------------------

Последний полный bench run `20260403_013443Z_896b26`, начатый `2026-04-03T01:34:43.250166Z`, показал хорошее качество ответа, но плохую latency-профиль для вопросов, которые исторически относились к wiki.

Наблюдаемые симптомы:

- `27/27` кейсов прошли по quality checks, но `duration_ms_p95 = 73779.895`.
- Для `wiki`-tag кейсов средняя latency составила `53788.0 ms`, median `50757.4 ms`, max `81183.5 ms`.
- Для `non_wiki` кейсов средняя latency составила `11439.9 ms`.
- Для `wiki`-tag кейсов среднее `tools_time_ms = 23797.2`, а для `non_wiki` только `44.5`.
- Для `wiki`-tag кейсов среднее число вызовов `run_command = 2.1`, для `non_wiki` оно равно `0.0`.

Это уже не соответствует текущему целевому состоянию системы:

- документы, ради которых вводился `corp-wiki-md-search`, сейчас уже добавлены в корпоративную БД;
- для простых company-fact вопросов агент должен по умолчанию завершать ответ на `corp_db_search`;
- переход в wiki должен оставаться только fallback-path для реально неиндексированных документов или для явного запроса на текстовый wiki-контекст.

Почему сейчас:

- bench уже зафиксировал стабильный регресс по latency;
- текущие prompt/skill rules конфликтуют между собой и продолжают тянуть агента в `wiki`;
- `wiki` path использует `run_command` и Docker sandbox, поэтому ложный переход в wiki не просто добавляет один tool call, а может стоить десятки секунд.

Goals:

- Зафиксировать root cause неправильного выбора между `corp-pg-db` и `corp-wiki-md-search`.
- Сделать `corp_db_search` default-path для company-fact и promoted-KB вопросов.
- Запретить wiki fallback после успешного `corp_db_search`, если пользователь не просил дополнительный текстовый контекст.
- Снизить latency для текущих `wiki`-tag кейсов до уровня, близкого к обычным `corp_db` кейсам.
- Добавить измеримые bench/observability критерии, чтобы регресс не вернулся.

Non-goals for first implementation (v1)
---------------------------------------

- Полный rework agent loop в `core`.
- Полная замена skill-системы на rule engine.
- Полный отказ от wiki как источника данных.
- Перенос всех wiki-сценариев в новые backend RPC за один этап.

Implementation considerations
-----------------------------

- Проблема находится не в доступности `corp_db`: по traces и logs backend отвечает быстро и корректно.
- Проблема находится в orchestration layer:
  - агент недостаточно жёстко понимает, что успешный `corp_db_search` уже authoritative;
  - `corp-wiki-md-search` описан слишком широко и конкурирует с `corp-pg-db` за одни и те же вопросы;
  - после успешного `kb_search` нет terminal rule "не ходить в wiki".
- Цена ошибки высокая:
  - дополнительный `run_command`;
  - дополнительные LLM iterations;
  - возможный sandbox cold-start;
  - раздувание контекста большими payload-ами и чтением `SKILL.md`.
- Решение должно быть двухслойным:
  - быстрое: prompt/skill/routing guardrails;
  - системное: убрать shell-first реализацию wiki из hot path и сделать company-fact retrieval компактнее.

Observed evidence
-----------------

### 1. Bench evidence from `2026-04-03`

В `bench/results/20260403_013443Z_896b26.jsonl` самые медленные кейсы выглядят так:

- `mk-006-vk`: `81183.5 ms`, tools `list_directory`, `read_file`, `corp_db_search`, `run_command`
- `mk-001-founded-year`: `75711.6 ms`, tools `corp_db_search`, `search_tools`, `list_directory`, `read_file`, `run_command`
- `mk-003-head-office`: `69272.7 ms`, тот же паттерн
- `mk-002-website`: `45719.1 ms`, тот же паттерн
- `mk-007-consulting`: `48405.7 ms`, тот же паттерн

Во всех этих случаях ответ по сути является коротким company fact, но runtime-path всё равно включает wiki-oriented действия.

### 2. Live reproduction on `2026-04-04`

Для подтверждения проблемы был сделан воспроизводимый triage с фиксированными `X-Request-Id`.

Кейс `rfc-skill-routing-mk001`

- Вопрос: "Сколько лет компании ЛАДзавод светотехники? Если точный возраст не знаешь, назови год основания."
- Итог: `duration_ms = 63266.085`
- `tools_used = ["list_directory", "read_file", "corp_db_search", "run_command"]`
- `corp_db_search` отработал успешно и быстро:
  - `tools-api POST /corp-db/search = 308.08 ms`
  - traces показывают `corp_db.lamp_filters = 268.6 ms`, `corp_db.hybrid_primary = 26.8 ms`, `corp_db.merge = 0.8 ms`
- После этого агент всё равно пошёл в wiki:
  - `list_directory(/data/skills/corp-wiki-md-search/)`
  - `read_file(/data/skills/corp-wiki-md-search/SKILL.md)`
  - `run_command(python3 /data/skills/corp-wiki-md-search/scripts/wiki_search.py ...)`
- Во время `run_command` был поднят sandbox:
  - `Creating sandbox for user 5202705269` в `2026-04-04T02:19:44.733692672Z`
  - `Sandbox ... ready` в `2026-04-04T02:20:14.811982336Z`
- Только один этот cold-start занял около `30.1s`.

Кейс `rfc-skill-routing-tech003`

- Вопрос: "Какой вес у светильника LAD LED R500-9-30-6-650LZD? Ответь числом и единицей измерения."
- Итог: `duration_ms = 9924.101`
- `tools_used = ["corp_db_search"]`
- `corp_db_search(kind=lamp_exact)` завершился за `344.91 ms`
- Перехода в wiki, `run_command` и sandbox не было.

### 3. What this proves

- `corp_db` как источник данных не является bottleneck для этой проблемы.
- Ложный переход в wiki происходит уже после успешного `corp_db_search`.
- Основной latency penalty создаёт orchestration overhead, а не database search.
- `run_command` превращает routing mistake в дорогой infrastructure path.

Root cause analysis
-------------------

### Root cause 1. Skill descriptions conflict with the intended precedence

Текущие descriptions и инструкции противоречат друг другу:

- `core/src/agent/system.txt` говорит: "сначала используй поиск по корпоративной базе, если там не нашел - проверь корпоративную wiki".
- Но `shared_skills/skills/corp-wiki-md-search/skill.json` говорит:
  - "Используй, когда вопрос про компанию и нужно отвечать «согласно wiki»."
- А `shared_skills/skills/corp-wiki-md-search/SKILL.md` ещё шире:
  - по сути предлагает wiki как обычный поиск по company-docs.

Для LLM это выглядит как конкурирующее правило:

- `corp-pg-db` про structured DB и promoted KB subset;
- `corp-wiki-md-search` про "вопрос про компанию".

Для company-fact вопроса модель выбирает оба пути, а не только `corp_db`.

### Root cause 2. `corp-pg-db` недостаточно явно покрывает company facts

Текущий `corp-pg-db` skill хорошо описывает:

- светильники;
- коды;
- категории;
- портфолио;
- крепления;
- promoted KB subset.

Но он недостаточно явно маркирует следующие вопросы как свой default-path:

- год основания компании;
- официальный сайт;
- адрес головного офиса;
- официальные соцсети;
- контактные каналы;
- краткие маркетинговые/company facts.

В результате даже после индексации этих документов в БД у модели нет сильного сигнала, что это именно `corp_db`-domain.

### Root cause 3. Нет terminal rule после успешного `kb_search`

В `system.txt` уже есть жёсткие terminal rules для:

- `lamp_exact`
- `portfolio_examples_by_lamp`

Но нет аналогичного правила для успешного:

- `corp_db_search(kind=hybrid_search, profile=kb_search, entity_types=["company"])`

Из-за этого даже успешный `corp_db` ответ не останавливает агент, и он продолжает искать "подтверждение" через wiki.

### Root cause 4. `kb_search` payload слишком большой для простого fact-answering

В воспроизведённом кейсе успешный `corp_db_search` вернул payload размером `53415 chars`.

Это создаёт два побочных эффекта:

- LLM тратит дополнительную итерацию на чтение и интерпретацию результата;
- модель менее уверена, что у неё уже есть короткий, точный и достаточный факт, поэтому идёт за вторым источником.

Для simple company-fact path это неверный contract: агенту нужен компактный authoritative answer, а не большой retrieval dump.

### Root cause 5. Wiki path реализован через shell and sandbox

`corp-wiki-md-search` фактически исполняется через:

- `list_directory`
- `read_file`
- `run_command`
- `python3 wiki_search.py ...`

Это делает цену ложного routing decision непропорционально высокой:

- shell path дороже встроенного tool call;
- он может инициировать создание sandbox;
- в bench и fresh runtime именно этот path даёт крупнейший long tail.

High-level behavior
-------------------

После исправления поведение должно быть таким:

1. Если вопрос является company fact / contact / website / address / social / general corporate info, агент сначала вызывает `corp_db_search`.
2. Для таких вопросов default-path должен быть:
   - `kind=hybrid_search`
   - `profile=kb_search`
   - при необходимости `entity_types=["company"]`
3. Если `corp_db_search` вернул `success` и вопрос требует короткий факт, агент отвечает сразу.
4. Агент не читает `corp-wiki-md-search/SKILL.md` и не вызывает `run_command` после успешного `corp_db_search`, если:
   - пользователь не просил "согласно wiki", "процитируй документ", "покажи фрагмент";
   - `corp_db_search` не вернул `empty`;
   - не требуется свободный текстовый контекст, отсутствующий в БД.
5. В wiki агент идёт только по одному из условий:
   - `corp_db_search` вернул `empty`;
   - `corp_db_search` вернул error / unavailable;
   - пользователь явно запросил wiki-text / document-context.

Routing policy and precedence
-----------------------------

### 1. Prompt-level precedence

В `core/src/agent/system.txt` нужно зафиксировать более жёсткое правило:

- для вопросов про компанию, контакты, реквизиты, сайт, адрес, соцсети, сервис, гарантию и общие факты сначала использовать `corp-pg-db`;
- `corp-wiki-md-search` использовать только если `corp_db_search` не нашёл ответ или нужен именно wiki-text context.

Дополнительно нужен explicit terminal rule:

- если `corp_db_search(kind=hybrid_search, profile=kb_search)` вернул `success` для company-fact вопроса, не делать `corp-wiki-md-search`, `run_command`, `list_directory` или `read_file`.

### 2. Skill description cleanup

`corp-pg-db` description нужно расширить так, чтобы в ней явно были:

- company facts;
- contacts;
- website;
- address;
- socials;
- promoted KB / indexed company documents.

`corp-wiki-md-search` description нужно сузить:

- "используй только для документов, которых ещё нет в corp-db, или когда нужен прямой текстовый контекст из wiki".

Фраза уровня "когда вопрос про компанию" должна быть удалена, потому что именно она делает wiki default candidate.

### 3. Runtime guardrail after successful corp-db

Нужен один из двух вариантов:

Option A, prompt-only v1:

- зафиксировать terminal rule только в `system.txt` и skills.

Option B, stronger runtime v1.1:

- добавить lightweight post-tool guardrail в `core`, который помечает успешный `corp_db_search profile=kb_search` как authoritative for company-fact intents и блокирует wiki tool calls в этом же turn.

Option B надёжнее и меньше зависит от поведения модели.

Data path changes
-----------------

### 1. Compact corp-db answer shape for company facts

Для company-fact вопросов `corp_db_search` не должен возвращать 50k+ chars retrieval dump.

В v1 допустимы два подхода:

- уменьшить payload `kb_search` для `entity_types=["company"]` до top snippets + short summary;
- добавить новый узкий `kind`, например `company_fact`, возвращающий компактный authoritative payload.

Предпочтительный path:

- сохранить существующий `corp_db_search`;
- добавить компактный contract для company facts без shell/wiki fallback.

### 2. Wiki should not depend on shell in the hot path

Даже после исправления prompt rules wiki останется fallback. Но его текущая реализация через `run_command` слишком дорогая.

В v2:

- wiki search должен стать first-class tool или `tools-api` route;
- `wiki_search.py` должен выполняться server-side без sandbox;
- `run_command` не должен быть обязательной частью normal retrieval routing.

Это снизит цену residual fallback и уберёт cold-start penalty.

Observability and bench gates
-----------------------------

### 1. Bench must assert routing, not only answer quality

Текущий bench проверяет только correctness ответа. Этого недостаточно.

Нужны route-level assertions для кейсов, которые уже покрыты `corp_db`:

- если company-fact кейс прошёл через `corp_db_search success`, то `run_command` должен считаться regression;
- `list_directory` / `read_file` по wiki skill после успешного `corp_db_search` должны считаться regression;
- для таких кейсов нужен latency target, например `p95 < 15s`.

### 2. Add routing signals to logs/traces

Для triage нужны отдельные признаки:

- `retrieval.intent=company_fact`
- `retrieval.selected_source=corp_db|wiki`
- `retrieval.wiki_after_corp_db_success=true|false`
- `sandbox.created=true|false`

Это позволит быстро отделять "медленный corp_db" от "ложный wiki fallback".

Error handling and UX
---------------------

- Пользователь не должен видеть внутреннее различие между БД и wiki.
- При `corp_db empty` агент честно говорит, что подтверждённой информации не найдено, и только потом идёт в wiki fallback.
- При отсутствии данных и в БД, и в wiki агент не придумывает ответ.
- Если wiki fallback всё же нужен, он не должен ломать SLA для простых company-fact вопросов.

Update cadence / Lifecycle
--------------------------

Фаза 1, immediate

- исправить `system.txt`;
- исправить `corp-pg-db` и `corp-wiki-md-search` descriptions;
- добавить terminal rule после успешного `kb_search`;
- обновить bench expectations.

Фаза 2, short-term

- сузить/переформатировать `corp_db` payload для company-fact retrieval;
- добавить route assertions в bench;
- добавить observability поля про selected source и wiki-after-success.

Фаза 3, medium-term

- убрать shell/sandbox dependency из wiki hot path;
- перевести wiki fallback на builtin/server-side tool.

Future-proofing
---------------

- Если позже снова появятся документы, которые ещё не попали в БД, wiki сохранится как fallback-source.
- Если company-doc corpus продолжит расти, compact company-fact contract можно расширять без изменения пользовательского API.
- Если понадобится более строгий control plane, prompt-level rules можно дополнить runtime policy layer без пересборки DB search.

Implementation outline
----------------------

1. Prompt and skill policy

- Обновить `core/src/agent/system.txt`.
- Обновить `shared_skills/skills/corp-pg-db/SKILL.md` и `skill.json`.
- Обновить `shared_skills/skills/corp-wiki-md-search/SKILL.md` и `skill.json`.

2. Runtime routing hardening

- Добавить guardrail на path "successful company-fact corp_db -> no wiki in same turn".
- При необходимости ограничить wiki tool availability для такого intent.

3. Data contract

- Сузить `kb_search` payload для company facts или добавить отдельный compact `kind`.

4. Observability and bench

- Добавить route assertions в bench eval/report.
- Добавить routing signals в logs/traces.
- Зафиксировать latency target для company-fact cases.

Testing approach
----------------

Unit / prompt tests:

- Проверить, что `system.txt` содержит terminal rule для successful `kb_search`.
- Проверить, что `corp-wiki-md-search` больше не описан как default-source "когда вопрос про компанию".
- Проверить, что `corp-pg-db` явно покрывает company facts.

Integration tests:

- Вопросы про год основания, сайт, адрес, соцсети, консультацию должны завершаться через `corp_db_search` без wiki tools.
- При `corp_db empty` wiki fallback должен по-прежнему работать.
- При explicit request "найди в wiki" wiki path должен оставаться доступным.

Bench tests:

- Повторный full bench не должен показывать `run_command` на company-fact кейсах, покрытых `corp_db`.
- `wiki`-tag кейсы, уже покрытые БД, должны перейти в latency-класс обычных `corp_db` кейсов.

Manual observability:

- Для company-fact запроса по `request_id` должно быть видно:
  - `tool.corp_db_search`
  - отсутствие `run_command`
  - отсутствие sandbox creation
  - короткий end-to-end trace без wiki fallback

Acceptance criteria
-------------------

- Given company-fact вопрос, when данные уже есть в corp-db, then агент отвечает через `corp_db_search` без `run_command`.
- Given successful `corp_db_search profile=kb_search`, when вопрос является коротким fact question, then агент не читает wiki skill и не вызывает wiki search.
- Given company-fact benchmark cases from `bench/golden/v1.jsonl`, when запускается full bench, then эти кейсы не имеют `run_command` в `meta.tool_stats`.
- Given company-fact benchmark cases from `bench/golden/v1.jsonl`, when запускается full bench, then их средняя latency ближе к `non_wiki` cohort, а не к текущим `53.8s`.
- Given реальный wiki-only документ, которого нет в corp-db, when `corp_db_search` возвращает `empty`, then wiki fallback остаётся рабочим.
- Given request triage by `request_id`, when оператор смотрит logs/traces, then он видит, был ли выбран `corp_db`, был ли ложный переход в wiki и создавался ли sandbox.
