# R700 search incident regression and rollout

Status: regression contract and rollout procedure recorded; production acceptance is **not
claimed** by this change. The running `core` and `tools-api` containers were built from images
whose IDs do not identify the current source revision, and the checked-in route tests currently
have two R700-series routing failures (details below). Do not use those containers as evidence
that the current source is deployed, and do not promote a production release until the gates in
this document pass.

## Incident baseline

The fixed historical evidence window is 2026-10-02T21:00:00Z through 2026-10-03T21:00:00Z
(2026-10-03 Moscow time): 52,827 VictoriaLogs records, seven chat traces, VictoriaMetrics,
and read-only SQL. Four of five relevant requests in the 20:59–21:02 Moscow-time chain ended
negatively despite HTTP 200 responses. The traces were:

| Intent | Trace |
|---|---|
| list five R700 models | `251fab7cd2ff2030a465591e6afff0a3` |
| describe R700 series | `2fb4d105a143b53c30bbcb61b5a39798` |
| R700 PROM models | `e3ef36e33c36eda77a887bf01a3b0a72` |
| projects/examples for PROM | `1fbf3e5f6ccb3c52a35ac09775799730` |
| contextual portfolio follow-up, “тогда с LAD LED R700” | `027c5c521863917005a155471a8d0a24` |

At investigation time, read-only SQL showed 709 lamps, 108 R700 names, 24 R700+PROM names,
zero exact rows named `R700`, `LAD LED R700`, or `LAD LED R700 PROM`, and 228 projects. The
140 projects reachable through category→sphere are category/sphere examples only, **not proof of
direct R700 model application**. These are incident observations, not fixed test constants.

## Regression contract

Replay the sequence in an isolated web session, preserving conversation context between turns:

1. `пока штук 5 светильнbков из серии r700` → list models (`corp_db.series_models`), canonical
   series `LAD LED R700`, `limit=5`.
2. `серия r700` → series knowledge (`corp_kb.series_description`), with evidence scoped to R700.
3. `светильники LAD LED R700 PROM` → `series_models`, canonical R700 plus PROM subfamily; all
   returned rows must be PROM and carry series evidence.
4. `объекты с LAD LED R700 PROM` → portfolio examples; results must identify provenance as
   `category_sphere_example` unless a real direct application relation is present.
5. `тогда с LAD LED R700` → retain portfolio intent, replace the entity/subfamily as requested,
   and do not repeat the prior business-empty search.

For every turn record selector choice, validated arguments/schema, executor result rows/status,
provenance/evidence, final answer, HTTP status, request ID, attempts, and end-to-end latency.
HTTP 200 or a keyword in the answer is never sufficient by itself. Catalog results must contain
at least the requested number of real matching rows where the fixture/data has them. Empty,
unknown-series, and unresolved-exact-model outcomes must be reported distinctly and honestly.

Deterministic regression data must include real-form SKUs, canonical series mappings, PROM/ST/HT,
R7000, unknown/empty series, exact SKU, and code lookup. Assert exclusions as well as inclusions:
PROM-only cannot include ST/HT; R700 cannot match R7000; exact model and code lookup must retain
their specialized paths. Keep production counts out of assertions.

## Local/CI verification

Run focused suites from a clean checkout in CI (the host Python environment may not have the
service dependencies installed):

```bash
# Core, in the built test image / CI environment
cd core && python -m unittest -q tests.test_routing_catalog tests.test_corp_db_tool

# Tools API, in its dependency environment
cd tools-api && python -m unittest discover -s tests -p 'test_corp_db.py' -q

# Existing bench contracts
python3 -m unittest -q \
  bench.tests.test_algorithmic_eval \
  bench.tests.test_routing_eval \
  bench.tests.test_run_modes
```

Source-aligned verification on 2026-10-04 (feature branch, before deployment):
`python3 -m unittest -q tests.test_routing_catalog tests.test_corp_db_tool` in `core/`
passed 69 tests after correcting the comparison-vs-model selector boundary in
`core/documents/routing.py`. `docker run --rm -v "$PWD/tools-api:/app" -w /app
--entrypoint python totosha-tools-api -m unittest discover -s tests -p test_corp_db.py -q`
passed 64 tests after restoring `category_id` in the empty portfolio response and fixing the
PROM-only fake connection. This uses the current mounted source with image dependencies, NOT the
running production container. Bench contract unit tests passed (24 tests). These results do not
establish CI, repeated-run LLM quality, source-aligned production deployment, or a five-turn
production smoke.

For LLM routing stability, use the existing RFC-030/repeated-run evaluation harness and freeze
provider/model, prompt/config revision, dataset version, temperature/sampling parameters, and
container build SHA. Run the held-out chain and negative cases repeatedly (minimum 10 runs per
case); report selection accuracy, argument validity/constraint preservation, evidence quality,
answer factuality, business-empty/attempts, p50/p95 latency, and failure rate separately. Gate on
zero PROM/ST/HT/R7000 or provenance violations and zero unsupported direct-application claims;
require all deterministic expected routes/arguments on every run. Attach machine-readable raw
results and a summary. Do not claim a repeated-run pass without the pinned configuration and
artifacts.

