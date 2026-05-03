RFC-007 Multiformat Document Search With LiteParse And Tiered Promotion
========================================================================

Status
------

Proposed

Date
----

2026-04-05

Context and motivation
----------------------

RFC-006 правильно зафиксировал, что для коротких company-fact вопросов агент не должен без причины уходить в wiki-path после успешного `corp_db_search`. Но этот RFC решал только routing-проблему для уже промотированных company facts и по сути исходил из устаревшей модели "wiki = markdown corpus".

Эта модель больше не покрывает реальную задачу:

- новые документы поступают в разных форматах, а не только в `md`;
- по ним нужно уметь искать сразу после поступления, без ожидания отдельного ETL в БД;
- по мере накопления статистики запросов часть документов должна отдельно перерабатываться и загружаться в `corp-db`, чтобы наиболее частые и стабильные сценарии обслуживались fast-path через `corp_db_search`.

Целевое состояние теперь двухуровневое:

- `corp_db_search` остаётся default-source для company facts и для часто используемых / отдельно промотированных документов;
- `doc_search` становится bounded document-search tool по полному локальному документному корпусу, включая `pdf`, `doc`, `docx`, `xls`, `xlsx`, `pptx`, `png`, `jpg`, `tiff`, `md`, а `corp_wiki_search` остаётся только alias на переходный период.

Почему сейчас:

- текущая реализация `corp_wiki_search` умеет искать только по `*.md`, что уже не соответствует фактическому формату входящих документов;
- shell-driven или ad hoc document retrieval плохо контролируется по latency, quality и security;
- у LlamaIndex уже есть готовый пакет skills `run-llama/llamaparse-agent-skills`, и для наших текущих целей из него важен именно `liteparse`:
  - local-first parsing;
  - conversion;
  - spatial text extraction;
- это означает, что нам не нужно изобретать parser workflow и prompt recipe с нуля: нужно аккуратно адаптировать и встроить уже существующий skill/workflow в наш bounded retrieval path;
- готовый parser LiteParse уже покрывает локальный parsing/OCR и хорошо подходит как parse-on-demand слой для сложных документов и изображений;
- CLI stack (`rg`, `rga`, `ugrep`, `fd`, `fzf`, `bat`, `jq`) даёт зрелые building blocks для быстрого и объяснимого поиска, но их нужно использовать как server-side implementation detail bounded tool-а, а не как агентский произвольный shell.

Goals:

- Поддержать immediate search по локальному корпоративному документному корпусу для форматов `pdf`, `doc`, `docx`, `xls`, `xlsx`, `pptx`, `png`, `jpg`, `tiff`, `md`.
- Сохранить `corp_db_search` как default-path для company facts и для документов/фрагментов, которые уже промотированы в БД.
- Ввести canonical `doc_search` tool для многоформатного document-search contract без agent-level `run_command`, сохранив `corp_wiki_search` как alias на период миграции.
- Переиспользовать существующий upstream skill `run-llama/llamaparse-agent-skills` как основу для parsing workflows вместо разработки новой skill-логики с нуля.
- Использовать tiered retrieval:
  - fast text/search adapters для дешёвого поиска;
  - LiteParse как parse-on-demand слой для OCR, изображений, сложных PDF и Office-файлов;
  - `corp-db` как hot path для популярных и заранее переработанных документов.
- Ввести статистику использования документов и promotion workflow из document corpus в `corp-db`.
- Усилить observability и security для document processing path.

Non-goals for first implementation (v1)
---------------------------------------

- Полная замена `corp_db_search` unified semantic index-ом по всем документам.
- Автоматическое промотирование документов в БД без review/manifest.
- Идеальное OCR-качество для любых сканов и рукописных документов.
- Экспонирование `rg`, `rga`, `ugrep`, `fd`, `fzf`, `bat`, `jq` как отдельных agent tools.
- Разработка нового parser skill framework, если готовый upstream skill уже покрывает нужный workflow.
- Использование `llamaparse` в production path v1.
- Полноценный UI для операторского triage и promotion в этом же RFC.

Implementation considerations
-----------------------------

