---
name: doc-search
description: Многоформатный поиск внутри конкретных document-domain routes локального corpus: `md`, `pdf`, `docx`, `xlsx`, `pptx`, `png`, `jpg`, `tiff` и другим рабочим документам; legacy `doc/xls/ppt` доступны только после ingest через `doc-worker` с LiteParse/LibreOffice runtime. Используй tool `doc_search` только когда route card указывает конкретный документ/документную тематику.
---

# Doc search

Use this skill for concrete `doc_domain` route cards: the route must point at known document selectors, preferred document ids, or a defined document topic from ingestion metadata. `doc_search` is not a generic corpus fallback and not the default for bare company facts.

## Core rules

- Canonical tool: `doc_search`.
- Canonical source name: `doc-search`.
- Treat `doc_search` as the primary route only for concrete document-domain requests, not as a generic fallback after KB miss.
- Do not use this skill as default path for short company-fact questions if `corp_db_search` already returned a sufficient answer.
- Prefer `corp_db_search` for company facts and promoted hot-path content, including generic certificates, declarations, components, and quality questions.

## Corpus model

`doc_search` works across:
- live document manifests under `/data/corp_docs/live/`
- normalized sidecars under `/data/corp_docs/parsed/`

The tool reads normalized sidecars on the chat path. Heavy parsing and legacy Office conversion belong to `doc-worker`, not to shell commands inside the agent.

## Quick workflow

1. Clarify what exact document, quote, fragment, file, or document-domain topic the user wants.
2. If the route selector selected a concrete document route, run `doc_search` with the route `preferred_document_ids` / document selectors.
3. If the request is a short company fact without document-domain signal, use `corp_db_search` first.
4. If `corp_db_search` returned `empty` / error and document retrieval is still appropriate, escalate only to a concrete document route.
5. Answer from the returned snippet. Quote only short fragments when needed.
6. Offer one narrow follow-up if the query is broad.

## Example

```json
{"query":"сертификат CE LAD LED R500", "top":5}
```

## Output rules

- Prefer short answers and compact snippets.
- Do not dump full documents.
- If the user asks for a citation, cite a short fragment from the returned snippet rather than exposing internal paths or tool details.
