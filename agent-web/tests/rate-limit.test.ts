import assert from "node:assert/strict";
import test from "node:test";

import { assertRateLimit, resetRateLimitBucketsForTests } from "../lib/server/rate-limit";

function makeRequest(ip: string, sessionToken?: string) {
  return new Request("http://widget.test/api/web/chat", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": ip,
    },
    body: JSON.stringify({
      message: "hello",
      session_token: sessionToken,
    }),
  });
}

test.beforeEach(() => {
  resetRateLimitBucketsForTests();
});

test("rotating session tokens does not bypass the per-ip limiter", () => {
  for (let index = 0; index < 12; index += 1) {
    const result = assertRateLimit(makeRequest("203.0.113.10", `aw_token_${index}`));
    assert.equal(result.allowed, true);
  }

  const rejected = assertRateLimit(makeRequest("203.0.113.10", "aw_final"));
  assert.equal(rejected.allowed, false);
  assert.equal(rejected.clientIp, "203.0.113.10");
  assert.match(String(rejected.retryAfterSeconds), /^[1-9]/);
});

test("different ips use independent limiter buckets", () => {
  for (let index = 0; index < 12; index += 1) {
    assert.equal(assertRateLimit(makeRequest("198.51.100.4")).allowed, true);
  }

  assert.equal(assertRateLimit(makeRequest("198.51.100.4")).allowed, false);
  assert.equal(assertRateLimit(makeRequest("198.51.100.5")).allowed, true);
});