- Входной corpus неоднородный:
  - текстовые документы (`md`, позже `txt`, `csv`, `json` по необходимости);
  - PDF с текстовым слоем;
  - Office документы (`doc`, `docx`, `xls`, `xlsx`, `pptx`);
  - изображения (`png`, `jpg`, `tiff`) и сканированные PDF.
- Для text-first форматов нужен максимально дешёвый fast-path без тяжёлого OCR/parsing.
- Для image/scanned/syntax-heavy документов нужен parse-on-demand слой с OCR и layout-aware extraction.
- Документы нельзя считать доверенными только потому, что они корпоративные: ingest может происходить из внешних писем, вложений и ручных загрузок.
- Search stack должен быть bounded и deterministic:
  - агент выбирает только между `corp_db_search` и `doc_search`;
  - внутренняя реализация `doc_search` сама выбирает `fd`, `rg`, `rga`, `ugrep`, `liteparse`, `jq` и cache.
- Нужно следовать философии Unix:
  - каждая утилита делает одну вещь хорошо;
  - утилиты дополняют друг друга, а не дублируют одну и ту же сложную логику;
  - orchestration остаётся простой, прозрачной и наблюдаемой.
- В v1 нужно предпочесть простое и надёжное решение:
  - reuse готового `liteparse` skill/workflow;
  - bounded wrapper вокруг `lit` CLI и CLI search tools;
  - без преждевременного выделения отдельного parser microservice.
- RFC-006 остаётся актуальным для short company facts:
  - успешный `corp_db_search` по company-fact не должен автоматически тянуть document search;
  - explicit doc/document/wiki context должен оставаться отдельным routing signal.

Naming decision
---------------

Название `corp-wiki-search` больше не соответствует фактической роли компонента:

- corpus теперь не ограничен wiki;
- документы могут быть разного происхождения;
- часть документов может вообще не быть "wiki-like";
- пользователю и агенту проще мыслить категорией `document search`, а не `wiki search`.

Поэтому целевое имя в RFC:

- `doc_search` для tool-а;
- `doc-search` для skill-а.

Совместимость:

- `corp_wiki_search` остаётся как deprecated alias на переходный период;
- существующий skill `corp-wiki-md-search` остаётся как deprecated alias/redirect до завершения миграции prompt-ов, tests и bench dataset.

Document intake and storage lifecycle
-------------------------------------

Для удобства и безопасности документы не должны попадать сразу в searchable corpus и не должны храниться как набор произвольных копий по папкам.

v1 вводит простой и надёжный lifecycle:

- `/data/corp_docs/quarantine/` — временная зона приёма новых файлов;
- `/data/corp_docs/live/` — searchable metadata/aliases для валидированных документов;
- `/data/corp_docs/cache/` — parse cache и normalized sidecars;
- `/data/corp_docs/rejected/` — отклонённые файлы и reason metadata;
- `/data/corp_docs/manifests/` — metadata, aliases, ACL, promotion manifests;
- `/data/corp_docs/cas/` — content-addressed storage, каноническое физическое хранилище бинарных файлов.

Ключевой принцип:

- физический файл хранится в CAS ровно один раз;
- `quarantine`, `live` и `rejected` описывают состояние документа и его metadata, а не содержат независимые копии файла.

### Why CAS

CAS нужен для простой и надёжной дедупликации:

- один и тот же документ может приходить из разных каналов;
- имя файла ненадёжно;
- директории и вложенность ненадёжны;
- повторная загрузка того же файла не должна порождать новый физический blob.

Для RFC-007 это лучший practical tradeoff:

- проще, чем сложная dedup-логика по именам и метаданным;
- надёжнее, чем хранение копий в нескольких папках;
- естественно сочетается с parse cache и promotion pipeline.

### CAS model

При ingest:

1. файл сначала попадает в `quarantine`;
2. ingestion job вычисляет `sha256` по содержимому;
3. blob сохраняется в:
   - `/data/corp_docs/cas/sha256/ab/cd/<full_sha256>`
4. если blob уже существует, новый физический файл не создаётся;
5. в manifest создаётся или обновляется document record, который ссылается на существующий CAS blob.

Минимальный manifest record:

```json
{
  "document_id": "doc_01...",
  "sha256": "abcdef...",
  "cas_path": "/data/corp_docs/cas/sha256/ab/cd/abcdef...",
  "original_filename": "R700-fire-cert.pdf",
  "media_type": "application/pdf",
  "size_bytes": 182731,
  "status": "live",
  "source": "admin_upload",
  "created_at": "2026-04-04T12:00:00Z"
}
```

### Dedup semantics

v1 использует только content dedup:

- одинаковый `sha256` => один и тот же физический blob;
- разные файлы с одинаковым именем, но разным содержимым => разные blobs;
- один и тот же blob может иметь несколько logical aliases / source records в metadata.

Это намеренно просто. В v1 не нужен near-duplicate detection:

- разные версии PDF с одной правкой считаются разными документами;
- OCR-equivalent, но бинарно разные файлы не дедуплицируются;
- fuzzy duplicate clustering остаётся вне scope.

### Folder behavior over CAS

`quarantine`, `live`, `rejected` и `manifests` работают поверх CAS так:

- `quarantine` содержит временный upload object до завершения проверки;
- после вычисления hash и валидации blob записывается в CAS;
- `live` хранит только searchable metadata, symlink/alias или thin record на CAS blob;
- `rejected` хранит rejection record и, опционально, quarantined original на короткий retention period;
- `doc_search` читает из `live` manifest и затем открывает соответствующий CAS blob.

Практический вывод:

- searchable corpus остаётся чистым;
- дубли не размножаются;
- cache и parsing привязываются к hash, а не к пути файла;
- переименование документа не ломает dedup и cache.

### Why this remains simple

CAS здесь не должен превращаться в отдельную storage platform.

Простой v1 дизайн:

- один filesystem root;
- один hash algorithm: `sha256`;
- sharded directory layout для избежания слишком больших каталогов;
- JSON manifests;
- atomic rename into CAS;
- no distributed storage;
- no object store requirement;
- no GC complexity beyond periodic sweep of unreferenced blobs.

Именно такая версия CAS соответствует требованию "простое и надёжное решение".

Observed gap in current implementation
--------------------------------------

Текущая реализация не покрывает новое требование по нескольким причинам:

- [core/tools/corp_wiki.py](/home/admin/totosha/core/tools/corp_wiki.py) ищет только по `*.md` через `wiki_root.rglob("*.md")`.
- Skill [shared_skills/skills/corp-wiki-md-search/SKILL.md](/home/admin/totosha/shared_skills/skills/corp-wiki-md-search/SKILL.md) до сих пор описывает wiki как Markdown corpus.
- В результате любой новый `pdf` / `docx` / `xlsx` / `pptx` / image документ сейчас либо невидим для retrieval, либо требует ручного обходного пути.

Это означает, что после устранения ложного wiki fallback в RFC-006 система стала лучше для company-fact latency, но всё ещё не имеет корректного production path для полнотекстового поиска по новым многоформатным документам.

High-level behavior
-------------------

Система после внедрения RFC работает так:

1. Пользователь задаёт вопрос.
2. Agent routing определяет intent:
   - `company_fact` / `promoted_doc_fact` -> сначала `corp_db_search`;
   - explicit `document/wiki/quote/fragment` intent -> `doc_search`;
   - mixed intent -> сначала `corp_db_search`, затем `doc_search` только если нужен document context или `corp_db` дал `empty`.
3. `doc_search` ищет по полному document corpus, а не только по Markdown:
   - сначала использует fast adapters;
   - затем при необходимости включает LiteParse.
4. Tool возвращает нормализованный ответ:
   - `document_id`
   - `relative_path`
   - `file_type`
   - `match_mode`
   - `snippet`
   - `page/sheet/slide` если применимо
   - `cache_hit`
5. Agent отвечает по найденному фрагменту.
6. Search stats записываются для дальнейшего promotion в `corp-db`.
7. Frequently used documents или их выделенные структурированные фрагменты по отдельному pipeline попадают в `corp-db`, после чего похожие вопросы начинают закрываться fast-path через `corp_db_search`.

Tiered retrieval model
----------------------

### Tier 1. `corp_db_search` as default authoritative source

`corp_db_search` остаётся authoritative source для:

