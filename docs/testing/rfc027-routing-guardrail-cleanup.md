# RFC-027 routing guardrail cleanup

Пост-RFC-027 cleanup для `core.tests.test_routing_guardrail`.

## Итог

Suite `core.tests.test_routing_guardrail` снова зелёный:

```bash
python3 -m unittest -q core.tests.test_routing_guardrail
```

Сейчас:
- `54 tests OK`
- `3 skipped`

## Что было классифицировано как obsolete expectations

Эти ожидания относились к pre-RFC-027 / pre-selector-primary поведению и были обновлены:

- ожидание старого prompt-блока `Routing shortlist:`;
- ожидание deterministic final-answer fallback при пустом finalizer LLM ответе;
- ожидание deterministic primary finalization в `benchmark` режиме;
- ожидание, что после route-selector-primary success агент ещё пойдёт в `doc_search` / browse-tool и словит guardrail;
- ожидание close reason `doc_search_payload_sufficient` там, где теперь закрытие идёт через `route_selector_payload_sufficient`;
- ожидание mixed-source follow-up (doc-first company fact / corp-db-first document topic), которое противоречит family-first selector contract.

## Что было исправлено как test/fixture drift

Следующие проблемы были не архитектурными регрессиями, а дрейфом тестового harness-а относительно RFC-027:

- helper для selector response не учитывал `locked_args` при выборе route;
- helper подставлял selector-visible args не из compact selector route card;
- helper неверно планировал primary route из старого main-loop tool order вместо актуального selector-primary execution;
- doc-search route matching не учитывал `preferred_document_ids` из `locked_args`;
- несколько payload fixtures для `application_recommendation` не содержали `results`, из-за чего payload классифицировался как weak.

## Ambiguous / intentionally skipped

Следующие сценарии оставлены как `skip`, потому что они требуют отдельного product decision и не входят в текущий RFC-027 route-tree contract:

- explicit wiki-first company-fact browsing;
- mixed-source doc-first company-fact routing;
- unrestricted generic `doc_search` fallback after weak company-fact payload.

## Regression command set

```bash
python3 -m unittest -q \
  core.tests.test_rfc027_llm_only \
  core.tests.test_rfc027_observability \
  core.tests.test_route_schema \
  core.tests.test_routing_catalog \
  core.tests.test_api_correlation \
  core.tests.test_routing_guardrail
```
