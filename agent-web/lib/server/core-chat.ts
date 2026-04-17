import { isSessionToken, mintSessionToken } from "@/lib/server/session-ids";
import {
  drainExpiredAnonymousSessions,
  resolveAnonymousSession,
} from "@/lib/server/web-session-registry";
import { z } from "zod";

export const webChatRequestSchema = z.object({
  message: z.string().trim().min(1).max(4000),
  session_token: z.string().optional(),
});

const coreResponseSchema = z.object({
  response: z.string().nullable(),
  source: z.string().optional(),
  ui_artifact: z.unknown().nullable().optional(),
  disabled: z.boolean().optional(),
  access_denied: z.boolean().optional(),
  error: z.string().optional(),
});

export interface WebChatDispatchResult {
  status: number;
  payload: {
    response: string | null;
    source: "web";
    session_token?: string;
    disabled?: boolean;
    access_denied?: boolean;
    error?: string;
    ui_artifact: unknown | null;
  };
}

function getCoreUrl() {
  return process.env.CORE_API_URL || "http://127.0.0.1:4000";
}

function resolveConfiguredWebIdentity() {
  const configuredUserId = Number.parseInt(process.env.AGENT_WEB_USER_ID || "", 10);
  if (!Number.isSafeInteger(configuredUserId) || configuredUserId <= 0) {
    return null;
  }

  const configuredChatId = Number.parseInt(
    process.env.AGENT_WEB_CHAT_ID || String(configuredUserId),
    10,
  );

  if (!Number.isSafeInteger(configuredChatId) || configuredChatId <= 0) {
    return null;
  }

  return {
    userId: configuredUserId,
    chatId: configuredChatId,
  };
}

async function reclaimCoreWebSession(userId: number, chatId: number) {
  try {
    const response = await fetch(`${getCoreUrl()}/api/web/session/reclaim`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: userId,
        chat_id: chatId,
      }),
      cache: "no-store",
    });

    if (!response.ok) {
      console.warn(
        JSON.stringify({
          event: "WEB_SESSION_RECLAIM_FAILED",
          user_id: userId,
          chat_id: chatId,
          status: response.status,
        }),
      );
    }
  } catch (error) {
    console.warn(
      JSON.stringify({
        event: "WEB_SESSION_RECLAIM_FAILED",
        user_id: userId,
        chat_id: chatId,
        error: error instanceof Error ? error.message : "unknown",
      }),
    );
  }
}

async function reclaimExpiredAnonymousSessions() {
  const expired = drainExpiredAnonymousSessions();
  await Promise.all(expired.map((entry) => reclaimCoreWebSession(entry.userId, entry.chatId)));
}

export async function dispatchWebChatTurn(
  request: Request,
  input: z.infer<typeof webChatRequestSchema>,
): Promise<WebChatDispatchResult> {
  await reclaimExpiredAnonymousSessions();

  const configuredIdentity = resolveConfiguredWebIdentity();
  let resolvedIds: { userId: number; chatId: number };
  let resolvedSessionToken: string | undefined;

  if (configuredIdentity) {
    resolvedIds = configuredIdentity;
    resolvedSessionToken = isSessionToken(input.session_token)
      ? input.session_token
      : mintSessionToken();
  } else {
    const anonymousSession = resolveAnonymousSession(request, input.session_token);
    if (!anonymousSession.ok) {
      return {
        status: anonymousSession.status,
        payload: {
          response: null,
          source: "web",
          error: anonymousSession.error,
          ui_artifact: null,
        },
      };
    }

    resolvedIds = {
      userId: anonymousSession.userId as number,
      chatId: anonymousSession.chatId as number,
    };
    resolvedSessionToken = anonymousSession.sessionToken;
  }

  try {
    const coreResponse = await fetch(`${getCoreUrl()}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: resolvedIds.userId,
        chat_id: resolvedIds.chatId,
        message: input.message,
        username: "",
        chat_type: "private",
        source: "web",
      }),
      cache: "no-store",
    });

    const corePayload = coreResponseSchema.safeParse(await coreResponse.json().catch(() => null));
    if (!coreResponse.ok || !corePayload.success) {
      return {
        status: 502,
        payload: {
          response: null,
          source: "web",
          session_token: resolvedSessionToken,
          error: "Core returned an invalid adapter response.",
          ui_artifact: null,
        },
      };
    }

    return {
      status: 200,
      payload: {
        response: corePayload.data.response,
        source: "web",
        session_token: resolvedSessionToken,
        disabled: corePayload.data.disabled ?? false,
        access_denied: corePayload.data.access_denied ?? false,
        error: corePayload.data.error,
        ui_artifact: corePayload.data.ui_artifact ?? null,
      },
    };
  } catch (error) {
    return {
      status: 502,
      payload: {
        response: null,
        source: "web",
        session_token: resolvedSessionToken,
        error: error instanceof Error ? error.message : "Failed to reach core adapter target.",
        ui_artifact: null,
      },
    };
  }
}
