RFC-009 Index-Driven Routing And LiteParse-First Doc Search
===========================================================

Status
------

Proposed

Date
----

2026-04-05

Context and motivation
----------------------

RFC-007 правильно расширил поиск с markdown-only corpus до многоформатных документов, но текущее состояние всё ещё создаёт три проблемы:

1. routing сформулирован слишком абстрактно как "short company facts -> corp_db_search, document-context -> doc_search", и это оставляет место для эвристик и путаницы;
2. intake flow для admin-only загрузки через репозиторий не зафиксирован как простой и воспроизводимый operational path;
3. внутренняя реализация `doc_search` пока не использует простую unified normalization model вокруг `liteparse`, хотя именно она лучше всего соответствует требованию "простое и надёжное решение".

Дополнительное наблюдение по текущей реализации:

- `doc_search` уже встроен как builtin tool, а не исполняется через skill shell-path;
- upstream `liteparse` skill присутствует как reusable workflow, но фактический executor в проекте сейчас вызывает `lit` напрямую только если бинарник установлен;
- в текущем `core` image нет гарантированной установки `lit`, `LibreOffice` и `ImageMagick`, поэтому production path ещё не соответствует RFC-007 полностью;
- текущий search engine остаётся mixed-mode: часть форматов парсится Python-кодом, часть уходит в optional `lit`, а часть будущих утилит (`rga`, `ugrep`) фигурирует только в RFC, но не в runtime.

Этот RFC предлагает сделать следующий шаг: перевести routing и document search в более строгую и простую модель.

Goals
-----

- Заменить intent-like routing на index-driven routing с явными route cards для `corp_db_search` и `doc_search`.
- Зафиксировать один понятный admin-only intake path через папку в репозитории.
- Перевести `doc_search` на LiteParse-first normalization pipeline:
  - raw document -> normalized sidecars;
  - поиск не по сырым файлам, а по нормализованному searchable representation.
- Свести production-critical Unix stack к минимальному и поддерживаемому ядру:
  - `fd`
  - `rg`
  - `jq`
  - `lit`
- Оставить `rga` и `ugrep` как optional accelerators / operator tools, а не как обязательную часть production contract.
- Сохранить CAS как canonical storage и thin live manifests.

Non-goals
---------

- Полноценный UI для загрузки документов.
- Автоматическая semantic routing модель или embedding router.
- Использование `llamaparse` в v1.
- Обязательное использование `rga` и `ugrep` в hot path.
- Автоматический promotion в `corp-db` без review.

Analysis of current state
-------------------------

### 1. Routing is still heuristic

Сейчас routing на практике определяется смесью:

- системного prompt;
- keyword heuristics в агенте;
- runtime guardrails;
- частично implicit skill descriptions.

Это уже лучше, чем раньше, но не является достаточно прозрачным источником истины.

Проблема не в том, что правило "company facts -> corp_db" неверное. Проблема в том, что оно описано на уровне intent, а не на уровне явного каталога доступных knowledge domains.

### 2. Intake flow is not operationally crisp

Сейчас из кода видно:

- есть CAS-backed storage;
- есть quarantine/live/rejected/manifests;
- есть CLI `scripts/doc_ingest.py`;
- но не определён канонический repo folder, куда admin кладёт файл, чтобы он гарантированно дошёл до ingestion и стал searchable.

Для эксплуатации это плохой UX: система умеет ingest, но пользовательский путь для администратора не закреплён.

### 3. Search stack is more complex than necessary

Текущий runtime смешивает:

- прямое чтение текстовых файлов;
- Python XML extractors для `docx/xlsx/pptx`;
- heuristic extraction для `pdf`;
- optional `lit parse`.

Это рабочий промежуточный вариант, но он хуже поддерживается, чем один unified parser boundary.

Если `lit` гарантированно установлен вместе с `LibreOffice` и `ImageMagick`, то production path можно упростить:

- ingestion нормализует документы в один searchable format;
- query path ищет по уже нормализованным sidecars;
- format-specific parsing logic почти исчезает из runtime search.

Why LiteParse-first is the right simplification
-----------------------------------------------

По официальному README LiteParse поддерживает:

- Office документы через `LibreOffice`;
- изображения через `ImageMagick`;
- auto-conversion в PDF перед parsing;
- CLI `lit parse` и JSON/text output;
- agent skill с явным workflow.

Это важно по двум причинам:

1. нам не нужно поддерживать собственный zoo extractors как production source of truth;
2. мы можем сделать `doc_search` простым:
   - ingestion делает normalization;
   - query path делает retrieval по sidecars.

Вывод:

- `LiteParse + LibreOffice + ImageMagick` должны быть обязательной частью `doc_search` runtime для v1.1;
- если этих зависимостей нет, supported-format promise не выполняется;
- до их появления `.doc/.xls/.ppt` действительно небезопасно и неполно поддерживать;
- после появления bounded LiteParse-first conversion boundary их можно вернуть в allowlist.

Proposed architecture
---------------------

Система делится на три простых слоя:

1. routing index
2. ingestion and normalization
3. query execution

### 1. Routing index

Вместо размытой классификации по intent вводится единый retrieval routing index.

Он строится из двух источников:

- `corp_db` index cards
- `doc_corpus` index cards

Каждая карточка описывает тему, а не конкретный tool call.

Минимальный contract:

```json
{
  "route_id": "db.company_profile.contacts",
  "source": "corp_db_search",
  "title": "Контакты и реквизиты компании",
  "summary": "Сайт, адрес, телефон, email, реквизиты, соцсети",
  "tags": ["контакты", "сайт", "адрес", "телефон", "email", "реквизиты"],
  "authoritative": true,
  "kind": "table_topic",
  "target": {
    "kind": "hybrid_search",
    "profile": "kb_search",
    "entity_types": ["company"]
  }
}
```

```json
{
  "route_id": "doc.fire_certificate_line",
  "source": "doc_search",
  "title": "Пожарный сертификат серии LINE",
  "summary": "Сертификаты, сроки действия, PDF и сканы по серии LINE",
  "tags": ["сертификат", "line", "пожарный", "pdf", "скан"],
  "authoritative": true,
  "kind": "document_topic",
  "target": {
    "document_id": "doc_abcd1234",
    "file_type": "pdf"
  }
}
```

### Routing algorithm

Routing больше не пытается сначала "угадать intent". Он делает lookup по index cards.

Алгоритм:

1. Если пользователь явно просит:
   - "покажи фрагмент"
   - "процитируй"
   - "найди в документе"
   - "pdf/docx/xlsx"
   то выбор принудительно идёт в `doc_search`.
2. Иначе router ищет top matches по routing index.
3. Если лучший hit относится к `corp_db_search` и имеет явный перевес по score, выбирается `corp_db_search`.
4. Если лучший hit относится к `doc_search`, выбирается `doc_search`.
5. Если score близки:
   - сначала выбирается authoritative `corp_db_search` только для table-backed concise facts;
   - для file-backed topics, certificates, manuals, scans, policies выбирается `doc_search`.

Это делает routing:

- простым;
- объяснимым;
- дебажимым;
- расширяемым без переписывания keyword heuristics.

### 2. Repo-based intake and normalization

Для v1 вводится один канонический admin-only путь:

- admin кладёт файл в `[doc-corpus/inbox/](/home/admin/totosha/doc-corpus/inbox/)`

Опционально рядом кладётся sidecar metadata:

- `<filename>.meta.json`

Пример:

```json
{
  "title": "Пожарный сертификат серии LINE",
  "summary": "Сертификат соответствия по серии LINE",
  "tags": ["сертификат", "line", "пожарный"],
  "authoritative": true
}
```

Почему именно так:

- путь понятен администратору;
- не нужен UI;
- не нужен watcher daemon;
- ingestion можно запускать вручную или pre-deploy hook-ом;
- repo остаётся единственной точкой операционного ввода на первом этапе.

### Intake flow

Файл становится доступен агенту так:

1. Admin копирует файл в `doc-corpus/inbox/`.
2. Admin запускает:

```bash
python scripts/doc_ingest.py sync-repo
```

3. Скрипт для каждого файла делает:
   - определение MIME и extension;
   - size limits;
   - hash `sha256`;
   - CAS dedup;
   - parser dependency checks;
   - normalization через `lit`;
   - запись sidecars;
   - создание manifest;
   - создание routing card;
   - атомарный перевод документа в `live`.

