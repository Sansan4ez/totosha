RFC-024 Agent Web Abuse Controls And Session Bounding
=====================================================

Status
------

Proposed

Date
----

2026-04-17

Related RFCs
------------

- `RFC-022-agent-web-chat-frontend-integration.md`

Context and motivation
----------------------

`RFC-022` introduces an embedded ephemeral `agent-web` channel. The basic shape is correct:

- browser widget;
- server-side adapter;
- `core /api/chat`;
- `source="web"`;
- no persistent browser history after closing the widget.

However, review of the first implementation surfaced two operational risks that make a public endpoint unsafe:

1. rate limiting can be bypassed if it depends on client-supplied session identifiers;
2. anonymous requests can mint unbounded backend sessions and workspace directories.

The system already has a layered security posture elsewhere, and the web channel should follow the same principle. The solution must stay simple, reliable, and efficient. It should not require a full conversation platform or a database-backed session service for `v1`.

The server already has `fail2ban` available. That is useful, but it should be treated as an outer coarse-grained abuse control, not as the only enforcement mechanism.

Goals
-----

- Prevent one source IP from bypassing web rate limits by rotating session identifiers.
- Prevent unbounded growth of backend web sessions, memory, and workspace directories.
- Preserve ephemeral browser behavior for the widget.
- Keep the implementation operationally simple for `v1`.
- Integrate cleanly with an already deployed `fail2ban` installation.
- Keep the design usable both for public web mode and restricted web mode.

Non-goals
---------

- Building a durable multi-tenant web session platform.
- Introducing Redis, Postgres, or another new state service just for web session control.
- Replacing reverse-proxy or firewall controls with application logic.
- Making `fail2ban` the primary online rate limiter.
- Preserving unlimited parallel anonymous widget sessions.

Design principles
-----------------

- **Server trust only**: client-supplied session identifiers are hints, not trust anchors.
- **Bounded state**: every in-memory registry and every workspace path must have a hard upper bound or TTL.
- **Immediate local enforcement**: abuse controls should reject requests before model/runtime work begins.
- **Layered controls**: application throttling handles short-term fairness; `fail2ban` handles repeated abusive IPs.
- **Graceful degradation**: the system still functions when `fail2ban` is absent, but bans become less aggressive.
- **Explicit operator knobs**: limits should be configurable through environment or admin config, not hidden in code.

Decision
--------

`agent-web` uses a three-layer protection model for public or semi-public web exposure:

1. **Application-level IP rate limiting**
   - enforced inside `agent-web`;
   - keyed by trusted client IP only;
   - independent of client-supplied `session_token`;
   - applied before adapter dispatch to `core`.

2. **Bounded server-side web session registry**
   - server issues and validates opaque session tokens;
   - registry entries have TTL and a hard cap;
   - invalid or missing client tokens do not create unbounded new identities;
   - backend web workspaces are reclaimed on expiry.

3. **Host-level abuse escalation via `fail2ban`**
   - `agent-web` emits explicit abuse log lines for repeated rate-limit events and invalid-session churn;
   - `fail2ban` watches those logs and bans repeat offenders at the server boundary;
   - this is a reinforcement layer, not the primary real-time limiter.

High-level behavior
-------------------

### Request flow

For every `agent-web` request:

1. Resolve the trusted client IP.
2. Apply an application-level IP rate limiter.
3. Resolve a server-issued web session token.
4. If the token is valid and not expired:
   - reuse the existing bounded backend session mapping.
5. If the token is missing or invalid:
   - either mint a new bounded session entry, or
   - reject if global/per-IP anonymous session budgets are exhausted.
6. Dispatch to `core /api/chat`.
7. Refresh the session TTL.
8. Return plain text and optional `ui_artifact`.

### Browser semantics

The widget still behaves as ephemeral browser state:

- open widget: session may start or resume;
- reload same tab: same browser-side session token may be reused;
- close tab/window: browser state disappears;
- if the server-side TTL expires, the next request starts a fresh bounded session.

This means the browser remains ephemeral while the server uses short-lived bounded state to avoid unbounded churn.

