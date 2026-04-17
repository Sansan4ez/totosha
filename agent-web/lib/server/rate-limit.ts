import { isIP } from "node:net";

const DEFAULT_WINDOW_S = 60;
const DEFAULT_MAX_REQUESTS = 12;

function readPositiveIntEnv(name: string, fallback: number) {
  const rawValue = process.env[name];
  if (!rawValue) {
    return fallback;
  }

  const parsedValue = Number.parseInt(rawValue, 10);
  return Number.isSafeInteger(parsedValue) && parsedValue > 0 ? parsedValue : fallback;
}

const WINDOW_S = readPositiveIntEnv("AGENT_WEB_RATE_LIMIT_WINDOW_S", DEFAULT_WINDOW_S);
const WINDOW_MS = WINDOW_S * 1_000;
const MAX_REQUESTS_PER_WINDOW = readPositiveIntEnv(
  "AGENT_WEB_RATE_LIMIT_MAX_REQUESTS",
  DEFAULT_MAX_REQUESTS,
);

type BucketEntry = {
  timestamps: number[];
};

export interface RateLimitResult {
  allowed: boolean;
  clientIp: string;
  limit: number;
  retryAfterSeconds: number;
  windowSeconds: number;
}

const buckets = new Map<string, BucketEntry>();

function compact(entry: BucketEntry, now: number) {
  entry.timestamps = entry.timestamps.filter((timestamp) => now - timestamp < WINDOW_MS);
}

function normalizeIpCandidate(value: string) {
  const trimmed = value.trim();
  if (!trimmed || trimmed.toLowerCase() === "unknown") {
    return null;
  }

  if (trimmed.startsWith("[") && trimmed.includes("]")) {
    const endIndex = trimmed.indexOf("]");
    const bracketedIp = trimmed.slice(1, endIndex);
    return isIP(bracketedIp) ? bracketedIp : null;
  }

  if (isIP(trimmed)) {
    return trimmed;
  }

  if (trimmed.includes(".") && trimmed.includes(":")) {
    const lastColonIndex = trimmed.lastIndexOf(":");
    const withoutPort = trimmed.slice(0, lastColonIndex);
    return isIP(withoutPort) ? withoutPort : null;
  }

  return null;
}

export function resolveTrustedClientIp(request: Request) {
  const forwardedFor = request.headers.get("x-forwarded-for") || "";
  for (const candidate of forwardedFor.split(",")) {
    const normalized = normalizeIpCandidate(candidate);
    if (normalized) {
      return normalized;
    }
  }

  const directHeaders = ["x-real-ip", "cf-connecting-ip"];
  for (const headerName of directHeaders) {
    const headerValue = request.headers.get(headerName);
    if (!headerValue) {
      continue;
    }

    const normalized = normalizeIpCandidate(headerValue);
    if (normalized) {
      return normalized;
    }
  }

  return "unknown";
}

export function rateLimitKey(request: Request) {
  return resolveTrustedClientIp(request);
}

function retryAfterSeconds(entry: BucketEntry, now: number) {
  const oldestTimestamp = entry.timestamps[0];
  if (!oldestTimestamp) {
    return WINDOW_S;
  }

  return Math.max(1, Math.ceil((WINDOW_MS - (now - oldestTimestamp)) / 1_000));
}

function requestPath(request: Request) {
  try {
    return new URL(request.url).pathname;
  } catch {
    return "unknown";
  }
}

function logRateLimitReject(request: Request, clientIp: string, entry: BucketEntry, now: number) {
  console.warn(
    JSON.stringify({
      event: "WEB_RATE_LIMIT_REJECT",
      abuse_marker: "WEB_RATE_LIMIT_REJECT",
      ip: clientIp,
      method: request.method,
      path: requestPath(request),
      window_s: WINDOW_S,
      max_requests: MAX_REQUESTS_PER_WINDOW,
      seen_requests: entry.timestamps.length,
      retry_after_s: retryAfterSeconds(entry, now),
    }),
  );
}

export function assertRateLimit(request: Request): RateLimitResult {
  const now = Date.now();
  const key = rateLimitKey(request);
  const entry = buckets.get(key) || { timestamps: [] };
  compact(entry, now);
  if (entry.timestamps.length >= MAX_REQUESTS_PER_WINDOW) {
    buckets.set(key, entry);
    logRateLimitReject(request, key, entry, now);
    return {
      allowed: false,
      clientIp: key,
      limit: MAX_REQUESTS_PER_WINDOW,
      retryAfterSeconds: retryAfterSeconds(entry, now),
      windowSeconds: WINDOW_S,
    };
  }

  entry.timestamps.push(now);
  buckets.set(key, entry);

  if (buckets.size > 2048) {
    for (const [bucketKey, bucketEntry] of Array.from(buckets.entries())) {
      compact(bucketEntry, now);
      if (!bucketEntry.timestamps.length) {
        buckets.delete(bucketKey);
      }
    }
  }

  return {
    allowed: true,
    clientIp: key,
    limit: MAX_REQUESTS_PER_WINDOW,
    retryAfterSeconds: 0,
    windowSeconds: WINDOW_S,
  };
}

export function resetRateLimitBucketsForTests() {
  buckets.clear();
}