4. После успешного завершения документ searchable через `doc_search`.

Если что-то не прошло:

- создаётся rejection record в `/data/corp_docs/rejected/`;
- raw blob в `live` не попадает;
- routing card не публикуется.

### Required statuses

Минимальные статусы:

- `quarantine`
- `validated`
- `normalized`
- `live`
- `rejected`

Принцип:

- searchable становится только `live`;
- `live` появляется только после успешной normalization.

### Filesystem layout

Repo-side:

- `[doc-corpus/inbox/](/home/admin/totosha/doc-corpus/inbox/)`
- `[doc-corpus/manifests/](/home/admin/totosha/doc-corpus/manifests/)`

Runtime-side:

- `/data/corp_docs/quarantine/`
- `/data/corp_docs/cas/`
- `/data/corp_docs/parsed/`
- `/data/corp_docs/live/`
- `/data/corp_docs/rejected/`
- `/data/corp_docs/manifests/routes/`

`parsed/` хранит normalization sidecars:

- `text.txt`
- `pages.jsonl`
- `meta.json`

Все sidecars привязаны к `sha256`, а не к исходному имени файла.

### 3. Query execution

`doc_search` больше не должен искать по сырым документам в hot path.

Он работает по нормализованным sidecars.

#### Canonical production stack

- `fd` — discovery sidecars and manifests
- `rg` — full-text search по normalized text / JSONL
- `jq` — извлечение page/sheet/slide metadata и snippet shaping
- `lit` — normalization at ingest time and fallback reparse

#### Optional tools

- `rga`
- `ugrep`

Они могут быть полезны:

- для operator debugging;
- для ad hoc maintenance;
- для миграции старого corpus;
- для сравнения качества/latency.

Но они не должны быть обязательной частью public production path. Иначе система становится тяжелее в поддержке без необходимости.

Search model
------------

### Normalization contract

На ingestion каждый document получает unified parsed representation:

- `text.txt` — полный collapsed text;
- `pages.jsonl` — page or logical chunk level records;
- `meta.json` — parse backend, file type, page count, OCR flags.

Пример `pages.jsonl`:

```json
{"chunk":1,"page":1,"text":"Сертификат пожарной безопасности серии LINE ..."}
{"chunk":2,"page":2,"text":"Срок действия сертификата до 2028 года ..."}
```

### Query algorithm

1. Router выбрал `doc_search`.
2. `doc_search` по routing cards ограничивает candidate set:
   - весь corpus;
   - или один тематический поднабор;
   - или конкретный `document_id`, если route hit точный.
3. `fd` находит relevant sidecars.
4. `rg` ищет query terms по `pages.jsonl` и `text.txt`.
5. `jq` извлекает лучшие chunks и связанный metadata.
6. Tool возвращает:
   - `document_id`
   - `relative_path`
   - `file_type`
   - `snippet`
   - `page/sheet/slide`
   - `match_mode`
   - `parser_backend`

### Match modes

Для простоты нужны только:

- `normalized_rg`
- `normalized_exact`
- `normalized_filename`
- `reparse_lit`

Это лучше, чем плодить backend names по каждой утилите.

### Reparse policy

Обычный поиск не запускает parser на каждый запрос.

`lit` используется:

- на intake;
- на cache rebuild;
- на explicit repair path;
- на lazy fallback, если sidecar отсутствует или parser version устарела.

Это критично для latency и predictability.

Format policy
-------------

После перехода на LiteParse-first normalization supported set становится таким:

- Text: `md`, `txt`, `csv`, `json`
- PDF: `pdf`
- Office via LibreOffice: `doc`, `docx`, `docm`, `odt`, `rtf`, `ppt`, `pptx`, `pptm`, `odp`, `xls`, `xlsx`, `xlsm`, `ods`, `csv`, `tsv`
- Images via ImageMagick: `jpg`, `jpeg`, `png`, `gif`, `bmp`, `tiff`, `webp`, `svg`

Важно:

- `.doc/.xls/.ppt` можно вернуть в allowlist только после того, как `lit + LibreOffice` станут обязательной частью bounded normalization path;
- до этого момента их reject policy остаётся правильной защитной временной мерой.

