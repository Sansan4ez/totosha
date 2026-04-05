RFC-010 LiteParse Integration And Document Search Optimization
==============================================================

Context and motivation
----------------------

Проект уже развился в полноценную platform architecture:

- `core` — latency-sensitive ReAct agent и execution hot path;
- `tools-api` — registry, skills, MCP discovery;
- `admin` — operator control plane;
- `corp-db` — authoritative structured knowledge;
- `corp-db-worker` — operator-only batch processing;
- `workspace/_shared` — persistent shared data plane, смонтированный в контейнеры как `/data`.

На этом фоне document search нельзя рассматривать изолированно. Решение должно быть согласовано с общими принципами платформы:

- security first;
- простой deploy в Docker Compose;
- понятный operator workflow;
- минимальная нагрузка на `core` hot path;
- чёткое разделение read path и write path;
- возможность promotion из document corpus в `corp-db`.

Текущее состояние частично решает задачу, но не полностью:

- `doc_search` уже существует как builtin tool;
- хранение документов переведено на CAS-backed model;
- есть intake CLI и promotion helpers;
- но production path ещё не опирается на обязательный `lit`;
- `core` image не содержит `lit`, `LibreOffice`, `ImageMagick`;
- query path всё ещё смешивает Python extractors, heuristics и optional parser fallback;
- routing ещё опирается на prompt/heuristics больше, чем на явный retrieval catalog.

Этот RFC рассматривает проект как единое целое и выбирает архитектурно правильный способ интегрировать `lit` и оптимизировать document search.

Problem statement
-----------------

Нужно одновременно решить пять задач:

1. Сделать поддержку многоформатных документов реальной, а не декларативной.
2. Не превратить `core` в тяжёлый parser container.
3. Сохранить простой operator-only workflow загрузки документов.
4. Сделать поиск быстрым и предсказуемым на chat path.
5. Подготовить документы к дальнейшему promotion в `corp-db`.

Analysis of the platform as a whole
-----------------------------------

### 1. `core` is the wrong place for heavy parsing

`core` уже выполняет:

- агентный цикл;
- sandbox orchestration;
- tool execution;
- session management;
- API endpoints;
- observability.

Это самый чувствительный к latency и reliability сервис в системе. Установка туда `lit`, `LibreOffice` и `ImageMagick` как обязательных runtime dependencies приведёт к:

- утяжелению образа;
- большему blast radius при parser/runtime проблемах;
- большему security surface;
- усложнению cold start и rebuild path;
- смешению chat hot path и document processing path.

Это противоречит архитектуре проекта.

### 2. `tools-api` is also the wrong place

`tools-api` в этой платформе — registry/control-plane слой:

- описания builtin tools;
- MCP;
- skills discovery;
- enable/disable states.

Он не должен становиться execution engine для document parsing. Иначе мы смешаем control plane и data plane.

### 3. Batch/worker pattern already exists

В проекте уже есть правильный architectural precedent:

- `corp-db-worker` — operator-only batch flow для rebuild/ETL.

Это очень важный сигнал. Document normalization и ingest по смыслу относятся к тому же классу задач:

- тяжёлые;
- batch-like;
- operator-triggered;
- допускают отдельный resource envelope;
- не должны блокировать live chat path.

Следовательно, интеграция `lit` должна идти по worker pattern, а не через `core`.

### 4. Shared data plane already exists

`workspace/_shared` уже используется как persistent shared storage и монтируется как `/data`.

Это делает решение простым:

- raw / normalized / manifests / usage / routes можно хранить в `/data/corp_docs`;
- `core` читает это read-only по факту логики;
- worker пишет туда controlled output;
- дополнительная storage platform не нужна.

Architectural options
--------------------

### Option A. Install `lit` directly into `core` and parse on demand

Плюсы:

- минимальное число новых сервисов;
- проще начать.

Минусы:

