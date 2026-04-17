RFC-022 Embedded Ephemeral Agent Web Chat With Structured UI
============================================================

Status
------

Proposed

Date
----

2026-04-17

Analyzed upstreams
-----------------

- `langgenius/webapp-conversation`
  - repo: `https://github.com/langgenius/webapp-conversation`
  - analyzed commit: `510ac2afaac4eaa227ae8e50e0427f16cc122d54`
- `openai/openai-structured-outputs-samples`
  - sample: `conversational-assistant`
  - repo: `https://github.com/openai/openai-structured-outputs-samples`

Context and motivation
----------------------

`totosha` already has:

- production agent runtime in `core`;
- Telegram and userbot channels;
- operator UI in `admin`;
- access control, sandboxing and proxy-based secrets isolation.

The missing piece is a simple browser chat surface for embedding into another site as a popup or iframe, for example:

```html
<iframe
 src="https://lab.llm-studio.pro/chatbot/..."
 style="width: 100%; height: 100%; min-height: 700px"
 frameborder="0"
 allow="microphone">
</iframe>
```

The clarified product requirement is intentionally narrow:

- no full chat application;
- no sessions list;
- no persistent history after the popup closes;
- no conversation rename;
- no long-lived message store;
- voice input is not required in `v1`.

This changes the integration strategy completely. We do not need a conversation platform. We need a thin embedded web channel for the existing agent.

At the same time, the widget should not be plain text-only if we can avoid it. The OpenAI sample demonstrates a useful pattern for structured visual responses:

- product cards;
- comparison charts;
- tables;
- custom tool result blocks.

That renderer pattern is worth keeping even though the sample's backend and tool loop are not.

Goals
-----

- Add a simple browser chat channel for the existing agent.
- Support embedding in iframe or popup form factor.
- Keep the backend path as close as possible to the current Telegram -> `core` flow.
- Avoid persistent user chat history in `v1`.
- Keep all secrets server-side.
- Keep `admin` separate from the end-user chat widget.
- Preserve a path for structured visual results such as cards, tables and charts.

Non-goals
---------

- Building a standalone chat product with stored conversations.
- Reproducing Dify-style conversation management.
- Adding voice input in `v1`.
- Adding file uploads in `v1`.
- Replacing `admin`.
- Exposing `proxy`, `tools-api` or LLM endpoints directly to the browser.
- Implementing full generative UI platform semantics beyond a controlled renderer contract.

Current state analysis
----------------------

### 1. The existing agent entrypoint is already simple

Telegram currently sends requests to `core` through a small HTTP contract:

- `POST /api/chat`
- payload:
  - `user_id`
  - `chat_id`
  - `message`
  - `username`
  - `source="bot"`
  - `chat_type`

`core` accepts this in `core/api.py` and returns a single final `response`.

This means a browser channel does not need a new agent architecture. It only needs a browser-safe adapter that can call the same runtime path with `source="web"`.

### 2. `langgenius/webapp-conversation` is too heavy for the real requirement

The repo provides polished chat UX, but it is built around a Dify-style application contract:

- `conversation_id`
- message history APIs
- rename flows
- uploads
- feedback
- SSE events for a conversation lifecycle

That is useful for a full web chat product, but it does not match the clarified requirement of an ephemeral embedded widget.

Using it for this scope creates unnecessary work:

- rewrite Dify-specific route handlers;
- emulate or replace conversation APIs;
- strip persistence assumptions;
- disable much of the shipped UI.

### 3. The OpenAI `conversational-assistant` sample is architecturally closer

The OpenAI sample is much simpler:

- one chat view;
- one turn endpoint;
- SSE streaming;
- client-side in-memory conversation state;
- no required persistent conversation backend;
- structured visual rendering via typed UI payloads.

That shape is much closer to our requirement. However, the sample is still not a drop-in fit because:

- it runs its own OpenAI SDK call directly in the app server;
- it owns its own tool-calling loop;
- its tool semantics live in the sample itself, not in `totosha/core`.

So the UI pattern is useful, but the backend logic must be replaced.

### 4. The most reusable part of the OpenAI sample is the structured UI renderer

