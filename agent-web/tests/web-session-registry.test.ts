import assert from "node:assert/strict";
import test from "node:test";

import {
  getAnonymousSessionRegistrySnapshotForTests,
  resetAnonymousSessionRegistryForTests,
  resolveAnonymousSession,
} from "../lib/server/web-session-registry";

function makeRequest(ip: string) {
  return new Request("http://widget.test/api/web/chat", {
    method: "POST",
    headers: {
      "x-forwarded-for": ip,
    },
  });
}

test.beforeEach(() => {
  resetAnonymousSessionRegistryForTests();
});

test("anonymous sessions are capped per ip but reusable with a server-issued token", () => {
  const request = makeRequest("203.0.113.20");
  const issuedTokens: string[] = [];

  for (let index = 0; index < 4; index += 1) {
    const result = resolveAnonymousSession(request, undefined, 1_000 + index);
    assert.equal(result.ok, true);
    issuedTokens.push(result.sessionToken as string);
  }

  const rejected = resolveAnonymousSession(request, undefined, 2_000);
  assert.equal(rejected.ok, false);
  assert.equal(rejected.status, 429);

  const reused = resolveAnonymousSession(request, issuedTokens[0], 3_000);
  assert.equal(reused.ok, true);
  assert.equal(reused.sessionToken, issuedTokens[0]);
  assert.equal(getAnonymousSessionRegistrySnapshotForTests().length, 4);
});

test("expired anonymous sessions free capacity for new widget opens", () => {
  const request = makeRequest("198.51.100.12");
  const created = resolveAnonymousSession(request, undefined, 10_000);
  assert.equal(created.ok, true);

  const [entry] = getAnonymousSessionRegistrySnapshotForTests();
  assert.ok(entry);

  const renewed = resolveAnonymousSession(request, undefined, entry.expiresAtMs + 1);
  assert.equal(renewed.ok, true);
  assert.notEqual(renewed.sessionToken, created.sessionToken);
  assert.equal(getAnonymousSessionRegistrySnapshotForTests().length, 1);
});
