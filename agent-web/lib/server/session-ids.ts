import { createHash, randomUUID } from "crypto";

const SESSION_TOKEN_PREFIX = "aw_";
const SESSION_ID_OFFSET = 1_000_000_000_000;
const SESSION_ID_RANGE = 8_000_000_000_000;

export function mintSessionToken() {
  return `${SESSION_TOKEN_PREFIX}${randomUUID().replace(/-/g, "")}`;
}

export function isSessionToken(value: unknown): value is string {
  return typeof value === "string" && value.startsWith(SESSION_TOKEN_PREFIX) && value.length >= 20;
}

function stablePositiveInt(namespace: string, token: string) {
  const digest = createHash("sha256")
    .update(`agent-web:${namespace}:${token}`)
    .digest("hex");
  const slice = Number.parseInt(digest.slice(0, 13), 16);
  return SESSION_ID_OFFSET + (slice % SESSION_ID_RANGE);
}

export function resolveSyntheticIds(token: string) {
  return {
    userId: stablePositiveInt("user", token),
    chatId: stablePositiveInt("chat", token),
  };
}
