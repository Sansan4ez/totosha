---
name: doc-search
description: Многоформатный поиск по локальному document corpus: `md`, `pdf`, `docx`, `xlsx`, `pptx`, `png`, `jpg`, `tiff` и другим рабочим документам; legacy `doc/xls/ppt` доступны только после ingest через `doc-worker` с LiteParse/LibreOffice runtime. Используй tool `doc_search` как canonical document-search path. `corp_wiki_search` и `corp-wiki-md-search` — deprecated aliases на переходный период.
---

# Doc search

Use this skill when the user explicitly asks for document context, citation, fragment, policy text, certificate link, or when `corp_db_search` returned `empty` / error and you need fallback retrieval from the local document corpus.

## Core rules

- Canonical tool: `doc_search`.
- Deprecated alias: `corp_wiki_search`.
- Canonical source name: `doc-search`.
- Do not use this skill as default path for short company-fact questions if `corp_db_search` already returned a sufficient answer.
- Prefer `corp_db_search` for company facts and promoted hot-path content.

## Corpus model

`doc_search` works across:
- live document manifests under `/data/corp_docs/live/`
- normalized sidecars under `/data/corp_docs/parsed/`
- legacy wiki folder `/data/skills/corp-wiki-md-search/wiki/` during migration

The tool reads normalized sidecars on the chat path. Heavy parsing and legacy Office conversion belong to `doc-worker`, not to shell commands inside the agent.

## Quick workflow

1. Clarify what exact document fact, quote, fragment, or file the user wants.
2. If the request is a short company fact, use `corp_db_search` first.
3. If document retrieval is appropriate, run `doc_search`.
4. Answer from the returned snippet. Quote only short fragments when needed.
5. Offer one narrow follow-up if the query is broad.

## Example

```json
{"query":"сертификат CE LAD LED R500", "top":5, "include_legacy":true}
```

## Output rules

- Prefer short answers and compact snippets.
- Do not dump full documents.
- If the user asks for a citation, cite a short fragment from the returned snippet rather than exposing internal paths or tool details.
