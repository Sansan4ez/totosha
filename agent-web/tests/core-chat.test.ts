import assert from "node:assert/strict";
import test from "node:test";

import { dispatchWebChatTurn } from "../lib/server/core-chat";
import { resetAnonymousSessionRegistryForTests } from "../lib/server/web-session-registry";

const originalFetch = global.fetch;
const originalEnv = {
  AGENT_WEB_USER_ID: process.env.AGENT_WEB_USER_ID,
  AGENT_WEB_CHAT_ID: process.env.AGENT_WEB_CHAT_ID,
  CORE_API_URL: process.env.CORE_API_URL,
};

test.beforeEach(() => {
  resetAnonymousSessionRegistryForTests();
  process.env.AGENT_WEB_USER_ID = originalEnv.AGENT_WEB_USER_ID;
  process.env.AGENT_WEB_CHAT_ID = originalEnv.AGENT_WEB_CHAT_ID;
  process.env.CORE_API_URL = "http://core.test";
});

test.afterEach(() => {
  global.fetch = originalFetch;
});

test("configured web identity is forwarded to core for restricted deployments", async () => {
  process.env.AGENT_WEB_USER_ID = "42";
  process.env.AGENT_WEB_CHAT_ID = "84";

  const fetchCalls: Array<{ url: string; body?: Record<string, unknown> }> = [];
  global.fetch = async (input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    fetchCalls.push({ url, body });
    if (url.endsWith("/api/chat")) {
      return new Response(JSON.stringify({ response: "ok", source: "web" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ status: "ok", reclaimed: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const result = await dispatchWebChatTurn(
    new Request("http://widget.test/api/web/chat", {
      method: "POST",
      headers: { "x-forwarded-for": "203.0.113.30" },
    }),
    { message: "hello", session_token: undefined },
  );

  const coreCall = fetchCalls.find((entry) => entry.url.endsWith("/api/chat"));
  assert.ok(coreCall);
  assert.equal(coreCall?.body?.user_id, 42);
  assert.equal(coreCall?.body?.chat_id, 84);
  assert.equal(result.payload.response, "ok");
  assert.match(result.payload.session_token || "", /^aw_/);
});