- company facts;
- контактов, реквизитов, сервиса, гарантии, адресов, соцсетей;
- заранее переработанных и промотированных документов;
- top-N часто используемых knowledge fragments, которые уже имеют нормализованный retrieval contract в БД.

Это сохраняет выигрыш RFC-006:

- короткие fact-вопросы не платят цену document parsing;
- часто используемые документы обслуживаются быстрее и стабильнее;
- agent не тратит лишние ходы на свободный document search там, где уже есть curated answer.

### Tier 2. `doc_search` as full document corpus search

`doc_search` становится bounded tool для поиска по всему локальному document corpus:

- `md`
- `pdf`
- `doc`, `docx`
- `xls`, `xlsx`
- `pptx`
- `png`, `jpg`, `tiff`

`corp_wiki_search` сохраняется только как backward-compatible alias. Основной semantic contract переносится на `doc_search`.

Upstream skill strategy
-----------------------

Вместо разработки новой skill-логики RFC предлагает опереться на уже существующий upstream repo:

- `run-llama/llamaparse-agent-skills`

Из него для production v1 нам подходит прежде всего `liteparse` skill:

- он local-first;
- не требует cloud dependency;
- уже описывает поддерживаемые форматы, зависимости и `lit` CLI workflow;
- хорошо соответствует цели "простое и надёжное решение".

`llamaparse` из текущего плана исключается:

- он требует внешнюю cloud dependency;
- это противоречит выбранному local-first и simple/reliable подходу;
- обсуждать его имеет смысл только в отдельном будущем RFC, если локальный path реально упрётся в качество, которое нельзя закрыть `liteparse`.

Следствие для нашего RFC:

- мы не переизобретаем parsing skill;
- мы адаптируем локальную skill-интеграцию и bounded tool contract вокруг существующего `liteparse` workflow;
- agent по-прежнему видит простой выбор `corp_db_search` vs `doc_search`, а не zoo из document tools.

Document search engine design
-----------------------------

### 1. Corpus layout

v1 вводит канонический локальный document corpus, доступный для `doc_search`.

Рекомендуемая структура:

- `/data/skills/corp-wiki-md-search/wiki/` для legacy markdown и wiki-like документов;
- `/data/corp_docs/quarantine/` для новых документов до проверки;
- `/data/corp_docs/cas/` для content-addressed blobs;
- `/data/corp_docs/live/` для searchable metadata/aliases поверх CAS;
- `/data/corp_docs/cache/` для parse cache и normalized sidecars;
- `/data/corp_docs/rejected/` для отклонённых файлов и reason metadata;
- `/data/corp_docs/manifests/` для metadata, allowlists, promotion manifests.

В v1 можно сохранить текущий skill path, но tool должен уметь искать как минимум по двум roots:

- legacy wiki root;
- document live root.

### 2. Search execution modes

`doc_search` использует mode `auto` по умолчанию и сам выбирает backend.

#### Mode A. Fast text search

Для уже текстовых или легко извлекаемых документов:

- `rg` как основной fast-path для `md`, `txt`, `json`, `csv` и других plain-text форматов;
- `rga` как recursive multi-format search для `pdf`, `docx`, `xlsx`, `pptx`, архивов и вложенных контейнеров;
- `ugrep` как targeted fallback/override, когда нужен явный filter pipeline, особенно для PDF и Office документов.

Зачем оба `rga` и `ugrep`:

- `rga` хорошо подходит как общий adapter framework поверх `rg`;
- `ugrep` даёт явный `--filter=...` control и удобен для узких режимов вроде `pdf:pdftotext % -` или `soffice --headless --cat %`.

#### Mode B. Parse-on-demand via LiteParse

Если fast-path:

- не дал релевантных совпадений;
- встретил image-only/scanned документ;
- требует OCR;
- требует layout-aware text extraction;
- должен вернуть page-aware snippet по `png/jpg/tiff` или сложному PDF,

tool запускает LiteParse.

LiteParse подходит для этого слоя, потому что по официальному README:

- работает локально без cloud dependencies;
- имеет OCR options и HTTP OCR adapters;
- умеет `PDF`, `DOC/DOCX`, `XLS/XLSX`, `PPT/PPTX`, image formats через conversion layer;
- может возвращать text/JSON и page screenshots.

