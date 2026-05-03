# RFC-027 regression suite

Проверка текущего RFC-027 контракта:

- family-first selector payload;
- selector-visible vs execution schema split;
- LLM-only selector/finalizer semantics (`no LLM, no answer`);
- routed final answers stay `finalizer_mode=llm`;
- observability fields for family/leaf/stage/validation/fallback.

## One-shot command

```bash
python3 -m unittest -q \
  core.tests.test_rfc027_llm_only \
  core.tests.test_rfc027_observability \
  core.tests.test_route_schema \
  core.tests.test_routing_catalog \
  core.tests.test_api_correlation
```

## Scenario map

| Scenario | Coverage |
|---|---|
| selector outage / disabled | `test_rfc027_llm_only.py` |
| finalizer outage | `test_rfc027_llm_only.py` |
| company fact finalization | `test_rfc027_llm_only.py` |
| application finalization | `test_rfc027_llm_only.py` |
| document family + family-local fallback + LLM finalization | `test_rfc027_llm_only.py` |
| portfolio finalization | `test_rfc027_llm_only.py` |
| schema narrowing / merge order / fallback validation | `test_route_schema.py` |
| family-first payload / leaf-family routing matrix | `test_routing_catalog.py` |
| observability route identity fields | `test_rfc027_observability.py` |
| API correlation import compatibility | `test_api_correlation.py` |
