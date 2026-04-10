Document Corpus
===============

Repo-managed source of truth for operator-provided documents used by `doc-worker`.

Layout
------

- `inbox/` contains raw files that should be ingested into `/data/corp_docs`
- `manifests/` is reserved for repo-side conventions and future operator metadata

Canonical workflow
------------------

`doc-corpus/inbox/` is the only repo-managed source for searchable documents.
`doc_search` does not read from legacy skill folders or ad-hoc wiki paths.
Published route manifests from this corpus feed the unified routing catalog as
`route_kind=doc_domain`, so explicit document-domain requests should prefer
`doc_search` directly rather than waiting for a prior KB miss.

Optional sidecar metadata
-------------------------

For a file `inbox/certificates/fire.pdf`, an optional sidecar may be provided as:

`inbox/certificates/fire.pdf.meta.json`

The sidecar must contain a JSON object. Its keys are merged into the alias/source
metadata stored in the runtime manifest.

Operator workflow
-----------------

```bash
docker compose --profile operator run --rm doc-worker sync-repo
```

The repo remains read-only for `doc-worker`; runtime artifacts and reports are
published under `/data/corp_docs`.

Migration from legacy corp-wiki
-------------------------------

If an existing deployment still keeps Markdown files under the old
`/data/skills/corp-wiki-md-search/wiki/` location, copy them into this repo
folder under `doc-corpus/inbox/` and re-run:

```bash
docker compose --profile operator run --rm doc-worker sync-repo
docker compose --profile operator run --rm doc-worker rebuild-routes
```

After that, only `/data/corp_docs/live/` and `/data/corp_docs/parsed/` are used
by `doc_search` on the chat path.