- тяжёлые зависимости в hot path;
- parser failures ближе к chat path;
- плохая predictability по latency;
- сильная coupling между agent runtime и parser runtime;
- сложнее ограничивать ресурсы отдельно от `core`.

Verdict:

- подходит как временный переходный этап;
- не лучший целевой вариант для этой платформы.

### Option B. Put `lit` into a dedicated operator-side document worker

Плюсы:

- соответствует existing worker pattern;
- isolates heavy dependencies;
- keeps `core` fast and simpler;
- ingestion and normalization become explicit write path;
- security boundary becomes clearer;
- проще вводить retry/rebuild/resync semantics.

Минусы:

- появляется ещё один service/worker profile;
- нужен явный operator command flow.

Verdict:

- лучший вариант.

### Option C. Extend `corp-db-worker` to also handle doc ingestion

Плюсы:

- reuse существующего operator profile.

Минусы:

- разные ответственности:
  - document normalization;
  - corp-db ETL;
- рост сложности одного worker;
- сложнее lifecycle и observability.

Verdict:

- допустимо как промежуточный шаг;
- но хуже, чем отдельный `doc-worker`.

Recommended decision
--------------------

В проект нужно интегрировать `lit` через новый operator-side service:

- `doc-worker`

Это главный вывод RFC.

`doc-worker`:

- содержит `lit`, `LibreOffice`, `ImageMagick`, `fd`, `rg`, `jq`;
- выполняет intake, validation, normalization, route indexing и rebuild parsed sidecars;
- пишет только в `/data/corp_docs`;
- не участвует в обычном chat request path;
- может запускаться по operator profile, аналогично `corp-db-worker`.

`core` при этом:

- не парсит сырые бинарные документы в нормальном hot path;
- читает только normalized sidecars и manifests;
- выполняет routing и retrieval;
- пишет usage stats best-effort.

High-level architecture
-----------------------

### Control plane

- `admin`
- `tools-api`
- prompt / skill configuration

### Write path

- repo inbox
- `doc-worker`
- `/data/corp_docs/{quarantine,cas,parsed,live,rejected,manifests,routes}`

### Read path

- `core`
- `doc_search`
- read-only access to normalized sidecars and route index

### Structured promotion path

- `corp-db-worker`
- читает promotion candidates / export manifests
- загружает selected fragments into `corp-db`

This separation matches the rest of the platform.

Detailed solution
-----------------

### 1. Introduce `doc-worker`

Новый сервис:

- build context: `./doc-worker` или `./core` с отдельным Dockerfile;
- profile: `operator`;
- volumes:
  - repo root read-only;
  - `./workspace/_shared:/data`;
- resources:
  - больше CPU/RAM, чем у `core`;
- network:
  - только `agent-net`;
- no public port required.

Responsibilities:

- `sync-repo`
- `ingest`
- `rebuild-parsed`
- `rebuild-routes`
- `doctor`

### 2. Make `lit` mandatory in write path

В `doc-worker` устанавливаются:

- `nodejs`
- `npm`
- `@llamaindex/liteparse`
- `libreoffice`
- `imagemagick`
- `ripgrep`
- `fd`
- `jq`

Policy:

- если `lit` или его required backends отсутствуют, ingestion fails loudly;
- документ не публикуется в `live`;
- reason фиксируется в `rejected`.

Это лучше, чем optional parser fallback, потому что support contract становится настоящим.

### 3. Shift parsing from query-time to ingest-time

Главная оптимизация поиска:

- parsing делается при ingest;
- query-time retrieval работает по normalized sidecars.

Нормализованный output на документ:

- `parsed/<sha256>/text.txt`
- `parsed/<sha256>/pages.jsonl`
- `parsed/<sha256>/meta.json`

`pages.jsonl` становится canonical searchable representation.

Следствие:

- поиск становится быстрым;
- latency становится предсказуемее;
- repeated queries не повторяют parsing;
- parser versioning и rebuild управляются отдельно.

