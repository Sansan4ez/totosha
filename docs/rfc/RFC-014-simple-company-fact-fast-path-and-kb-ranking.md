# RFC-014: Simple Company-Fact Fast Path And KB Ranking

Status
------

Proposed

Date
----

2026-04-08

Summary
-------

Short company-fact questions such as `Расскажи о компании` and `Подскажи контакты компании` currently go through the general ReAct loop, even though the required data already exists in the corporate PostgreSQL knowledge base.

In the current behavior:

- `corp_db_search(kind=hybrid_search, profile=kb_search)` returns `success`;
- the payload often already contains the correct `kb_chunk` rows from `common_information_about_company.md`;
- the agent still spends several extra LLM iterations;
- the LLM may try `doc_search`, get blocked by the routing guardrail, and then answer with a false-negative phrase such as `нет подтверждённых контактов`.

This RFC proposes a simple and effective fix:

- keep company facts in the current corporate DB path;
- avoid new services, new indexes, and multi-step orchestration;
- introduce a deterministic company-fact fast path in the agent;
- tighten relevance checks for company-fact `success`;
- add a small ranking/alias improvement in the DB for the existing company profile chunks.

Problem Statement
-----------------

The current company-fact path is too general for a narrow and frequent task.

Observed on 2026-04-08:

- `tools-api` returns `kb_chunk` rows for both general company info and contacts;
- DB latency is acceptable, typically well below the LLM time budget;
- the agent still takes about 28-29 seconds because most time is spent in repeated LLM calls;
- routing marks the first company-fact lookup as successful too early;
- once marked successful, the guardrail blocks `doc_search`;
- the final natural-language answer is still delegated to the LLM and may contradict the payload.

The practical failure mode is:

1. successful DB lookup;
2. unsuccessful agent interpretation;
3. polite but wrong final answer.

Goals
-----

- Answer short company-fact questions directly from the corporate DB.
- Minimize LLM iterations for company facts.
- Return deterministic, user-ready answers for:
  - general company info;
  - contacts;
  - address;
  - website;
  - year founded;
  - requisites.
- Keep the solution simple enough to maintain without a new retrieval subsystem.
- Preserve the existing `corp_db_search` contract as much as possible.

Non-Goals
---------

- Moving company facts out of PostgreSQL into a separate wiki or search service.
- Building a new ranking engine.
- Replacing `hybrid_search` for all intents.
- General document-search redesign.
- Reworking application recommendation or catalog search.

Design Principles
-----------------

- Prefer deterministic rendering over extra LLM reasoning when the payload is already sufficient.
- Prefer a small number of explicit company-fact templates over free-form query generation.
- Keep the fallback chain shallow.
- Optimize for correctness first, then latency.

Target Behavior
---------------

For short company-fact questions:

1. the router selects `corp_db.company_profile`;
2. the agent rewrites the user query into a canonical company-fact query template;
3. the agent calls one `corp_db_search(kind=hybrid_search, profile=kb_search, entity_types=["company"])`;
4. the agent validates that the returned payload is relevant to the asked fact type;
5. if relevant, the agent renders the final answer deterministically and stops;
6. only if the payload is not relevant enough does the agent try one fallback path.

Examples:

- `Подскажи контакты компании.`  
  Returns phone, email, address, and website from the company contact chunks.

- `Расскажи о компании.`  
  Returns a short summary from `О компании` and `Наш профиль`, optionally with the website.

- `Когда основана компания?`  
  Returns the year if found in the company profile chunk.

Proposed Changes
----------------

### A. Add a deterministic company-fact fast path in the agent

When intent is `company_fact`, the agent should not rely on free-form ReAct completion after the first successful company-fact lookup.

Instead:

1. call `corp_db_search` once with canonical args;
2. inspect the payload locally;
3. render the answer directly in Python;
4. stop the run.

This reuses the existing helpers in `core/agent.py`, but moves them from empty-completion fallback into the normal success path.

### B. Tighten what counts as a successful company-fact lookup

Current company-fact success detection is too broad. It treats many `success` payloads as confirmed even when the top results are only loosely related.

New rules:

- `contacts` intent is successful only if the payload yields at least one of:
  - phone;
  - email;
  - postal address;
  - website.
- `about_company` intent is successful only if top results include a known company-profile title or heading such as:
  - `О компании`;
  - `Наш профиль`;
  - `Контактная информация`;
  - `Реквизиты`;
  - `Социальные сети компании`.
- `website` intent is successful only if a URL is extracted.
- `year_founded` intent is successful only if a year is extracted.

If these checks fail, the result is treated as non-confirmed and the guardrail must not lock the agent into an incorrect success state.