## Safe production rollout, smoke, and rollback

1. **Preflight:** run the CI gates above and repeated-run report; review diffs; freeze deployment
   SHA, image IDs, schema/data snapshot marker, and known-good image IDs. If any hard gate fails,
   stop before production.
2. **Deploy:** use the repository's normal guarded rollout, rebuilding the affected services from
   the reviewed SHA (at minimum `core`, `tools-api`, and any changed DB/migrator image). Record
   `docker compose ps`, health endpoints, image IDs, build SHA, and timestamps. Do not apply a DB
   migration unless the release explicitly includes and reviews one.
3. **Isolated smoke:** use a dedicated authorized test account and new isolated web session; do
   not reuse customer history. Send the five turns above sequentially and attach a fresh unique
   `request_id` to each HTTP request. Capture request/response metadata with secrets and personal
   data redacted. Assert selected route, schema-valid args, returned rows and evidence, truthful
   final answer, no repeated identical business-empty, closed trace/reason, and no direct-use claim
   from category/sphere-only evidence.
4. **Correlate:** for each request ID, verify API logs and traces, business status/reason, route and
   fallback attempts, evidence/provenance, and per-phase latency. Check dashboards/counters before
   and after the smoke; distinguish business-empty from transport success. Save the baseline/fixed
   comparison with image/config/data revision, attempts, business-empty count, evidence grade,
   and latency. Do not place request IDs, query text, user IDs, or trace IDs in metric labels.
5. **Promote only** after every assertion succeeds and evidence is reviewed. Preserve the smoke
   report and linked trace/log references in the release record.
6. **Rollback:** if any hard assertion, health check, or error/latency guardrail fails, stop
   promotion and restore the previously recorded known-good images/config using the normal compose
   rollback procedure; revert only the implicated migration if its reviewed rollback is safe.
   Recheck health and run a known-good catalog + portfolio smoke. Keep failed release artifacts
   for diagnosis; do not repeat the test against user sessions.

No production request was sent as part of this report: the locally running service images are not
source-aligned, and the checked-in selector test failure means the preconditions for safe rollout
are unmet. Production trace evidence, fixed-vs-baseline latency, and the RFC-030 repeated-run
artifact remain release/acceptance blockers rather than fabricated results.


## Production rollout 2026-10-05 (manual API acceptance)

По явному поручению пользователя развернуты только `core` и `tools-api` из
`fix/r700-search-incident`; `main` не менялся. Исходные образы сохранены как
`totosha-core:r700-rollback-20261005` и `totosha-tools-api:r700-rollback-20261005`.
Первый smoke SHA `809eb83` обнаружил неверный маршрут объектов PROM, недоказанные
утверждения о применении и потерю количества моделей. Выполнен откат обоих сервисов.

Исправления `907864d`, `24eb147`: разграничение описания/списка/объектов в selector,
bounded rendering всех возвращенных series rows и кодов, обязательная оговорка
для `category_sphere_example`, остановка поиска при unknown/ambiguous series.
Первопричина потери строк: five-row JSON занимает 43441 символ при бюджете finalizer
24000; прямой API возвращал пять строк, а LLM получал обрезанный JSON.

Финально работающие образы собраны с `BUILD_GIT_SHA=24eb147b37f68a95944ff8d22339b14257a974b2`,
`BUILD_TIME=2026-10-04T23:35:17Z`; `/health` подтверждает SHA и валидный routing catalog.
Оба сервиса healthy. Финальная проверка началась после готовности core: прежняя
попытка сразу после recreate получила connection failures и не считается acceptance.

Первые пять запросов выполнены последовательно в новой отдельной web-сессии;
остальные — в отдельных сессиях. `execution_mode=runtime`, `return_meta=true`.
Модель фактического production ответа — `gpt-5.6-terra`, не модель worker.

| Request ID suffix (`r700-prod-final-20261005-`) | Проверка | Результат | Latency, s | Trace ID |
|---|---|---|---:|---|
| 01 | 5 R700 моделей | 5 реальных строк | 5.28 | f9fe8d8f82b4a050ae1117b8b3dac97a |
| 02 | Описание серии | Описание, не lamp_not_found | 8.51 | 599e5d8d5c8d1acd74182f5eb9ced523 |
| 03 | PROM-only модели | 5 PROM строк | 7.57 | 9b63c0c225f7c7671da291ab90f714aa |
| 04 | Объекты PROM | 5 проектов с косвенной provenance | 10.28 | 7065aee0ae7bc18d265e99acf83e404a |
| 05 | Контекст: тогда R700 | Portfolio task сохранён, scope R700 | 7.19 | b583c4549938f1c2f3fe32fee03fc031 |
| 06 | R500/R700 сравнение | Описание обеих серий | 8.7 | 68f6f472ac774a1c05f1818229d323df |
| 07 | R7000 | Неизвестная серия, без подмены | 4.2 | d3c98e50e181b6a5119abd1cc919d504 |
| 08 | Unknown series | Неизвестная серия, без подмены | 4.13 | ea233e7c195a1d60ecb38d5bb6d4faca |
| 09 | Exact SKU | Карточка точной модели | 10.86 | 0f8bf0a53a3552f4bf997b075fb16c16 |
| 10 | Коды заказа | ETM/ORACL/article/SKU присутствуют | 6.55 | e24d8c54d0b77ebd03b2f072e52790af |