### 4. Simplify `doc_search` runtime

`doc_search` должен стать read-only retriever по normalized corpus.

Алгоритм:

1. router даёт candidate scope;
2. `fd` находит relevant parsed sidecars / manifests;
3. `rg` ищет query terms по `pages.jsonl`;
4. `jq` вытаскивает лучшие chunks и их metadata;
5. tool возвращает top snippets.

Fallback policy:

- если sidecar отсутствует или version mismatch:
  - request не должен запускать heavy parser прямо из `core`;
  - он возвращает controlled degraded result или `normalization_missing`;
  - operator потом чинит corpus через `doc-worker rebuild-parsed`.

Это важный platform decision: не превращать chat request в ETL job.

### 5. Add route index as first-class artifact

`doc-worker` публикует route cards в:

- `/data/corp_docs/manifests/routes/*.json`

Есть два вида route cards:

- `corp_db` cards
- `doc_search` cards

`core` читает aggregated routing index при startup / periodic refresh.

Это убирает зависимость от грубых keyword heuristics и делает routing explainable.

### 6. Define repo-based operator workflow

Для admin-only initial workflow:

- repo folder: `[doc-corpus/inbox/](/home/admin/totosha/doc-corpus/inbox/)`

Operator steps:

1. копирует файл в `doc-corpus/inbox/`;
2. при необходимости кладёт `.meta.json`;
3. запускает:

```bash
docker compose run --rm --profile operator doc-worker sync-repo
```

4. смотрит report;
5. после success документ доступен агенту.

Это лучше, чем копирование сразу в `/data/corp_docs`, потому что:

- отделяет source of truth от runtime artifacts;
- поддерживает review via git;
- не ломает lifecycle quarantine/live/rejected;
- проще audit trail.

### 7. Promotion stays separate

`doc-worker` не пишет напрямую в `corp-db`.

Он only prepares:

- normalized content;
- route cards;
- usage-friendly manifests.

`corp-db-worker` или следующий ETL step выполняет:

- export selected chunks;
- load into `corp-db`;
- update corresponding `corp_db` routing cards.

Это сохраняет разделение raw corpus и structured DB.

Search optimization strategy
----------------------------

### Principle 1. Search normalized chunks, not raw files

Это самая важная оптимизация.

### Principle 2. Use routing to reduce candidate set before grep

`doc_search` не должен grep-ить весь corpus на каждый запрос.

Candidate narrowing:

1. explicit route hit by tags/title/summary;
2. document family subset;
3. fallback to whole corpus only if route index low-confidence.

### Principle 3. Keep toolchain minimal

Production-critical:

- `fd`
- `rg`
- `jq`
- `lit`

Optional:

- `rga`
- `ugrep`

Reasoning:

- `rga` и `ugrep` сильные утилиты, но они не обязательны, если есть normalized text sidecars;
- основной смысл normalization как раз в том, чтобы перестать зависеть от format-specific search tools в hot path;
- чем меньше moving parts в read path, тем выше reliability.

### Principle 4. Cache by content hash and parser version

Already aligned with existing CAS approach.

Need to formalize:

- parsed sidecars key = `sha256 + parser_version + OCR config hash`;
- old sidecars are invalidated by version change;
- rebuild handled by `doc-worker rebuild-parsed`.

### Principle 5. Score chunks, not full documents

Scoring должен работать на chunk/page level:

- term hits
- filename bonus
- route-card bonus
- exact phrase bonus

Then aggregate to document result.

Это даёт лучший snippet quality без тяжёлого ranking engine.

Security implications
---------------------

Recommended design improves security overall:

- `core` no longer needs heavy document converters in hot path;
- parser attack surface moves to operator-side worker;
- `doc_search` stays read-only;
- generic file tools still cannot read managed corpus directly;
- `lit`, `LibreOffice`, `ImageMagick` live inside bounded worker execution.