### C. Use canonical company-fact query templates on the primary path

The query rewrite logic already exists in `core/agent.py`, but it is mainly used in fallback logic.

This RFC makes canonical query expansion mandatory for company facts before the first `corp_db_search`.

Canonical examples:

- contacts: `239-18-11 lad@ladled.ru контакты ladzavod`
- general info: `общая информация о компании ЛАДзавод светотехники`
- address: `челябинск чайковского 3 адрес офиса ladzavod`
- website: `официальный сайт компании ЛАДзавод светотехники`

This is intentionally simple. It is cheaper and more stable than allowing the LLM to invent ad hoc search strings.

### D. Add a small DB ranking improvement for company profile chunks

The current knowledge rows already exist, but generic phrases like `контакты компании` can still rank weakly because all related chunks share nearly identical aliases.

Add explicit aliases for the existing company rows in `corp.corp_search_docs` and, if needed, in the source import path for `knowledge_chunks`:

- `О компании`
  - `о компании общая информация профиль история компания ladzavod`
- `Контактная информация`
  - `контакты телефон email e-mail адрес офис ladzavod`
- `Реквизиты`
  - `реквизиты инн кпп огрн юридическая информация`
- `Социальные сети компании`
  - `сайт telegram youtube vk соцсети ladzavod`

This is intentionally a small targeted change, not a generic ranking rewrite.

### E. Keep `doc_search` out of the default path for these questions

Right now documents are not yet the primary source for these queries, and the user explicitly noted that the relevant information is already in the same DB.

So the default order should be:

1. `corp_db_search` company fast path;
2. deterministic render;
3. stop.

`doc_search` should remain a fallback only for:

- explicit wiki/document requests;
- real DB miss;
- future cases where company facts are intentionally moved into the document corpus.

### F. Add low-cost observability fields for this path

This RFC does not implement full observability wiring. That is handled separately in RFC-013.

But this path should still emit clear local metadata:

- `company_fact_intent_type`
- `company_fact_fast_path=true/false`
- `company_fact_rendered=true/false`
- `company_fact_payload_relevant=true/false`
- `company_fact_fallback_reason`

These fields make debugging possible even before end-to-end tracing is fully fixed.

Implementation Outline
----------------------

1. In `core/agent.py`, split company-fact intent into subtypes:
   - `about_company`
   - `contacts`
   - `website`
   - `address`
   - `year_founded`
   - `requisites`
2. Reuse `_expand_company_fact_query()` on the primary path, not only on fallback.
3. Add a relevance validator for company-fact payloads.
4. After the first relevant `corp_db_search`, render the final answer deterministically and return immediately.
5. Only if relevance validation fails, allow one fallback path.
6. Update KB aliases for the company profile chunks in DB/init or import logic.
7. Add regression tests and benchmark cases.

Testing Approach
----------------

### Unit tests

- company-fact subtype classification
- canonical query rewrite selection
- payload relevance checks
- deterministic rendering for:
  - contacts
  - about company
  - website
  - year founded

### Integration tests

- `corp_db_search(kind=hybrid_search, profile=kb_search)` for:
  - `общая информация о компании ЛАДзавод светотехники`
  - `239-18-11 lad@ladled.ru контакты ladzavod`
- verify returned top chunks contain the expected company rows

### End-to-end tests

- `Расскажи о компании`
- `Подскажи контакты компании.`
- `Какой официальный сайт компании?`
- `Когда основана компания?`

Checks:

- no false-negative phrasing;
- at most one `corp_db_search` in the happy path;
- no `doc_search` unless explicitly needed;
- reduced total LLM calls versus current behavior.

Acceptance Criteria
-------------------

1. `Расскажи о компании` returns a short factual summary from the company DB payload, not a refusal.
2. `Подскажи контакты компании.` returns at least one confirmed contact fact from the DB payload.
3. Happy-path company-fact requests finish without an extra `doc_search`.
4. Happy-path company-fact requests render from deterministic Python logic after the first relevant `corp_db_search`.
5. Generic company-fact requests no longer depend on multiple LLM iterations to form the final answer.
6. Benchmark coverage includes live `agent_chat` cases for the two production queries above.

Risks
-----

- If the relevance validator is too strict, the agent may fall back more often than necessary.
- If the alias patch is too narrow, future company-fact variants may still rank inconsistently.
- If deterministic rendering grows too large, the simple path may start to resemble a second agent.

The mitigation is to keep the scope narrow and focused on short company-fact requests only.

Open Questions
--------------

- Should the company-fact subtype be recorded in benchmark artifacts as a first-class field?
- Should the alias patch live in DB bootstrap SQL, import code, or both?
