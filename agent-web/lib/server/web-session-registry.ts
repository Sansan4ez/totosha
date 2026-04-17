import { isSessionToken, mintSessionToken, resolveSyntheticIds } from "./session-ids";
import { resolveTrustedClientIp } from "./rate-limit";

const DEFAULT_SESSION_TTL_S = 900;
const DEFAULT_MAX_ANON_SESSIONS = 256;
const DEFAULT_MAX_ANON_SESSIONS_PER_IP = 4;

type AnonymousSessionEntry = {
  sessionToken: string;
  clientIp: string;
  userId: number;
  chatId: number;
  createdAtMs: number;
  lastSeenAtMs: number;
  expiresAtMs: number;
};

export interface AnonymousSessionResult {
  ok: boolean;
  status: number;
  clientIp: string;
  sessionToken?: string;
  userId?: number;
  chatId?: number;
  error?: string;
}

const sessionsByToken = new Map<string, AnonymousSessionEntry>();

function readPositiveIntEnv(name: string, fallback: number) {
  const rawValue = process.env[name];
  if (!rawValue) {
    return fallback;
  }

  const parsedValue = Number.parseInt(rawValue, 10);
  return Number.isSafeInteger(parsedValue) && parsedValue > 0 ? parsedValue : fallback;
}

const SESSION_TTL_S = readPositiveIntEnv("AGENT_WEB_SESSION_TTL_S", DEFAULT_SESSION_TTL_S);
const SESSION_TTL_MS = SESSION_TTL_S * 1_000;
const MAX_ANON_SESSIONS = readPositiveIntEnv(
  "AGENT_WEB_MAX_ANON_SESSIONS",
  DEFAULT_MAX_ANON_SESSIONS,
);
const MAX_ANON_SESSIONS_PER_IP = readPositiveIntEnv(
  "AGENT_WEB_MAX_ANON_SESSIONS_PER_IP",
  DEFAULT_MAX_ANON_SESSIONS_PER_IP,
);

function countSessionsForIp(clientIp: string) {
  let total = 0;
  for (const entry of Array.from(sessionsByToken.values())) {
    if (entry.clientIp === clientIp) {
      total += 1;
    }
  }
  return total;
}

function logBudgetReject(
  clientIp: string,
  reason: "global_cap" | "per_ip_cap",
  extra: Record<string, number>,
) {
  console.warn(
    JSON.stringify({
      event: "WEB_SESSION_BUDGET_REJECT",
      abuse_marker: "WEB_SESSION_BUDGET_REJECT",
      ip: clientIp,
      reason,
      ttl_s: SESSION_TTL_S,
      max_anon_sessions: MAX_ANON_SESSIONS,
      max_anon_sessions_per_ip: MAX_ANON_SESSIONS_PER_IP,
      ...extra,
    }),
  );
}

export function drainExpiredAnonymousSessions(nowMs = Date.now()) {
  const expired: AnonymousSessionEntry[] = [];
  for (const [sessionToken, entry] of Array.from(sessionsByToken.entries())) {
    if (entry.expiresAtMs > nowMs) {
      continue;
    }
    sessionsByToken.delete(sessionToken);
    expired.push(entry);
  }
  return expired;
}

export function resolveAnonymousSession(
  request: Request,
  requestedSessionToken?: string,
  nowMs = Date.now(),
): AnonymousSessionResult {
  const clientIp = resolveTrustedClientIp(request);
  drainExpiredAnonymousSessions(nowMs);

  const normalizedSessionToken = isSessionToken(requestedSessionToken)
    ? requestedSessionToken
    : undefined;

  if (normalizedSessionToken) {
    const existing = sessionsByToken.get(normalizedSessionToken);
    if (existing) {
      existing.lastSeenAtMs = nowMs;
      existing.expiresAtMs = nowMs + SESSION_TTL_MS;
      return {
        ok: true,
        status: 200,
        clientIp,
        sessionToken: existing.sessionToken,
        userId: existing.userId,
        chatId: existing.chatId,
      };
    }
  }

  if (sessionsByToken.size >= MAX_ANON_SESSIONS) {
    logBudgetReject(clientIp, "global_cap", {
      active_sessions: sessionsByToken.size,
    });
    return {
      ok: false,
      status: 429,
      clientIp,
      error: "Anonymous web session budget is exhausted. Retry after active sessions expire.",
    };
  }

  const sessionsForIp = countSessionsForIp(clientIp);
  if (sessionsForIp >= MAX_ANON_SESSIONS_PER_IP) {
    logBudgetReject(clientIp, "per_ip_cap", {
      active_sessions_for_ip: sessionsForIp,
    });
    return {
      ok: false,
      status: 429,
      clientIp,
      error: "Too many active anonymous web sessions from this IP. Retry after existing sessions expire.",
    };
  }

  const sessionToken = mintSessionToken();
  const ids = resolveSyntheticIds(sessionToken);
  sessionsByToken.set(sessionToken, {
    sessionToken,
    clientIp,
    userId: ids.userId,
    chatId: ids.chatId,
    createdAtMs: nowMs,
    lastSeenAtMs: nowMs,
    expiresAtMs: nowMs + SESSION_TTL_MS,
  });

  return {
    ok: true,
    status: 200,
    clientIp,
    sessionToken,
    userId: ids.userId,
    chatId: ids.chatId,
  };
}

export function resetAnonymousSessionRegistryForTests() {
  sessionsByToken.clear();
}

export function getAnonymousSessionRegistrySnapshotForTests() {
  return Array.from(sessionsByToken.values()).map((entry) => ({ ...entry }));
}
