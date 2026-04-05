---
name: corp-wiki-md-search
description: Deprecated alias for `doc-search`. Исторически это был поиск по корпоративной wiki (Markdown), теперь используй canonical skill `doc-search` и tool `doc_search` для поиска по многоформатному локальному document corpus. `corp_wiki_search` остаётся backward-compatible alias.
---

# Deprecated wiki alias

This alias stays only for migration compatibility.

Canonical replacement:
- skill: `doc-search`
- tool: `doc_search`

Rules:
- Before using this alias, confirm that `corp_db_search` did not already return a sufficient answer, unless the user explicitly asked for document context.
- Prefer `doc_search`. The old name `corp_wiki_search` is still accepted, but should not be the default in prompts or examples.
- Legacy wiki under `/data/skills/corp-wiki-md-search/wiki/` remains searchable through the canonical `doc_search` tool.