### Restricted deployments

When the deployment uses restricted access mode rather than anonymous public mode:

- the adapter may use a configured server-side web identity such as `AGENT_WEB_USER_ID`;
- this supports `admin_only` or `allowlist` mode;
- rate limiting still applies per IP;
- bounded session state still applies.

Abuse control layers
--------------------

### 1. Application-level IP limiter

The in-app limiter is the first line of defense because it is immediate and cheap.

Recommended policy for `v1`:

- key by trusted source IP only;
- resolve the trusted IP from `X-Forwarded-For` first, then `X-Real-IP`, then `CF-Connecting-IP`, else fall back to `unknown`;
- fixed or sliding window is acceptable;
- do not include raw `session_token` in the limiter key;
- reject with `429` before any `core` call;
- log an explicit structured event on every reject.

Recommended knobs:

- `AGENT_WEB_RATE_LIMIT_WINDOW_S`
- `AGENT_WEB_RATE_LIMIT_MAX_REQUESTS`

Example:

- `12` requests per `60` seconds per IP for chat turns.

This is intentionally simple and robust. It may be slightly unfair for multiple users behind one NAT, but it is much safer than token-based throttling.

Operational note:

- if the reverse proxy does not forward a trustworthy client IP, all requests collapse into `unknown`;
- that is acceptable as a fail-safe for application throttling, but too coarse for meaningful `fail2ban` bans;
- deployments that enable `fail2ban` escalation should preserve the real client IP at the proxy boundary.

### 2. Bounded server-side web session registry

The web channel needs short-lived server-side session state, but not unlimited session creation.

The registry stores:

- server-issued `session_token`;
- backend session identifiers;
- last activity time;
- source IP;
- optional configured identity mode flag.

Required properties:

- TTL, for example `15` to `30` minutes of inactivity;
- global maximum active web sessions;
- optional maximum active web sessions per IP;
- periodic cleanup of expired entries;
- cleanup of associated backend workspace/session state.

The key constraint is critical:

- a missing or invalid client token must not cause infinite new backend identity allocation.

Instead:

- if under budget, mint one new bounded session entry;
- if over budget, reject with `429` or `503` depending on policy;
- log the event for observability and `fail2ban`.

### 3. `fail2ban` integration

`fail2ban` is useful here because it escalates from request-level throttling to host-level temporary bans.

Recommended usage:

- `agent-web` emits explicit abuse markers to its own service log;
- `fail2ban` watches that log stream, not the browser response payload;
- repeated matches lead to a temporary ban at the host or reverse-proxy boundary.

Current `v1` marker contract:

- emitted marker: `WEB_RATE_LIMIT_REJECT`;
- emitted from `agent-web/lib/server/rate-limit.ts` whenever the in-app per-IP limiter rejects a request;
- logged as one JSON object on one line via `console.warn(...)`;
- current fields:
  - `event`
  - `abuse_marker`
  - `ip`
  - `method`
  - `path`
  - `window_s`
  - `max_requests`
  - `seen_requests`
  - `retry_after_s`

Example line:

```json
{"event":"WEB_RATE_LIMIT_REJECT","abuse_marker":"WEB_RATE_LIMIT_REJECT","ip":"203.0.113.24","method":"POST","path":"/api/web/chat","window_s":60,"max_requests":12,"seen_requests":12,"retry_after_s":41}
```

Reserved follow-on markers for later session-bounding work:

- `WEB_SESSION_BUDGET_REJECT`
- `WEB_INVALID_SESSION_BURST`

These names are documented now so the abuse vocabulary stays coherent, but they should be treated as future extensions until bounded server-side session enforcement lands.

This gives a clean separation:

- app limiter handles per-request fairness and immediate rejection;
- `fail2ban` handles repeated attackers over minutes.

Why `fail2ban` is not enough on its own:

- it is reactive, not immediate;
- it depends on log parsing and ban thresholds;
- it does not protect the first burst of expensive requests by itself;
- it is coarse-grained and may not be present in every environment.

So the correct stance is:

- **required**: in-app IP limiter;
- **recommended**: `fail2ban` escalation;
- **optional**: reverse-proxy rate limit in front of `agent-web`.

Abuse-log contract
------------------

The abuse-log contract is intentionally small and stable.

Required properties:

- one rejection event per line;
- machine-parsable JSON;
- explicit `abuse_marker` string for filter matching;
- explicit `ip` field derived from the same trusted-IP logic used by the in-app limiter;
- enough retry metadata for operators to correlate bans with limiter behavior.

Operational interpretation:

- `WEB_RATE_LIMIT_REJECT` means the request already lost at the application layer and did not reach `core`;
- `retry_after_s` communicates application backoff, not the `fail2ban` ban duration;
- `seen_requests` reflects local process state and is diagnostic only, not a cluster-wide counter.

The log contract should remain append-only:

- existing keys keep their meaning;
- new keys may be added;
- consumers should filter on `abuse_marker` and `ip`, not on full-line equality.

Fail2ban consumption
--------------------

`fail2ban` should consume these markers as an outer escalation layer:

- it should not replace the in-app limiter;
- it should react only after repeated abuse markers;
- it should ban after the application has already performed the cheap immediate rejects.

Suggested filter:

```ini
[Definition]
failregex = ^.*"abuse_marker":"WEB_RATE_LIMIT_REJECT".*"ip":"<HOST>".*$
ignoreregex =
```

Suggested jail shape:

```ini
[agent-web-rate-limit]
enabled = true
filter = agent-web-rate-limit
logpath = /var/log/agent-web.log
maxretry = 6
findtime = 10m
bantime = 30m
action = iptables-multiport[name=agent-web-rate-limit, port="80,443", protocol=tcp]
```

Notes:

- point `logpath` at the real `agent-web` log source in the deployment, such as a file, journald export, or Docker log collector output;
- do not parse browser access logs unless they preserve the same client-IP semantics as `agent-web`;
- keep `maxretry` above the single-window application limit so one short burst gets `429`s first and only repeated bursts get banned;
- if the service is behind Nginx, Caddy, or another reverse proxy, the ban action may live there instead of raw iptables.

Public web mode and restricted deployments
------------------------------------------

The same layering applies in both deployment styles, but the thresholds differ.

### Public web mode

Use the stricter profile when the widget is reachable by anonymous internet traffic:

- enable the in-app IP limiter unconditionally;
- enable `fail2ban` on `WEB_RATE_LIMIT_REJECT`;
- preserve the original client IP through the proxy chain;
- use comparatively short `findtime` and meaningful temporary bans because repeated `429` churn is expected attacker behavior;
- treat future `WEB_SESSION_BUDGET_REJECT` markers as high-signal once bounded anonymous sessions ship.

### Restricted deployments

Restricted deployments include `admin_only`, `allowlist`, private embeds, VPN-only exposure, or setups with configured `AGENT_WEB_USER_ID`.

Recommended stance:

- keep the in-app limiter enabled because restricted access does not eliminate automation mistakes or abuse;
- keep `fail2ban` available as an escalation layer, but usually with a looser threshold than public mode;
- if a reverse proxy or VPN already performs stronger identity-aware controls, `fail2ban` may stay enabled but should be tuned conservatively;
- do not depend on `fail2ban` for ordinary access control because `core` access mode and `web_enabled` remain the primary admission controls.

Session identity model
----------------------

Two deployment modes are supported.

### Mode A. Configured identity for restricted deployments

Use when the web channel is intentionally operator-controlled:

- `AGENT_WEB_USER_ID` is configured;
- optionally `AGENT_WEB_CHAT_ID` is configured;
- access control in `core` sees a known identity.

This is simple and reliable for:

- `admin_only`;
- `allowlist`;
- private website embeds.

### Mode B. Bounded anonymous identity for public deployments

Use when the widget is publicly reachable:

- `agent-web` mints server-issued session tokens;
- each active token maps to one bounded backend identity;
- tokens expire by TTL;
- expired entries are removed;
- new entries are refused when session budgets are exhausted.