Во всех 10 ответах `tool_errors=0`; вывод и meta проверены, HTTP success сам по себе
не использовался как критерий. Конфликт exact R700 SKU + series R500 через прямой
tools-api отклонён: `empty`, `reason=selector_conflict`, без результатов.
Оговорки объектов явно запрещают считать их доказанным применением серии/модели.

Локальные тесты запускались отдельными процессами: routing catalog 46, corp_db tool 23,
selector fake 25 (включая новую bounded-output регрессию), routing guardrail 75
(3 skipped), tools-api 68. Общий запуск сначала выявил stale observability stub;
он исправлен. Bench discovery ранее прошёл 31 тест. Это не live repeated-run CI gate.

Raw API/meta и docker logs сохранены локально в `.git/r700-production/`
(`chat-final-summary.jsonl`, `chat-01.json`–`chat-10.json`, `core-final.log`,
`tools-final.log`, `conflict-api.json`). Не добавлены в git из-за account/session data.
Trace IDs выше позволяют найти запросы в telemetry. Отдельная агрегация метрик и
длительный soak не проводились; acceptance ограничен перечисленными сценариями.
Отменённый специализированный gate `.11` не восстановлен.

Откат: `docker tag totosha-core:r700-rollback-20261005 totosha-core:latest`,
аналогично tools-api, затем `docker compose up -d --no-deps core tools-api`.
Текущий prod оставлен на проверенных исправленных образах, rollback tags сохранены.


## Merge to main and production redeploy — 2026-10-06 MSK

По поручению пользователя ветка влита в `main` merge-коммитом
`3ad8c4e60162de5b4ad7cfb55147ca9a99c36bc3` и отправлена в `origin/main`.
Из этого SHA пересобраны и пересозданы только `core`, `tools-api`, `agent-web`.
`/health` core подтверждает SHA, selector enabled и routing catalog ok;
все три контейнера healthy, web health возвращает ok. БД и остальные сервисы
не перезапускались. Проверки ссылок и мыши ранее подтверждены пользователем.

Сохранены непосредственно предшествующие образы для отката:
`totosha-core:pre-main-20261005`, `totosha-tools-api:pre-main-20261005`,
`totosha-agent-web:pre-main-20261005`. Чтобы откатить сервис, перетегировать
его rollback image в `totosha-<service>:latest` и выполнить
`docker compose up -d --no-deps core tools-api agent-web`.

После health readiness повторены 10 API-сценариев в новой сессии
(первые пять — одна последовательная цепочка). Все ответы без tool errors.
Assertions: ровно пять R700 строк, пять PROM-only строк, portfolio route на
обоих запросах объектов и обязательное предупреждение о косвенной связи,
unknown series без подмены, ETM/ORACL коды присутствуют. Дополнительно вручную
проверены описание, сравнение R500/R700 и точный SKU. Latency 4.75–19.51 s.

| Request ID | Trace ID | Latency, s |
|---|---|---:|
| r700-main-20261005-01 | b5c41031a53691e86f5a439e8d718e8a | 7.03 |
| r700-main-20261005-02 | 8b9f636356e87100b3201638378f3da4 | 19.51 |
| r700-main-20261005-03 | d81ddafdcd14628089f626e5de80eb5a | 6.66 |
| r700-main-20261005-04 | 431586b444280fb2da5110026f2701ac | 9.47 |
| r700-main-20261005-05 | f996ef671dacecbfee30fdbc3228ab7d | 12.33 |
| r700-main-20261005-06 | 84dfa87ec9d5566dd7333c2648a69392 | 12.1 |
| r700-main-20261005-07 | b787781657a206fa6f5af1deb5eebb28 | 6.86 |
| r700-main-20261005-08 | 1b2f9f54e3030cbc4de5a2aea973cef6 | 4.75 |
| r700-main-20261005-09 | cb5793d7e623bad1c99b16cc1e0d7a7a | 15.68 |
| r700-main-20261005-10 | 89544169a963b7ea85e96900a5b70b5a | 6.28 |

Локальные raw artifacts/logs/build/health: `.git/r700-main-rollout/`; не публикуются
из-за session/account data. Документационный коммит после merge не меняет runtime code;
работающие образы намеренно маркированы SHA merge-коммита.