Required safeguards:

- no agent-level `run_command` for document parsing;
- bounded temp dirs;
- CPU/RAM/time limits for worker commands;
- safe ImageMagick policy;
- rejection for encrypted/malformed/problematic files;
- manifests only published after successful normalization.

Impact on existing project structure
------------------------------------

### `core`

Changes:

- simplify `doc_search`;
- remove most format-specific extractors from query path over time;
- keep routing, snippets, usage stats.

Benefits:

- lower complexity;
- more predictable latency;
- smaller parser-related failure surface.

### `tools-api`

Changes:

- mostly none;
- tool definition stays stable;
- may expose doc-worker status later via admin endpoints.

### `admin`

Initial phase:

- no upload UI required.

Later:

- optional page for:
  - sync-repo;
  - ingest status;
  - rejected documents;
  - rebuild parsed corpus.

### `corp-db-worker`

Changes:

- remain responsible for promotion/ETL into `corp-db`;
- consume exports from normalized documents, not raw parser results.

Migration plan
--------------

Phase 1. Introduce `doc-worker`

- add Dockerfile and compose service;
- install `lit`, `LibreOffice`, `ImageMagick`, `fd`, `rg`, `jq`;
- mount repo root read-only and `/data` writable.

Phase 2. Add repo inbox workflow

- create `doc-corpus/inbox/`;
- add `sync-repo` command;
- support `.meta.json` sidecars.

Phase 3. Make ingest produce normalized sidecars

- `parsed/<sha256>/text.txt`
- `parsed/<sha256>/pages.jsonl`
- `parsed/<sha256>/meta.json`

Phase 4. Switch `doc_search` to normalized read path

- first support dual mode;
- then deprecate raw-file parsing in query path.

Phase 5. Introduce route index

- build cards for `corp_db` and documents;
- migrate agent routing to index-driven lookup.

Phase 6. Re-enable legacy Office binaries

- only after green end-to-end tests on `lit` path.

Testing approach
----------------

Unit:

- parser dependency checks;
- route card generation;
- repo inbox manifest parsing;
- chunk scoring;
- versioned parsed sidecars.

Integration:

- `doc-worker sync-repo` on `pdf/doc/docx/xls/xlsx/ppt/pptx/png/jpg/tiff/md`;
- sidecar generation;
- `doc_search` over sidecars only;
- promotion export to `corp-db-worker`.

Operational:

- rebuild one document;
- rebuild whole parsed corpus;
- reject malformed file;
- duplicate upload via CAS;
- route card refresh after ingest.

Acceptance criteria
-------------------

- `lit` is integrated through a dedicated operator-side worker, not as a mandatory parser runtime inside `core`.
- `core` chat hot path does not depend on `LibreOffice` or `ImageMagick`.
- `doc_search` primarily searches normalized sidecars, not raw documents.
- admin-only repo workflow exists and is reproducible.
- route index becomes the primary routing source for `corp_db_search` vs `doc_search`.
- `.doc/.xls/.ppt` are enabled only after the guaranteed LiteParse normalization path is active.
- production-critical read path uses the minimal stack: `fd + rg + jq`.
- parsing/conversion stack is isolated in the write path: `lit + LibreOffice + ImageMagick`.

References
----------

- [README.md](/home/admin/totosha/README.md)
- [ARCHITECTURE.md](/home/admin/totosha/ARCHITECTURE.md)
- [docker-compose.yml](/home/admin/totosha/docker-compose.yml)
- [core/Dockerfile](/home/admin/totosha/core/Dockerfile)
- [core/documents/search.py](/home/admin/totosha/core/documents/search.py)
- [core/tools/doc_search.py](/home/admin/totosha/core/tools/doc_search.py)
- [scripts/doc_ingest.py](/home/admin/totosha/scripts/doc_ingest.py)
- [core/documents/promotion.py](/home/admin/totosha/core/documents/promotion.py)