The valuable idea in the sample is not its OpenAI-specific orchestration. The valuable idea is this pipeline:

1. The model emits a structured tool result or UI payload.
2. That payload is validated against a narrow schema.
3. The frontend maps the payload to prebuilt React components.
4. The browser renders cards/tables/charts without executing model-authored code.

This gives us rich presentation without allowing the model to generate arbitrary HTML, CSS or JSX.

For `totosha`, this is a strong fit because:

- it keeps rendering deterministic;
- it avoids XSS-prone raw HTML rendering;
- it allows progressive enhancement beyond plain text;
- it can coexist with a simple ephemeral widget.

### 5. Persistent storage is explicitly unnecessary in `v1`

Because the widget is ephemeral and history is discarded when closed:

- `SESSION.json` is irrelevant for the web widget;
- no `conversation_id` registry is needed;
- no rename/list/history APIs are needed;
- no long-lived message database is needed.

The only state needed in `v1` is in-memory widget state for the current open browser instance.

Decision
--------

`v1` uses a standalone embedded web module named `agent-web` with:

- an ephemeral chat model;
- a minimal browser-to-core adapter;
- a structured UI renderer inspired by OpenAI `conversational-assistant`.

The architecture is:

1. Browser iframe/popup loads `agent-web`.
2. `agent-web` sends user messages to a server-side adapter endpoint.
3. The adapter calls the existing `core /api/chat` path with:
   - synthetic or scoped `user_id`
   - synthetic per-widget `chat_id`
   - `source="web"`
   - `chat_type="private"`
4. `core` runs the normal agent flow.
5. `agent-web` renders either:
   - plain text assistant output, or
   - structured UI blocks such as cards/tables/charts when present.
6. When the iframe/popup closes, the browser-side chat state is lost.

In other words:

- reuse the runtime;
- add a new transport/channel;
- do not add a conversation platform.
- keep a controlled structured-rendering layer for rich responses.

Why this is the right scope
---------------------------

- It matches the product requirement exactly.
- It minimizes backend changes.
- It avoids building storage and history features that are explicitly unwanted.
- It stays close to the existing Telegram path, which reduces risk.
- It preserves the current secrets and security boundaries.

Alternatives considered
-----------------------

### Option A. Fork `webapp-conversation` and implement a reduced Dify-like backend

Pros:

- polished UX out of the box;
- mature chat layout.

Cons:

- too much surface area for the requirement;
- requires stripping conversation/history assumptions;
- pushes us toward solving persistence problems we do not need.

Verdict:

- rejected for `v1`.

### Option B. Use the OpenAI `conversational-assistant` sample shape and replace its backend logic

Pros:

- much closer to ephemeral widget behavior;
- already centered around a single-turn endpoint and in-memory state;
- easier to embed and simplify.
- includes a strong structured UI renderer pattern for cards, tables and charts.

Cons:

- sample backend must be rewritten to call `core` instead of OpenAI directly;
- sample tool loop must be removed;
- sample demo business tools and mock data must be removed.

Verdict:

- accepted as the preferred foundation for `v1`.

### Option C. Build a minimal custom widget from scratch

Pros:

- smallest scope;
- zero inherited platform assumptions.

Cons:

- slightly more UI work than adapting a simple sample;
- no ready-made streaming/parser ergonomics.

Verdict:

- also acceptable.
- If adaptation friction from the OpenAI sample is high, this becomes the preferred implementation path.

Recommended frontend shape
--------------------------

The recommended `v1` frontend is a minimal standalone widget, not a full chat application.

UI requirements:

- one scrollable message area;
- one text input;
- one send button;
- loading state while the agent responds;
- optional close/reset button controlled by host page;
- responsive layout for iframe/popup;
- no sidebar;
- no history list;
- no attachments;
- no voice input in `v1`.

The rendering model should still support two content classes:

1. plain assistant messages;
2. structured visual blocks rendered from validated payloads.

Preferred implementation approach:

1. fork the OpenAI `conversational-assistant` sample into a repo-owned `agent-web`;
2. strip it down aggressively;
3. keep the renderer architecture for structured UI;
4. replace all sample backend/tool logic with `totosha` adapter logic.

