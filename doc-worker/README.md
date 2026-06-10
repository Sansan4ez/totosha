doc-worker
==========

Operator-side document worker for RFC-010.

Purpose
-------

`doc-worker` owns the write path for the document corpus:

- repo inbox synchronization
- document intake into `/data/corp_docs`
- normalization / parsed sidecars rebuild
- routing index rebuild
- environment diagnostics

It is intentionally separate from `core` so heavy parsing dependencies such as
LiteParse, LibreOffice, and ImageMagick do not become chat-path requirements.

Current commands
----------------

- `doctor`
- `ingest`
- `sync-repo`
- `rebuild-parsed`
- `rebuild-routes`
- `verify-domain`

Example
-------

```bash
docker compose --profile operator run --rm doc-worker doctor --strict
docker compose --profile operator run --rm doc-worker sync-repo
docker compose --profile operator run --rm doc-worker verify-domain --strict \
  --expected-route-id doc_search.sports_lighting_norms \
  --expected-route-family doc_search.sports_lighting_norms \
  --expected-relative-path part_440.1325800.2023.doc
```