Security model
--------------

Даже при LiteParse-first подходе безопасность строится так:

- агент не вызывает произвольный shell path;
- `doc_search` использует allowlisted executor;
- `lit` запускается с timeout, CPU/RAM limits и bounded temp dir;
- `LibreOffice` и `ImageMagick` используются только внутри этого executor;
- generic file tools не получают прямой доступ к managed corpus;
- `ImageMagick` должен работать с безопасной policy;
- normalization происходит до публикации в `live`.

Operational model
-----------------

### What admin does

1. Кладёт файл в `doc-corpus/inbox/`.
2. При необходимости добавляет `.meta.json`.
3. Запускает `python scripts/doc_ingest.py sync-repo`.
4. Проверяет report:
   - ingested
   - rejected
   - duplicate
5. После success документ доступен агенту.

### What system does

1. Берёт raw file из repo inbox.
2. Копирует в runtime quarantine.
3. Делает validation.
4. Пишет blob в CAS.
5. Нормализует через `lit`.
6. Пишет parsed sidecars.
7. Создаёт live manifest.
8. Публикует routing card.

Migration plan
--------------

1. Install runtime dependencies

- добавить в `core` image:
  - `nodejs` / `npm`
  - `@llamaindex/liteparse`
  - `libreoffice`
  - `imagemagick`
  - `jq`
  - `fd`
  - `ripgrep`

2. Introduce repo intake folder

- создать `doc-corpus/inbox/`
- создать `doc-corpus/manifests/`
- добавить `sync-repo` в `scripts/doc_ingest.py`

3. Move parsing to ingest-time normalization

- ввести `/data/corp_docs/parsed/`
- генерировать sidecars по `lit`
- перестать искать по raw files как по primary path

4. Add routing cards

- для `corp_db` таблиц/профилей;
- для каждого `live` документа;
- собрать единый routing index

5. Replace heuristic routing

- перевести agent routing на index lookup;
- оставить explicit document override;
- сохранить guardrails уже поверх index-driven decisions

6. Re-enable legacy Office binaries

- вернуть `.doc/.xls/.ppt` в allowlist только после green integration tests с LiteParse runtime

Testing approach
----------------

Unit:

- route card scoring;
- repo inbox manifest parsing;
- CAS dedup;
- normalization sidecar generation;
- rejected reasons;
- routing precedence `corp_db` vs `doc_search`.

Integration:

- `doc`, `docx`, `xls`, `xlsx`, `ppt`, `pptx`, `pdf`, `png`, `jpg`, `tiff` проходят через `lit`;
- normalized sidecars создаются и searchable через `rg`;
- duplicate raw files не создают duplicate blobs;
- `doc_search` отвечает без повторного parse в hot path;
- routing index выбирает `corp_db` для table topics и `doc_search` для document topics.

Manual:

- admin copies a document into `doc-corpus/inbox/`;
- runs `python scripts/doc_ingest.py sync-repo`;
- sees one clear success or rejection report;
- agent afterwards retrieves the document.

Acceptance criteria
-------------------

- Routing выполняется по явному retrieval index, а не по размытым intent heuristics.
- Admin знает один канонический repo path для загрузки документов: `doc-corpus/inbox/`.
- После `sync-repo` документ либо попадает в `live`, либо получает machine-readable rejection reason.
- `doc_search` ищет по normalized sidecars, а не по raw documents как primary hot path.
- `lit`, `LibreOffice` и `ImageMagick` входят в обязательный runtime stack для document normalization.
- `fd + rg + jq + lit` составляют production-critical core.
- `rga` и `ugrep` не являются обязательными для корректной работы production path.
- `.doc/.xls/.ppt` возвращаются в allowlist только после включения guaranteed LiteParse normalization path.
- Agent-level shell path не используется для document retrieval.

References
----------

- LiteParse README: https://github.com/run-llama/liteparse
- LiteParse supported formats and dependencies: https://github.com/run-llama/liteparse
- LiteParse skill: https://raw.githubusercontent.com/run-llama/llamaparse-agent-skills/main/skills/liteparse/SKILL.md
- LlamaParse Agent Skills repository: https://github.com/run-llama/llamaparse-agent-skills
