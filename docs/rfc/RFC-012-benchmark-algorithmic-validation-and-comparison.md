RFC-012 Benchmark Algorithmic Validation And Comparison
=======================================================

Status
------

Draft (2026-04-05)

Context and motivation
----------------------

Текущий benchmark stack в `bench/` проверяет в основном два слоя:

- текст финального ответа (`answer`) через `contains_any`, `number`, `regex` и похожие проверки;
- routing/meta через `selected_source`, `intent`, `forbid_tools`.

Это уже полезно, но для значительной части датасета такая модель проверки избыточно дорогая и слишком косвенная:

- для exact company facts, exact catalog facts, retrieval по фильтрам и application recommendation система уже получает правильные данные на промежуточном шаге, обычно в tool payload;
- benchmark всё равно ждёт, пока LLM превратит эти данные в prose-ответ;
- затем evaluator проверяет именно prose, а не сами факты или подобранные сущности;
- из-за этого трудно отличить "данные были найдены правильно, но ответ сформулирован неудачно" от "retrieval сам по себе ошибся";
- latency и token cost остаются выше необходимого уровня даже там, где correctness можно проверить алгоритмически.

Сейчас `bench_run.py` сохраняет в results только:

- `answer`;
- `meta`;
- агрегаты usage/routing.

Но не сохраняет сами structured tool outputs, которые уже проходили через agent loop. Это видно в [bench/bench_run.py](/home/admin/totosha/bench/bench_run.py#L296). Соответственно, `bench_eval.py` не может валидировать intermediate correctness и работает только через answer-level checks и routing-level checks в [bench/bench_eval.py](/home/admin/totosha/bench/bench_eval.py#L110).

При этом текущий стек уже даёт важные предпосылки для более дешёвой и точной проверки:

- `corp_db_search` возвращает JSON payload для company facts, exact model lookups, retrieval и application recommendation;
- `doc_search` возвращает JSON payload с документами, match mode и promoted/live records;
- `ToolResult` уже поддерживает `metadata`, то есть structured artifact можно переносить без ломки общего контракта в [core/models.py](/home/admin/totosha/core/models.py#L8);
- `run_meta` уже используется как request-scope накопитель и естественная точка для bench/debug данных в [core/run_meta.py](/home/admin/totosha/core/run_meta.py#L14).

Цель этого RFC: перевести benchmark с answer-first validation к artifact-first algorithmic validation для детерминированных кейсов, не теряя при этом e2e-покрытие там, где оно действительно нужно.

Goals
-----

- Перевести benchmark correctness для детерминированных кейсов на structured algorithmic validation.
- Уменьшить зависимость pass/fail от того, как именно LLM сформулировал финальный текст.
- Снизить latency и LLM cost для benchmark-сценариев, где финальный prose не обязателен для проверки correctness.
- Научиться сохранять и валидировать промежуточные tool artifacts.
- Разделить benchmark на режимы:
  - direct deterministic;
  - agent-with-artifacts;
  - legacy text e2e;
  - comparison/shadow mode.
- Добавить comparison test, который показывает расхождения между legacy answer-based и новым algorithmic validator.
- Сохранить небольшой e2e набор для narrative/format-sensitive кейсов.

Non-goals
---------

- Полный отказ от e2e benchmark с LLM-ответами.
- Автоматическая оценка качества prose, tone of voice или маркетингового стиля.
- Полный generic JSONPath engine или внедрение тяжёлой внешней библиотеки ради evaluation.
- Мгновенный перевод абсолютно всех benchmark-кейсов в один шаг.
- Изменение product behavior только ради benchmark, если correctness можно извлекать из уже существующих payloads.

Design principles
-----------------

- Проверять нужно не то, как модель "сказала", а то, какие данные система реально нашла и выбрала.
- Финальный LLM render должен быть обязательным только там, где benchmark действительно проверяет рендеринг, сравнение, summary или UX-форму ответа.
- Structured artifacts должны сниматься только с allowlisted tools и в bounded объёме.
- Benchmark не должен превращаться в opaque магию: dataset должен явно описывать execution mode и validation mode.
- Shadow comparison обязателен на этапе миграции, чтобы видеть ложные позитивы и ложные негативы нового evaluator.

Current state analysis
----------------------

### 1. Current evaluator is answer-first

Сейчас `bench_eval.py` читает:

- `answer`;
- `meta`;
- `golden.checks`;
- `routing`.

И затем считает verdict как:

- `eval_checks(answer, checks)`
- `eval_routing(meta, routing)`

в [bench/bench_eval.py](/home/admin/totosha/bench/bench_eval.py#L114).

Это означает, что benchmark по умолчанию привязан к финальной natural-language формулировке, даже если кейс по сути проверяет простой structured факт или deterministic selection.

### 2. Current runner drops tool-level correctness artifacts

`bench_run.py` сохраняет ответ и `meta`, но не сохраняет:

- payload успешного `corp_db_search`;
- payload успешного `doc_search`;
- candidate lists;
- resolved application / selected lamp / portfolio examples.

Из-за этого evaluator не может понять:

- был ли retrieval правильным;
- была ли ошибка только в финальном рендере;
- сколько правильных кандидатов было до ответа.

### 3. Current benchmark already contains a large deterministic subset

Аудит текущего `bench/golden/v1.jsonl` показывает 40 кейсов. Из них как минимум 38 уже подходят для algorithmic validation без обязательной проверки prose:

- `mk-001` ... `mk-007`: company facts;
- `sales-001`: document links / filenames;
- `tech-003` ... `tech-015`: exact catalog attributes;
- `tech-016` ... `tech-019`: retrieval by deterministic constraints;
- `tech-024` ... `tech-031`: application recommendation;
- `sales-002` ... `sales-006`: portfolio-by-application.

Остаются два кейса, которые должны жить в e2e/hybrid basket:

- `tech-001-tempered-glass`
  - factual document-derived answer, но сегодня не имеет dedicated normalized artifact;
- `tech-002-r500-vs-r700`
  - сравнительный narrative answer, где формулировка и компактное summary являются частью результата.

Следовательно, immediate migration target для `algorithmic_v1` составляет 38 из 40 кейсов.

### 4. The current stack already supports a clean artifact path

На стороне core есть три естественные точки расширения:

- `ToolResult.metadata` в [core/models.py](/home/admin/totosha/core/models.py#L8);
- `run_meta` в [core/run_meta.py](/home/admin/totosha/core/run_meta.py#L14);
- agent loop после `execute_tool(...)` в [core/agent.py](/home/admin/totosha/core/agent.py#L1078).

На стороне benchmark есть две естественные точки:

- запись результатов в [bench/bench_run.py](/home/admin/totosha/bench/bench_run.py#L296);
- evaluator logic в [bench/bench_eval.py](/home/admin/totosha/bench/bench_eval.py#L110).

Это означает, что migration не требует переписывать весь agent loop или benchmark framework с нуля.

Why the current answer-first model is suboptimal
------------------------------------------------

### 1. It overpays for prose when data is already exact

Для вопроса "Какой вес у модели X?" правильность уже есть в exact attribute payload. LLM нужен только для превращения `18.3` в `"18.3 кг"`. Это ненужный cost layer для benchmark correctness.

### 2. It creates false negatives on harmless paraphrases

Если модель вернула правильные данные, но немного иначе сформулировала ответ, text checks могут упасть, хотя retrieval и data selection были корректными.

### 3. It hides the real failure boundary

Сейчас benchmark не умеет различать:

- wrong retrieval;
- right retrieval, wrong render;
- right retrieval and render, but over-browsed path;
- right retrieval, but poor candidate ranking.

Algorithmic validation по artifacts решает эту проблему.

### 4. It blocks faster benchmark modes

Пока correctness живёт только на answer-level, benchmark почти всегда вынужден идти через полный `agent -> tools -> LLM final answer` path, даже если можно было проверить только tool output и остановиться раньше.

Case classification and migration target
----------------------------------------

### Bucket A. Direct deterministic facts

Cases:

- `mk-001` ... `mk-007`
- `tech-003` ... `tech-015`

Target validation:

- direct structured field checks;
- no dependency on final answer text.

Preferred execution:

- `direct_tool` для cheap data-plane benchmark;
- optional `agent_chat` shadow subset for routing regression.

### Bucket B. Deterministic retrieval / selection

Cases:

- `tech-016` ... `tech-019`

Target validation:

- validate selected model or candidate list against structured constraints;
- do not validate only the sentence "Подходит модель X".

Preferred execution:

- `direct_tool` or `agent_chat + artifact validation`.

### Bucket C. Application recommendation

Cases:

- `tech-024` ... `tech-031`
- `sales-002` ... `sales-006`

Target validation:

- validate `resolved_application`, `categories`, `recommended_lamps`, `portfolio_examples`, `follow_up_question` directly from `application_recommendation` payload.

Preferred execution:

- `agent_chat + artifact validation` for routing coverage;
- optional `direct_tool` fast suite for raw backend correctness and latency.

### Bucket D. Document-link lookup

Cases:

- `sales-001`

Target validation:

- validate returned file identifiers / URLs from structured document payload or promoted records;
- no need to require exact prose.

### Bucket E. Keep as hybrid/e2e

Cases:

- `tech-001`
- `tech-002`

Reason:

- they depend on document-derived summarization or comparison narrative;
- `tech-002` in particular is meaningfully about concise comparative phrasing.

Verdict:

- keep these as `legacy_text` or `hybrid` in v1.

Recommended decision
--------------------

Benchmark evolves into a multi-mode system:

1. Dataset explicitly declares execution mode and validation mode per case.
2. Core records compact structured artifacts for allowlisted tools during bench/debug runs.
3. Evaluator supports:
   - `legacy_text`;
   - `routing`;
   - `algorithmic`;
   - `hybrid`;
   - `comparison`.
4. Deterministic cases migrate away from answer-text correctness and toward artifact correctness.
5. A dedicated comparison test reports:
   - legacy verdict;
   - algorithmic verdict;
   - divergence reasons;
   - latency/cost deltas by mode.

High-level behavior
-------------------

### Mode 1. `agent_chat + algorithmic`

1. Runner sends the natural-language user question to `/api/chat`.
2. Agent routes and calls tools as usual.
3. Allowlisted tool payloads are captured into `meta.bench_artifacts`.
4. Evaluator ignores final prose for correctness when case validation mode is `algorithmic`.
5. Evaluator checks artifact fields and routing fields.

This mode preserves routing coverage but removes dependence on prose.

### Mode 2. `direct_tool + algorithmic`

1. Runner executes the declared tool directly, without final LLM answer generation.
2. Result payload is written into result row as the primary artifact.
3. Evaluator validates payload algorithmically.

This mode is the cheapest and fastest benchmark for deterministic backend/data-plane correctness.

### Mode 3. `agent_chat + legacy_text`

1. Runner uses the current full chat path.
2. Evaluator checks answer text and routing.

This remains for narrative or render-sensitive cases.

### Mode 4. `comparison`

1. Same case or same run is evaluated by both validators:
   - legacy answer validator;
   - algorithmic artifact validator.
2. Report shows verdict matrix and differences.

This mode is mandatory during migration.

Artifact capture design
-----------------------

### Artifact scope

Only allowlisted tools contribute benchmark artifacts in v1:

- `corp_db_search`
- `doc_search`
- `corp_wiki_search` as alias of `doc_search`

All other tools remain outside artifact capture unless explicitly added later.

### Artifact shape

Each captured artifact uses a compact normalized schema:

```json
{
  "tool": "corp_db_search",
  "success": true,
  "kind": "application_recommendation",
  "captured_from": "tool_result_metadata",
  "payload": { "... compact JSON payload ..." }
}
```

For `doc_search`, `kind` is omitted or set to `doc_search`.

### Where artifacts are stored

During the request:

- artifacts accumulate in `run_meta["bench_artifacts"]`.

In results JSONL:

- runner writes `meta.bench_artifacts` as-is;
- optionally also copies `primary_artifact` to the top-level result row for convenience.

### How artifacts are produced

Preferred implementation path:

1. Tool wrapper returns `ToolResult.metadata["bench_artifact"]` for allowlisted tools.
2. Agent loop appends that artifact into `run_meta`.
3. API returns it only when `return_meta=true`.

Why this path is preferred:

- no need to scrape formatted text back into JSON;
- avoids reparsing pretty-printed output;
- works even if user-facing output formatting changes;
- keeps artifact capture explicit and auditable.

### Bounded size requirements

Artifacts must be bounded:

- maximum 8 captured artifacts per request;
- maximum 128 KiB total serialized artifact payload;
- long previews truncated;
- only compact payloads stored, not full raw corpora or giant document text.

This is necessary to keep bench results small and safe.

Dataset schema changes
----------------------

The dataset format grows from `question + golden.checks + routing` into a richer contract.

### Proposed top-level additions

```json
{
  "execution": {
    "mode": "agent_chat"
  },
  "validation": {
    "mode": "algorithmic"
  }
}
```

### Execution modes

- `agent_chat`
  - current behavior via `/api/chat`
- `direct_tool`
  - direct tool invocation with declared tool name and args
- `agent_chat_shadow`
  - same as `agent_chat`, but also evaluated in legacy shadow mode

### Validation modes

- `legacy_text`
  - current `answer` checks
- `algorithmic`
  - checks against structured artifacts
- `hybrid`
  - both structured and text checks
- `routing_only`
  - for pure routing regression probes

### Structured check schema

Minimal v1 check types:

- `equals`
- `one_of`
- `exists`
- `len_gte`
- `contains_any`
- `all_prefix`
- `number_eq`
- `number_range`

Minimal path syntax:

- dotted fields: `resolved_application.application_key`
- array field itself: `recommended_lamps`
- wildcard projection: `recommended_lamps[*].url`

This should be implemented as a small internal path resolver, not as a full JSONPath dependency.

### Example: application recommendation case

```json
{
  "id": "tech-027-application-stadium-projectors",
  "execution": { "mode": "agent_chat" },
  "validation": {
    "mode": "algorithmic",
    "artifact_selector": {
      "tool": "corp_db_search",
      "kind": "application_recommendation"
    },
    "checks": [
      { "type": "equals", "path": "status", "value": "success" },
      { "type": "equals", "path": "resolved_application.application_key", "value": "sports_high_power" },
      { "type": "len_gte", "path": "recommended_lamps", "value": 2 },
      { "type": "all_prefix", "path": "recommended_lamps[*].url", "value": "https://ladzavod.ru/catalog/" },
      { "type": "len_gte", "path": "portfolio_examples", "value": 1 },
      { "type": "contains_any", "path": "follow_up_question", "value": ["высот", "прожектор"] }
    ]
  }
}
```

### Example: exact attribute case

```json
{
  "id": "tech-003-weight-r500-9-30-6-650lzd",
  "execution": {
    "mode": "direct_tool",
    "tool": "corp_db_search",
    "args": {
      "kind": "lamp_exact",
      "name": "LAD LED R500-9-30-6-650LZD"
    }
  },
  "validation": {
    "mode": "algorithmic",
    "checks": [
      { "type": "number_eq", "path": "results[0].weight_kg", "value": 18.3, "tolerance": 0.2 }
    ]
  }
}
```

Evaluation model
----------------

### Legacy evaluator remains intact

`eval_checks(answer, checks)` stays available for:

- `legacy_text`
- `hybrid`
- migration shadow runs

### New algorithmic evaluator

New evaluator reads:

- `validation.mode`
- `validation.artifact_selector`
- `validation.checks`
- `meta.bench_artifacts`

and computes verdict strictly from structured payload.

### Hybrid evaluator

For selected cases:

- structured checks must pass;
- text checks may also be required.

This is useful for `tech-001` and `tech-002`, or any case where both correctness and compact phrasing matter.

Comparison test design
----------------------

Migration must include a first-class comparison test. Without it, there is no safe way to detect whether algorithmic validation became too lax or too strict.

### Comparison test objectives

Comparison test answers three questions:

1. Where do legacy and algorithmic validators disagree?
2. Are disagreements caused by text-level fragility or by missing/incorrect artifacts?
3. How much latency/cost is saved when deterministic cases run without final LLM answer generation?

### Comparison inputs

Comparison consumes either:

- one `agent_chat` run containing both `answer` and `bench_artifacts`; or
- two runs:
  - `legacy_e2e` run;
  - `algorithmic` run or `direct_tool` run.

### Comparison outputs

Per case:

- `legacy_pass`
- `algorithmic_pass`
- `routing_pass`
- `comparison_status`

Allowed `comparison_status` values:

- `same_pass`
- `same_fail`
- `legacy_only_pass`
- `algorithmic_only_pass`
- `missing_artifact`
- `not_comparable`

Aggregate report:

- counts by comparison status;
- divergence list with reasons;
- latency avg/p50/p95 by mode;
- tokens total by mode;
- estimated cost by mode.

### Required comparison assertions

During migration, the comparison suite must fail if:

- algorithmic validator passes a case that lacks the required artifact;
- direct deterministic mode silently falls back to LLM;
- divergence rate exceeds the allowed threshold for migrated buckets.

### Recommended command surface

One of two acceptable implementations:

Option A:

- extend `bench_eval.py` with `--algorithmic`, `--legacy`, `--compare`

Option B:

- keep `bench_eval.py` simple and add `bench_compare.py`

Preferred choice:

- `bench_compare.py`, because it keeps current evaluator simple and makes comparison mode explicit.

Execution strategy by bucket
----------------------------

### Company facts and exact catalog facts

Preferred mode:

- `direct_tool`

Reason:

- no routing ambiguity is being tested;
- zero need for final LLM render;
- benchmark becomes much cheaper and more stable.

### Retrieval by structured constraints

Preferred mode:

- `direct_tool` for backend correctness;
- small shadow subset via `agent_chat` for routing/regression sanity.

Reason:

- correctness is candidate selection, not prose.

### Application recommendation

Preferred mode:

- keep primary suite in `agent_chat + algorithmic`, because this bucket still needs routing coverage from user wording to `application_recommendation`;
- optionally add `direct_tool` smoke suite for raw backend latency.

Reason:

- here the interesting behavior starts from natural language intent resolution.

### Document link lookup

Preferred mode:

- `agent_chat + algorithmic` initially;
- later `direct_tool` if direct document search execution proves stable and representative.

### Narrative comparison

Preferred mode:

- `legacy_text` or `hybrid`

Reason:

- this bucket is small and intentionally tests answer rendering.

Data contract examples for current benchmark
--------------------------------------------

### Current `application_recommendation` payload

The existing backend already returns a compact structure:

- `status`
- `kind`
- `query`
- `filters`
- `resolved_application`
- `categories`
- `recommended_lamps`
- `portfolio_examples`
- `follow_up_question`

in [tools-api/src/routes/corp_db.py](/home/admin/totosha/tools-api/src/routes/corp_db.py#L954).

This is already sufficient for algorithmic validation of:

- resolved application key;
- ambiguity status;
- recommendation count;
- presence of catalog URLs;
- presence of portfolio URLs;
- presence of follow-up question.

### Current `doc_search` payload

`doc_search` already returns structured JSON with:

- `status`
- `results`
- top match metadata

in [core/tools/doc_search.py](/home/admin/totosha/core/tools/doc_search.py#L120).

This is enough to start algorithmic validation for document-link and promoted-document cases, even if full document-fact normalization is deferred.

Migration plan
--------------

### Phase 0. Shadow design and artifacts

- add `bench_artifacts` support to `run_meta`;
- capture allowlisted tool artifacts via `ToolResult.metadata`;
- return artifacts in `/api/chat` when `return_meta=true`;
- do not change verdict logic yet.

### Phase 1. New evaluator and dataset schema

- add `execution` and `validation` schema blocks;
- implement `eval_algorithmic`;
- keep `eval_checks` and `eval_routing` unchanged;
- add dataset migration for deterministic cases in shadow mode.

### Phase 2. Comparison suite

- add `bench_compare.py` or equivalent comparison mode;
- report divergence between legacy and algorithmic verdicts;
- add latency/token/cost comparison across modes.

### Phase 3. Direct deterministic runner

- extend runner to support `execution.mode=direct_tool`;
- migrate exact fact and deterministic retrieval buckets to direct mode;
- keep selected routing-sensitive cases as `agent_chat`.

### Phase 4. Reduce legacy surface

- keep only a small narrative/e2e basket in legacy mode;
- make algorithmic validation the default for deterministic benchmark cases.

Testing approach
----------------

### Unit tests

- path resolver tests for structured checks;
- evaluator tests for each check type;
- artifact selector tests;
- comparison matrix tests;
- result-row schema tests.

### Integration tests

- `/api/chat` returns `meta.bench_artifacts` when `return_meta=true`;
- `corp_db_search` artifacts are captured after successful tool execution;
- `doc_search` artifacts are captured and truncated correctly;
- `direct_tool` execution writes valid result rows.

### Comparison tests

Mandatory comparison fixtures:

- same case passes under both validators;
- correct artifact but paraphrased prose:
  - legacy may fail;
  - algorithmic must pass;
- missing artifact:
  - algorithmic must fail explicitly;
- wrong artifact but plausible prose:
  - legacy may pass;
  - algorithmic must fail.

### Manual smoke

- run small mixed dataset in `legacy`, `algorithmic`, and `comparison` modes;
- verify report readability and divergence reasons;
- verify deterministic direct suite produces `tokens_total == 0` or no `llm_usage` for direct-mode rows.

Acceptance criteria
-------------------

- `bench_run.py` supports per-case `execution.mode`.
- Bench results can carry compact structured artifacts without unbounded payload growth.
- `bench_eval.py` or companion evaluator supports `algorithmic` validation.
- Comparison mode/report exists and shows verdict divergence between legacy and algorithmic checks.
- At least 38 of the current 40 benchmark cases are migrated to `algorithmic` or `direct_tool` validation.
- `tech-001` and `tech-002` remain explicitly marked as `hybrid` or `legacy_text`, not silently forced into algorithmic mode.
- Deterministic direct suite can run without mandatory final LLM response generation.
- Comparison report includes latency and token/cost deltas between old and new benchmark modes.

Risks and mitigations
---------------------

### Risk 1. Artifacts become too large or leak too much internal context

Mitigation:

- allowlist tools;
- compact payloads only;
- hard caps on artifact count and size;
- truncate previews.

### Risk 2. Algorithmic checks become too permissive

Mitigation:

- shadow comparison is mandatory;
- mismatches are reported explicitly;
- hybrid mode remains for ambiguous/narrative cases.

### Risk 3. Direct-tool suite stops covering routing regressions

Mitigation:

- keep a routing-sensitive subset in `agent_chat + algorithmic`;
- do not move application-intent primary coverage fully to direct mode.

### Risk 4. Dataset migration becomes messy

Mitigation:

- incremental migration by bucket;
- keep backward compatibility for legacy rows;
- add case-level explicit modes instead of global switching.

Alternatives considered
-----------------------

### Option A. Keep answer-text validation and only add more regexes

Плюсы:

- минимум работ.

Минусы:

- не решает проблему cost/latency;
- не различает data correctness и render correctness;
- хрупко к harmless paraphrase.

Verdict:

- отклонено.

### Option B. Fully replace benchmark with direct backend tests

Плюсы:

- очень быстро и дёшево.

Минусы:

- теряется routing coverage;
- не видно agent-level regressions;
- не покрывает narrative/e2e behavior.

Verdict:

- отклонено как единственный режим, но принимается как часть multi-mode strategy.

### Option C. Multi-mode benchmark with artifact-first validation and comparison suite

Плюсы:

- сохраняет routing coverage там, где она важна;
- резко удешевляет deterministic subset;
- делает verdict точнее и объяснимее;
- позволяет безопасную миграцию через comparison test.

Минусы:

- требует dataset schema expansion и artifact plumbing.

Verdict:

- принято.

Implementation outline
----------------------

1. Добавить `run_meta_append_artifact(...)` и bounded storage в `core/run_meta.py`.
2. На allowlisted tools начать возвращать compact `bench_artifact` через `ToolResult.metadata`.
3. В agent loop добавлять bench artifacts в run meta после успешного tool execution.
4. Расширить `/api/chat` meta contract, не ломая текущих потребителей.
5. Расширить dataset schema полями `execution` и `validation`.
6. Реализовать structured path resolver и `eval_algorithmic`.
7. Добавить comparison runner/report.
8. Мигрировать deterministic buckets.
9. Оставить hybrid/e2e basket для narrative cases.

Open questions
--------------

- Нужен ли единый `primary_artifact`, или достаточно `bench_artifacts[]` + selector?
- Стоит ли direct-tool mode ходить через core tool wrapper или напрямую в `tools-api`?
- Нужно ли в v1 нормализовать `doc_search` до document-fact artifacts, или достаточно promoted/document-link payloads?
- Хотим ли мы отдельный `bench/golden/v2.jsonl`, или backward-compatible migration внутри `v1.jsonl`?

Recommended next step
---------------------

Следующим шагом нужно делать не полную миграцию датасета, а инфраструктурный минимум:

- artifact capture в `core`;
- algorithmic evaluator;
- comparison report.

Только после этого имеет смысл массово переводить кейсы из `v1.jsonl` в новый validation mode.
