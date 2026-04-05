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

Example
-------

```bash
docker compose run --rm --profile operator doc-worker doctor --strict
docker compose run --rm --profile operator doc-worker sync-repo
```