Дополнительно это решение уже оформлено upstream как готовый `liteparse` skill, который описывает:

- `lit parse`;
- `lit batch-parse`;
- `lit screenshot`;
- OCR options;
- output options;
- optional LibreOffice / ImageMagick dependencies.

Для нашего use case LiteParse не должен становиться universal first step. Его роль в v1:

- accurate fallback;
- OCR fallback;
- parser for complex documents;
- sidecar generator for cache.

Практический вывод: в v1 достаточно thin integration layer вокруг `lit` CLI и его output contracts, а не собственной parser platform.

#### Execution graph, not fixed linear pipeline

Важно: backend selection не должен моделироваться как одна жёсткая цепочка вида:

- `fd -> rg|rga|ugrep -> liteparse -> jq`

Это только один из возможных execution patterns.

Корректнее думать о `doc_search` как о маленьком orchestration graph:

- `fd -> rg`
- `fd -> rga`
- `fd -> ugrep`
- `fd -> liteparse`
- `lit parse file | rg`
- `lit parse file --format json | jq`
- `curl ... | lit parse -`

Причина:

- LiteParse сам умеет писать в stdout и хорошо работает как Unix filter;
- иногда выгоднее сначала распарсить один конкретный файл и потом искать по его stdout/JSON;
- иногда выгоднее сначала сделать coarse search через `rga`, а LiteParse включить только на shortlisted files;
- иногда query уже привязан к конкретному файлу или диапазону страниц, и `fd`/`rga` вообще не нужны.

Поэтому RFC фиксирует не одну линейную цепочку, а набор allowlisted execution patterns внутри bounded executor.

#### Mode C. Cached normalized search

После первого LiteParse прохода tool сохраняет normalized sidecar:

- `text.txt`
- `structured.json`
- `meta.json`

keyed by:

- `sha256(file contents)`
- `mtime`
- `file size`
- parser version
- OCR config hash

В случае CAS canonical key должен быть именно content hash:

- `sha256(file contents)` является primary cache key;
- `mtime` и `file size` используются только как быстрые invalidation hints до повторной проверки hash;
- если два logical document records ссылаются на один CAS blob, parse cache у них общий.

Повторные запросы по тому же документу сначала используют cache, а не повторный parse.

### 3. File discovery and preview tooling

Best-practice CLI stack используется как internal implementation detail:

- `fd` для быстрого discovery по roots, glob patterns и extension filters;
- `rg` / `rga` / `ugrep` для actual matching;
- `bat` для operator/debug preview локальных фрагментов;
- `jq` для разборки LiteParse JSON sidecars и debug/admin workflows;
- `fzf` только для operator tooling и manual triage, не для production agent path.

Важно:

- agent не получает прямого доступа к этим командам;
- tool возвращает нормализованный JSON/text contract;
- shell orchestration живёт только внутри bounded server-side executor;
- инструменты должны гибко дополнять друг друга:
  - `fd` находит кандидатов;
  - `rg` ищет по plain text;
  - `rga` расширяет поиск на многоформатные документы;
  - `ugrep` даёт узкие targeted filters;
  - `liteparse` может включаться как fallback, как file-scoped parser, или как Unix filter в pipe;
  - `jq` нормализует parser output;
  - `bat` помогает с preview и debug;
  - `fzf` остаётся только операторским convenience layer.

Это и есть желаемая Unix-композиция: простой pipeline из малых надёжных компонентов вместо одного хрупкого "умного" монолита.

Routing policy
--------------

### 1. Default routing

- Short company-fact / promoted-doc questions -> `corp_db_search`.
- Explicit `"найди в документе"`, `"процитируй"`, `"покажи фрагмент"`, `"поиск по pdf/docx/xlsx"` -> `doc_search`.
- Если `corp_db_search` дал `empty` и вопрос по смыслу относится к documents/policies/specs/manuals/certificates -> `doc_search`.

### 2. Guardrail update

Guardrail из RFC-006 должен быть уточнён:

