# agent-web

Repo-owned embedded chat widget scaffold for RFC-022.

This app intentionally stops at the frontend shell plus a thin adapter:

- ephemeral browser-visible widget state only;
- bounded server-side anonymous session registry with TTL and per-IP/global budgets;
- minimal chat layout for iframe or popup embedding;
- `/api/web/chat` adapter to `core`;
- explicit structured-artifact renderer boundary for the follow-up schema work.

Out of scope in this scaffold:

- direct OpenAI SDK orchestration;
- sample demo tools, mock business flows, and mock data;
- persisted browser history;
- full structured UI schema and component registry.

## Dependency maintenance

Next.js and `eslint-config-next` are pinned together at 15.5.27. React 18 remains
supported; the Node 22 Docker image satisfies Next.js 15's Node >=18.18 requirement.
The app has no synchronous `cookies()`, `headers()`, or dynamic route parameters
requiring migration to Next.js 15's async request APIs. GET route handlers are no
longer cached by default; the health endpoint intentionally returns a fresh response.
Next.js updated the TypeScript target to ES2017 and generated route type references.

PostCSS is pinned to 8.5.29 with an npm override referencing the direct dependency.
Keep this override: Next.js 15 otherwise installs a vulnerable nested PostCSS even
when the direct dependency is patched. Revalidate the build when changing it.

Verification for this upgrade: `npm ci`, `npm test` (9 passing tests), `npm run build`,
and a local production standalone-server smoke (health, homepage, security headers,
and static JavaScript). `npm audit --omit=dev` reports zero vulnerabilities.
The full audit still reports development-tool findings in the Tailwind/ESLint glob
chain (braces) and esbuild; resolving those requires separate tooling maintenance.
This smoke does not exercise the live reverse proxy or the core chat backend.

## Embedding

The widget contains overscroll at its document and scroll containers to reduce accidental
browser history swipes, while keeping vertical messages and horizontal tables scrollable.
Browser back/forward buttons and mouse side buttons are not intercepted. The embedding
site may also need `overscroll-behavior-x: none` on its own document: an iframe cannot
control the parent page's browser gestures. Verify on the actual browser/device.

Use the widget in an iframe:

```html
<iframe
  src="https://your-agent-web-host:3003/"
  style="width: 100%; height: 100%; min-height: 700px; border: 0"
  allow="clipboard-read; clipboard-write">
</iframe>
```

For the current `lab.llm-studio.ru` deployment there are two supported iframe URLs:

```html
<iframe
  src="https://lab.llm-studio.ru/chatbot/5wEyI3e609HadGKN"
  style="width: 100%; height: 100%; min-height: 700px; border: 0"
  allow="clipboard-read; clipboard-write">
</iframe>
```

```html
<iframe
  src="https://lab.llm-studio.ru/agent-web/"
  style="width: 100%; height: 100%; min-height: 700px; border: 0"
  allow="clipboard-read; clipboard-write">
</iframe>
```

Both URLs are expected to be reverse-proxied to the same `agent-web` instance. Because
the widget is a Next.js app, the proxy must also forward `/_next/*` and `/api/web/*`
to `agent-web`.

## Runtime knobs

- `CORE_API_URL`: internal URL for `core`, defaults to `http://127.0.0.1:4000`
- `AGENT_WEB_RATE_LIMIT_WINDOW_S`: per-IP limiter window in seconds, defaults to `60`
- `AGENT_WEB_RATE_LIMIT_MAX_REQUESTS`: per-IP requests allowed in one window, defaults to `12`
- `AGENT_WEB_SESSION_TTL_S`: anonymous session TTL in seconds, defaults to `900`
- `AGENT_WEB_MAX_ANON_SESSIONS`: global cap for active anonymous widget sessions, defaults to `256`
- `AGENT_WEB_MAX_ANON_SESSIONS_PER_IP`: per-IP cap for active anonymous widget sessions, defaults to `4`
- `AGENT_WEB_USER_ID`: optional fixed core `user_id` for restricted deployments
- `AGENT_WEB_CHAT_ID`: optional fixed core `chat_id` when `AGENT_WEB_USER_ID` is set
- `NEXT_PUBLIC_AGENT_WEB_SSE=0`: force plain JSON transport and disable the SSE wrapper
- `AGENT_WEB_ALLOWED_FRAME_ANCESTORS`: CSP `frame-ancestors` policy, defaults to `'self'`

Rejected requests emit structured abuse markers:

- `WEB_RATE_LIMIT_REJECT`: per-IP request throttling hit; fail2ban can match repeated bursts from one source IP.
- `WEB_SESSION_BUDGET_REJECT`: anonymous session budget exhausted globally or per IP.

`fail2ban` should remain an outer escalation layer. The online limiter still lives in `agent-web`, and `fail2ban` should only consume repeated reject markers from trusted service logs.

## Smoke checklist

- Open the iframe and send a few turns; verify the widget shows progressive text when SSE is enabled.
- Reload the iframe; verify the visible chat history resets to the welcome state.
- Close and reopen the popup or iframe instance; verify no prior turns are shown.
- Open more than `AGENT_WEB_MAX_ANON_SESSIONS_PER_IP` fresh widgets from one IP; verify later opens are rejected early.
- Wait past `AGENT_WEB_SESSION_TTL_S` and reopen; verify a fresh anonymous session can be created again.
- Temporarily disable web access in `core` and verify the widget falls back to a plain text disabled message.
