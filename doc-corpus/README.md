Document Corpus
===============

Repo-managed source of truth for operator-provided documents used by `doc-worker`.

Layout
------

- `inbox/` contains raw files that should be ingested into `/data/corp_docs`
- `manifests/` is reserved for repo-side conventions and future operator metadata

Optional sidecar metadata
-------------------------

For a file `inbox/certificates/fire.pdf`, an optional sidecar may be provided as:

`inbox/certificates/fire.pdf.meta.json`

The sidecar must contain a JSON object. Its keys are merged into the alias/source
metadata stored in the runtime manifest.

Operator workflow
-----------------

```bash
docker compose run --rm --profile operator doc-worker sync-repo
```

The repo remains read-only for `doc-worker`; runtime artifacts and reports are
published under `/data/corp_docs`.