The important design constraint is:

- anonymous mode uses bounded reuse and expiry, not infinite minting.

Backend cleanup
---------------

To make bounded sessions real, cleanup must happen in `core` as well as in `agent-web`.

Required behavior:

- expired web session entries are removed from the web session registry;
- corresponding `core` session entries are cleared;
- corresponding web workspace directories are removed or reclaimed;
- cleanup is idempotent and safe if the entry is already gone.

Recommended implementation shape:

- add explicit web-session cleanup helpers in `core`;
- isolate web workspaces under a dedicated subtree rather than treating them like long-lived Telegram user workspaces.

Preferred layout:

- `/workspace/web/<session-id>` or similar, not `/workspace/<synthetic-user-id>` indefinitely.

This reduces collision risk and makes cleanup operationally obvious.

Alternatives considered
-----------------------

### Option A. Rely primarily on `fail2ban`

Pros:

- simple to configure if already installed;
- blocks at the host boundary.

Cons:

- reactive;
- too slow for first-burst protection;
- does not solve unbounded backend session creation by itself;
- not portable enough as the primary control.

Verdict:

- rejected as the only control layer;
- accepted as an outer escalation layer.

### Option B. IP-only in-app limiter plus bounded server-side session registry

Pros:

- simple;
- immediate;
- no new infrastructure;
- directly addresses both review findings.

Cons:

- NAT fairness is imperfect;
- requires cleanup code for expired sessions.

Verdict:

- accepted for `v1`.

### Option C. Redis-backed distributed session and rate-limit service

Pros:

- strongest multi-instance coordination.

Cons:

- too much operational complexity for current scope;
- unnecessary before `agent-web` is horizontally scaled.

Verdict:

- rejected for `v1`;
- possible later if the web channel becomes a multi-instance public service.

Implementation outline
----------------------

1. Change the web rate limiter to key on trusted IP only.
2. Add explicit abuse log markers for rate-limit rejects now, and reserve the session-budget markers for the bounded-session follow-up.
3. Introduce a bounded server-side web session registry in `agent-web`.
4. Add TTL and global/per-IP caps for active web sessions.
5. Rework anonymous web identity allocation to reuse bounded registry entries rather than mint forever.
6. Add cleanup hooks in `core` for expired web session state and workspaces.
7. Move web workspaces into a dedicated subtree or add equivalent explicit cleanup semantics.
8. Add optional `fail2ban` documentation and sample filter/jail configuration.

Testing approach
----------------

### Unit tests

- limiter ignores caller-supplied `session_token`;
- repeated requests from one IP hit the limit even if tokens rotate;
- missing token creates at most one bounded session per admitted request;
- expired sessions are reclaimed;
- generic fenced `json` blocks remain plain text;
- explicit fenced `ui_artifact` blocks still work.

### Integration tests

- public web mode rejects bursts from one IP before `core` work begins;
- anonymous session creation stops at configured budget;
- expired web sessions are cleaned from registry and backend state;
- restricted mode with configured web identity still passes `core` access control.

### Manual tests

- open widget, send requests, reload same tab, confirm temporary continuity;
- close tab, wait for TTL, confirm a fresh session starts;
- force repeated `429`s and verify abuse logs are emitted;
- verify `fail2ban` can match `WEB_RATE_LIMIT_REJECT` in the deployed environment and only ban after repeated rejects.

Acceptance criteria
-------------------

- A client cannot bypass the application-level web rate limiter by rotating `session_token`.
- Anonymous web requests cannot create unbounded backend sessions or workspace directories.
- Public web mode continues to work without requiring a new external state service.
- Restricted web mode works with configured identity in `core` access control.
- The system continues to function without `fail2ban`, but emits explicit abuse logs when rejecting requests.
- When `fail2ban` is present, repeated abuse events can be escalated to temporary IP bans.
- The abuse-log contract explicitly documents the current `WEB_RATE_LIMIT_REJECT` marker and leaves future session-budget markers reserved rather than implied as already shipped.
- Generic fenced `json` response examples remain visible to the user as plain text.