- блокировать `doc_search` после успешного `corp_db_search` только для short company facts и promoted facts;
- не блокировать `doc_search`, если пользователь явно просит document fragment, quote, certificate, manual, specification, scan или file-backed context.

Это убирает ложную жёсткость RFC-006 и сохраняет нужный fast-path.

### 3. Skill semantics

Skill `doc-search` должен стать основным document corpus skill.

Для v1 достаточно conservative path:

- ввести новый canonical skill `doc-search`;
- ввести новый canonical tool `doc_search`;
- сохранить `corp-wiki-md-search` и `corp_wiki_search` как deprecated aliases;
- переписать description и examples с Markdown-only на multiformat corpus;
- добавить в skill явную отсылку к upstream `liteparse` workflow и его зависимостям.

Promotion from document corpus to corp-db
-----------------------------------------

### 1. Why promotion exists

Не все документы должны сразу попадать в `corp-db`.

Причины:

- часть документов редкая и нужна только occasional document search;
- часть документов тяжёлая для структурирования;
- некоторые документы часто меняются и не стоят стоимости постоянного DB ingest;
- immediate availability важнее мгновенной индексации в БД.

Поэтому `doc_search` обслуживает long tail, а `corp-db` обслуживает hot set.

### 2. Promotion criteria

Документ или его отдельные фрагменты становятся кандидатами на promotion в `corp-db`, если выполняется одно или несколько условий:

- высокий query frequency;
- высокий answer yield;
- низкая tolerance к latency;
- часто задаются короткие fact-like вопросы по одному и тому же документу;
- содержимое относительно стабильно;
- есть ясный структурированный extraction contract.

### 3. Stats to collect

`doc_search` записывает:

- `query`
- `intent_class`
- `document_id`
- `file_type`
- `match_mode` (`rg`, `rga`, `ugrep`, `liteparse`, `cache`)
- `duration_ms`
- `cache_hit`
- `selected_result_rank`
- optional `answer_success`

На основе этих данных отдельный operator job формирует promotion candidates.

### 4. Promotion workflow

1. Статистика document hits копится в logs/metrics/table.
2. Operator job строит top candidate list.
3. Для выбранных документов создаётся/обновляется manifest promotion.
4. Отдельный ETL перерабатывает документ:
   - chunking
   - normalization
   - metadata extraction
   - optional structured fields
5. Документ попадает в `corp-db`.
6. Routing policy начинает трактовать его как preferred `corp_db_search` path.

Tool contract changes
---------------------

`doc_search` v2 contract рекомендуется расширить:

```json
{
  "query": "сертификат пожарной безопасности R700",
  "top": 5,
  "context": 2,
  "file_types": ["pdf", "docx"],
  "mode": "auto",
  "include_metadata": true
}
```

Нормализованный result:

```json
{
  "status": "success",
  "query": "сертификат пожарной безопасности R700",
  "results": [
    {
      "document_id": "sha256:...",
      "relative_path": "certs/fire/r700-fire-2026.pdf",
      "file_type": "pdf",
      "match_mode": "rga",
      "snippet": "....",
      "page": 2,
      "score": 0.91,
      "cache_hit": true
    }
  ]
}
```

`mode`:

- `auto` -> normal production path;
- `fast` -> only `rg` / `rga` / `ugrep`, без LiteParse;
- `accurate` -> допускает LiteParse и OCR;
- `debug` -> admin-only, возвращает backend details.

Error handling and UX
---------------------

Категории ошибок:

- unsupported file / corrupt file;
- parse timeout;
- OCR unavailable;
- document not found;
- no matches;
- cache mismatch / stale cache;
- backend dependency missing (`rga`, `ugrep`, LibreOffice, ImageMagick, LiteParse).

User-facing behavior:

- если `corp_db_search` дал ответ, agent не говорит о внутреннем document routing;
- если `doc_search` не нашёл совпадений, agent честно говорит, что в корпоративных документах совпадение не найдено;
- если parse path упёрся в timeout или OCR unavailable, agent сообщает, что документ найден, но автоматически извлечь текст сейчас не удалось, и предлагает сузить запрос или указать файл/раздел.

Operator-facing behavior:

- в logs/traces видно backend mode и parser/adapters;
- admin/debug path показывает dependency/adapter failure отдельно от no-match.