If that fork ends up carrying too much dead weight, the fallback is a smaller custom widget that reuses only the renderer concepts.

Structured UI model
-------------------

The widget should not accept arbitrary HTML from the model.

Instead it should use a controlled contract similar to the sample:

- a finite list of supported component types;
- strict JSON schemas for component props;
- React mapping from schema type to local component;
- recursive rendering only through that mapping.

Initial supported visual components should be intentionally small:

- `card`
- `header`
- `table`
- `bar_chart`
- `product_card` or equivalent item card

Optional later additions:

- `carousel`
- order cards
- compact status/result banners

This gives us a safe visual grammar without turning the widget into a generic page builder.

Where structured payloads come from
-----------------------------------

There are two viable ways to feed the renderer:

### Option 1. `core` returns text plus optional UI artifact

`core` remains responsible for orchestration and may emit:

- `response_text`
- optional `ui_artifact`

Where `ui_artifact` conforms to the widget schema.

This is the cleaner target design because:

- orchestration stays in `core`;
- widget remains presentation-only;
- the same runtime can later reuse the same artifact in other channels if needed.

### Option 2. `agent-web` interprets narrow structured tool outputs

The adapter can initially detect specific structured payloads already returned by tools and map them into UI blocks.

This is acceptable as a bootstrap path, but it should not become the long-term ownership boundary if it starts duplicating agent logic.

Decision for RFC:

- target design is Option 1;
- bootstrap implementation may temporarily use Option 2 if it reduces initial effort.

Backend contract
----------------

`v1` should not introduce a large `/api/web/*` surface.

A minimal contract is enough:

- `POST /api/web/chat`
- optional `GET /api/web/health`

`POST /api/web/chat` request:

- `message`
- optional `widget_session_id`
- optional host metadata if needed later

Server-side adapter responsibilities:

- resolve or mint synthetic `user_id`;
- mint synthetic per-widget `chat_id`;
- call existing `core /api/chat`;
- set `source="web"`;
- force `chat_type="private"`;
- return the agent response to the widget;
- forward optional structured UI artifacts when present.

### Transport modes

Two acceptable transport modes exist:

#### Mode 1. Simple request/response

The adapter waits for `core` to finish and returns:

- `{ "response": "...", "ui_artifact": null | { ... } }`

This is the fastest implementation and is enough for `v1`.

#### Mode 2. SSE wrapper

The adapter still calls the same `core /api/chat`, but returns the result as a small SSE stream for better UX.

Example event flow:

- `message_start`
- one or more `message_delta`
- `message_end`

Important detail:

- this is only a UI transport wrapper;
- it does not require true token streaming from `core` in `v1`.
- structured UI can still be delivered at end-of-turn even if text is not token-streamed.

If speed matters most, start with Mode 1 and add SSE later.

Identity model
--------------

Because there is no persistent history requirement, identity can stay minimal.

Recommended model:

- widget generates a random ephemeral id on load;
- adapter maps it to synthetic `user_id` and `chat_id`;
- mapping lives only for the widget lifetime or short TTL;
- closing the popup effectively abandons the session.

This is enough to preserve runtime assumptions in `core` without adding real web account/session management.

Important constraint:

- `user_id` and `chat_id` must not be trusted from the browser as authoritative internal ids;
- the server-side adapter owns final identity assignment.

Runtime integration
-------------------

`core` should gain explicit support for `source="web"`.

Required behavior:

- web calls are observable separately from Telegram calls;
- channel can be enabled/disabled independently;
- access policy can be tightened later without changing the widget contract.

Recommended additions:

- `web_enabled` flag in access/config;
- `source="web"` in logs and tracing;
- same `run_agent(...)` code path as Telegram unless a web-specific exception is truly necessary.
- optional support for returning `ui_artifact` alongside text response.

Structured UI ownership
-----------------------

The widget owns only rendering.

`core` owns:

- deciding when a visual artifact is useful;
- producing or relaying structured payloads;
- ensuring those payloads remain within the agreed schema.

`agent-web` owns:

- schema validation on the client/server boundary;
- mapping payloads to React components;
- fallback to plain text if the artifact is missing or invalid.

This split prevents the frontend from becoming a second orchestration engine.

Security model
--------------

The widget must preserve the existing security posture:

- browser never talks to `proxy` directly;
- browser never sees LLM credentials;
- adapter is the only browser-facing API surface;
- `core` remains the runtime trust boundary.
- structured UI payloads are schema-constrained and rendered only through local components.

Because the widget is intended for embedding:

- CORS and iframe policy must be configured intentionally;
- allowed host origins should be explicit;
- rate limiting for `source="web"` should exist from day one.

For `v1`, recommended deployment stance:

- widget enabled only for known host sites;
- not an anonymous public chat endpoint by default.

Voice and media
---------------

Voice input is out of scope for `v1`.

Implications:

- do not request microphone permissions by default;
- do not expose audio upload UI;
- keep the browser `allow="microphone"` optional at embed level, not required by the widget itself.

File uploads are also out of scope for `v1`.

This keeps the first release aligned with the simplest safe path.

Deployment topology
-------------------

`docker-compose.yml` gains one new service:

- `agent-web`

Its responsibilities:

- serve the embedded widget UI;
- expose the adapter endpoint used by the browser;
- call `core` internally;
- remain the only browser-facing web chat service.

Recommended topology:

1. Host page embeds iframe.
2. iframe loads `agent-web`.
3. `agent-web` calls internal `core`.
4. `core` uses existing `proxy`, `tools-api`, sandbox and other internals.

`admin` remains separate and unchanged.

Observability
-------------

Minimal telemetry for `v1`:

- request count for widget chat calls;
- latency for adapter and `core` runtime;
- error rate;
- rate-limit rejects;
- host origin or deployment tag if needed;
- `source=web` correlation in existing traces/logs.
- count of responses containing `ui_artifact`.

This is enough to compare widget traffic with Telegram traffic without storing end-user history.

Implementation outline
----------------------

1. Add web channel support in `core`
   - accept `source="web"` explicitly;
   - add `web_enabled` config gate;
   - ensure observability labels distinguish web from bot.

2. Build `agent-web` adapter
   - add `POST /api/web/chat`;
   - map widget request to `core /api/chat`;
   - own synthetic ids server-side.

3. Build the widget UI
   - minimal message list;
   - input + send;
   - loading/error states;
   - reset on close/reload.

4. Port structured renderer from the OpenAI sample
   - keep component schema definitions;
   - keep component-to-React mapping;
   - remove sample business tools and mock data;
   - support plain text plus optional `ui_artifact`.

5. Embed integration
   - verify iframe deployment;
   - configure allowed origins and framing policy;
   - confirm popup close semantics discard local state.

6. Optional polish
   - SSE wrapper;
   - host-page API via `postMessage`;
   - theme/custom branding props.
- richer renderer components such as carousel.

Testing approach
----------------

### Unit

- synthetic id generation and mapping;
- adapter request validation;
- `source="web"` config gating;
- origin checks and rate limiting.
- UI artifact schema validation;
- component mapping/render fallback.

### Integration

- widget request reaches `core /api/chat`;
- `core` runs the normal agent path with `source="web"`;
- response returns correctly to the widget;
- structured UI payload renders as local React components;
- disabling `web_enabled` blocks the channel cleanly.

### Manual

- open the widget in iframe;
- send a message and get a response;
- verify a sample structured response renders as cards/table/chart;
- reload iframe and confirm chat state is reset;
- close popup and reopen it, confirm history is gone;
- verify Telegram and `admin` flows still work.

Acceptance criteria
-------------------

- A site can embed the web chat in iframe or popup form.
- The embedded chat works without a conversation list or stored history.
- Closing or reloading the widget resets the chat state in `v1`.
- The browser never receives internal LLM or proxy credentials.
- The widget reaches the same agent runtime as Telegram, via `core`.
- Web traffic is labeled separately as `source="web"`.
- `admin` remains unchanged.
- Voice input and file uploads are absent in `v1`.
- The widget can render schema-validated structured results such as cards, tables or charts without executing model-authored HTML/JSX.
