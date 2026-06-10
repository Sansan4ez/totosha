Doc Worker Runbook
==================

Purpose
-------

`doc-worker` owns document intake and normalization. The chat path in `core` reads only
manifests and normalized sidecars from `/data/corp_docs`.

`doc_search` is the canonical chat-time route for `doc_domain` retrieval. Explicit
document-domain questions should route directly to `doc_search`; `doc-worker` only
publishes the searchable substrate and route manifests used by that route.

Main commands
-------------

```bash
docker compose --profile operator run --rm doc-worker doctor --strict
docker compose --profile operator run --rm doc-worker sync-repo
docker compose --profile operator run --rm doc-worker rebuild-parsed --force
docker compose --profile operator run --rm doc-worker rebuild-routes
docker compose --profile operator run --rm doc-worker verify-domain --strict \
  --expected-route-id doc_search.sports_lighting_norms \
  --expected-route-family doc_search.sports_lighting_norms \
  --expected-relative-path part_440.1325800.2023.doc
```

Repo workflow
-------------

1. Copy documents into `doc-corpus/inbox/`.
2. Optionally add `<filename>.meta.json` рядом с файлом.
3. Run `doc-worker sync-repo`.
4. Check the JSON report and `doc-worker doctor`.

Representative document-domain verification
-------------------------------------------

For RFC-019 and the current sports-lighting inbox document:

1. Add `doc-corpus/inbox/part_440.1325800.2023.doc.meta.json`.
2. Run `doc-worker sync-repo`.
3. Run `doc-worker rebuild-parsed --force`.
4. Run `doc-worker rebuild-routes`.
5. Run `doc-worker verify-domain --strict --expected-route-id doc_search.sports_lighting_norms --expected-route-family doc_search.sports_lighting_norms --expected-relative-path part_440.1325800.2023.doc`.

The verification output must show `selected_route_kind=doc_domain`, the expected
route id/family, and the published `part_440.1325800.2023.doc` as the top hit for
the representative sports-lighting queries.

Migration from legacy corp-wiki
-------------------------------

The old `/data/skills/corp-wiki-md-search/wiki/` path is no longer read by
`doc_search`. For existing deployments:

1. Copy legacy markdown files into `doc-corpus/inbox/` in this repository.
2. Commit and deploy the repo update.
3. Run `doc-worker sync-repo`.
4. Run `doc-worker rebuild-routes`.
5. Verify with `doc-worker doctor` that `route_index_present=true`.

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
- `empty` on a document query after migration: verify the file was copied into `doc-corpus/inbox/` and that `sync-repo` published a live manifest
