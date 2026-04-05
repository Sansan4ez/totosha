Doc Worker Runbook
==================

Purpose
-------

`doc-worker` owns document intake and normalization. The chat path in `core` reads only
manifests and normalized sidecars from `/data/corp_docs`.

Main commands
-------------

```bash
docker compose run --rm --profile operator doc-worker doctor --strict
docker compose run --rm --profile operator doc-worker sync-repo
docker compose run --rm --profile operator doc-worker rebuild-parsed --force
docker compose run --rm --profile operator doc-worker rebuild-routes
```

Repo workflow
-------------

1. Copy documents into `doc-corpus/inbox/`.
2. Optionally add `<filename>.meta.json` рядом с файлом.
3. Run `doc-worker sync-repo`.
4. Check the JSON report and `doc-worker doctor`.

Doctor interpretation
---------------------

- `binaries`: runtime dependencies expected inside `doc-worker`
- `corpus.live_documents`: live manifest count
- `corpus.parsed_current`: documents with a current parsed sidecar
- `corpus.missing_current`: documents that require `rebuild-parsed`
- `corpus.route_index_present`: whether `rebuild-routes` has published an index

Failure modes
-------------

- `legacy_office_binary_requires_doc_worker_runtime`: legacy `doc/xls/ppt` was ingested outside the guaranteed `doc-worker` runtime
- `normalization_missing`: `core` saw a live document without a current sidecar; rebuild with `doc-worker rebuild-parsed`
- `invalid_metadata_json` / `invalid_metadata_type`: fix the repo sidecar under `doc-corpus/inbox/`