Security model
--------------

Этот RFC улучшает production security только если document parsing остаётся bounded service-side path.

### 1. What improves

- agent больше не должен ходить в произвольный `run_command` ради document search;
- search stack централизуется в одном tool executor;
- появляется единый allowlisted parsing/search path вместо agent-driven shell composition;
- можно централизованно применять timeouts, file-size limits и parser resource limits.

### 2. New risks

LiteParse по своему security policy считает обработку untrusted documents ответственностью deployer-а, а не самой библиотеки. Это означает:

- malicious uploads;
- malformed PDFs;
- zip bombs / decompression bombs;
- path traversal in filenames;
- resource exhaustion;
- oversized scans/images

должны обрабатываться нашим deployment perimeter, а не оставляться parser-у по умолчанию.

Это прямой вывод из официального `SECURITY.md` LiteParse.

### 3. Required security controls

Document parsing path должен выполняться с отдельными ограничениями:

- bounded execution boundary для parsing;
- CPU / memory / wall-clock limits;
- page count limits;
- file size limits;
- allowlisted converters only;
- sanitized filenames and storage paths;
- no macro execution;
- no network egress for local parse path;
- bounded concurrency;
- parse cache quotas and eviction policy.
- CAS root доступен только ingestion/search runtime, но не agent write path.

Дополнительно:

- `ImageMagick` policy должна быть зафиксирована безопасной конфигурацией;
- `LibreOffice --headless` используется только внутри bounded executor с лимитами;
- `ugrep --filter` и любые shell filters не должны принимать raw user-controlled shell fragments.
- upload path никогда не пишет напрямую в `live`; только ingestion pipeline может создать live-record поверх CAS blob.

Важное упрощение:

- v1 не требует отдельного parser microservice;
- достаточно одного надёжного bounded executor/process boundary вокруг `lit`, `rga`, `ugrep` и сопутствующих утилит;
- выделение отдельного parsing service оправдано только если это покажут реальные метрики нагрузки, изоляции или операционной сложности.

Update cadence / Lifecycle
--------------------------

Document lifecycle в целевой схеме:

1. Документ попадает в `quarantine`.
2. Ingestion pipeline валидирует его и вычисляет `sha256`.
3. Blob сохраняется в CAS или переиспользуется, если уже существует.
4. После успешной проверки создаётся `live` record, и документ становится immediately searchable через `doc_search`.
5. По мере запросов копится usage statistics.
6. Если документ часто востребован, его содержимое или выбранные chunks промотируются в `corp-db`.
7. После promotion короткие вопросы по нему начинают закрываться через `corp_db_search`.
8. Если документ обновился, его hash меняется:
   - parse cache invalidируется;
   - promotion candidates пересматриваются;
   - при необходимости ETL в БД делает re-ingest.

Future-proofing
---------------

Решение закладывает расширение без слома contracts:

- можно добавить новые форматы без изменения agent API, расширяя internal adapter registry;
- можно при необходимости вынести parsing boundary в отдельный сервис, сохранив tool name `doc_search`;
- можно добавить semantic reranking поверх normalized snippets позже;
- можно постепенно переименовать skill из wiki-oriented в doc-oriented без поломки существующего tool routing;
- можно ввести auto-promotion recommendations, не меняя production retrieval contract.

Implementation outline
----------------------

1. Corpus and skill redefinition
   - ввести `doc-search` как canonical multiformat document corpus skill;
   - оставить `corp-wiki-md-search` как deprecated alias на период миграции;
   - зафиксировать upstream dependency на `run-llama/llamaparse-agent-skills`, прежде всего на `liteparse` skill;
   - обновить `SKILL.md`, `skill.json`, `system.txt` и routing examples;
   - зафиксировать, что `corp_db_search` остаётся default-path для company facts и promoted docs.

2. `doc_search` engine v2
   - добавить multi-root discovery;
   - добавить file type classification;
   - внедрить allowlisted execution graph вокруг `fd`, `rg`, `rga`, `ugrep`, `liteparse`, `jq`;
   - вернуть нормализованный structured payload вместо markdown-like text dump.

3. Intake, CAS and metadata
   - ввести `quarantine -> cas -> live/rejected` lifecycle;
   - вычислять `sha256` и складывать blobs в CAS;
   - хранить manifests и aliases отдельно от blobs;
   - не допускать прямого попадания новых файлов в `live`.

4. Parse cache and metadata
   - ввести hash-based cache поверх CAS blobs;
   - сохранять normalized text/json sidecars;
   - добавить invalidation on file change.

5. Security hardening
   - вынести parsing в bounded execution boundary с лимитами;
   - добавить timeouts, quotas и dependency allowlist;
   - убрать любые agent-level shell paths для document retrieval.

6. Observability and stats
   - метрики по `match_mode`, `file_type`, `cache_hit`, `duration_ms`, `parse_duration_ms`;
   - traces по backend selection;
   - usage stats для promotion.

7. Promotion pipeline
   - определить schema для document usage stats;
   - сделать candidate report;
   - добавить operator flow для promotion manifest и ETL в `corp-db`.

8. Bench and regression gates
   - добавить bench cases по `pdf/docx/xlsx/pptx/png/jpg/tiff/md`;
   - развести quality, routing и parser-latency assertions;
   - отдельно проверять, что company-fact queries не падают обратно в document path без необходимости.

Testing approach
----------------

Unit:

- file type detection;
- CAS path derivation;
- dedup by content hash;
- backend selection policy;
- cache key / invalidation;
- result normalization;
- routing rules `corp_db` vs `corp_wiki`;
- guardrail exceptions для explicit document requests.

Integration:

- `doc_search` по corpus с `md`, `pdf`, `docx`, `xlsx`, `pptx`, `png`, `jpg`, `tiff`;
- repeated upload of identical file does not create a second blob;
- multiple logical aliases can point to one CAS blob;
- fast-path search via `rg` / `rga` / `ugrep`;
- LiteParse fallback и cache hit on second request;
- dependency missing scenarios;
- promotion stats write path.

Manual / E2E:

- explicit query "найди в pdf";
- scanned PDF с OCR;
- image-only certificate;
- mixed query: short company fact + "покажи фрагмент документа";
- same question before and after promotion to `corp-db`.

Bench:

- latency buckets для `corp_db_search` vs `doc_search fast` vs `doc_search accurate`;
- routing checks: no wiki/doc search after successful company-fact `corp_db_search`, unless explicit doc intent;
- quality checks against known documents across all target formats.

Acceptance criteria
-------------------

- `doc_search` в production path умеет искать минимум по `pdf`, `doc`, `docx`, `xls`, `xlsx`, `pptx`, `png`, `jpg`, `tiff`, `md`.
- identical uploaded files are stored once in CAS and reused via metadata/aliases.
- Для plain-text и text-layer documents tool использует fast-path без обязательного LiteParse запуска.
- Для scanned/image documents tool умеет переходить в LiteParse/OCR path и возвращать page-aware snippet.
- Agent не использует `run_command` для production document search.
- Short company-fact questions после успешного `corp_db_search` не уходят в `doc_search`, если пользователь явно не запросил document context.
- Explicit document/quote/fragment questions могут идти в `doc_search` даже после `corp_db_search`, если это нужно по смыслу запроса.
- Есть usage stats, достаточные для построения promotion candidates в `corp-db`.
- Frequently used documents могут быть отдельно промотированы в `corp-db` без изменения публичного agent contract.
- У document parsing path есть timeouts, resource limits и isolated execution boundary.
- Bench покрывает multi-format retrieval и ловит regressions по routing, quality и latency.

References
----------

- LlamaParse Agent Skills: https://github.com/run-llama/llamaparse-agent-skills
- LiteParse README: https://github.com/run-llama/liteparse
- LiteParse security policy: https://github.com/run-llama/liteparse/blob/main/SECURITY.md
- ripgrep: https://github.com/BurntSushi/ripgrep
- ripgrep-all: https://github.com/phiresky/ripgrep-all
- ugrep: https://github.com/Genivia/ugrep
- fd: https://github.com/sharkdp/fd
- fzf: https://github.com/junegunn/fzf
- bat: https://github.com/sharkdp/bat
- jq: https://jqlang.org/
