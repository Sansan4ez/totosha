import { sendChatTurn } from "@/lib/chat-api";
import type { WidgetMessage, WidgetTurnResponse } from "@/lib/types";

const SESSION_STORAGE_KEY = "agent-web-session-token";

export const INITIAL_MESSAGE: WidgetMessage = {
  id: "welcome",
  role: "assistant",
  state: "ready",
  content: "Здравствуйте. Чем могу помочь?",
};

export function createMessage(
  role: WidgetMessage["role"],
  content: string,
  options: Partial<WidgetMessage> = {},
): WidgetMessage {
  return {
    id: options.id || `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    content,
    artifact: options.artifact ?? null,
    state: options.state || "ready",
  };
}

export function buildAssistantMessage(payload: WidgetTurnResponse): WidgetMessage {
  if (payload.disabled) {
    return createMessage(
      "assistant",
      "The web channel is disabled on the server. Enable it before embedding the widget.",
      { state: "error" },
    );
  }

  if (payload.access_denied) {
    return createMessage(
      "assistant",
      "The web channel request was rejected by the core access policy.",
      { state: "error" },
    );
  }

  return createMessage("assistant", payload.response || "(no response)", {
    artifact: payload.ui_artifact || null,
  });
}

export function loadPersistedSessionToken() {
  if (typeof window === "undefined") {
    return undefined;
  }
  return window.sessionStorage.getItem(SESSION_STORAGE_KEY) || undefined;
}

export function persistSessionToken(sessionToken?: string) {
  if (typeof window === "undefined" || !sessionToken) {
    return;
  }
  window.sessionStorage.setItem(SESSION_STORAGE_KEY, sessionToken);
}

export async function requestAssistantReply(
  message: string,
  sessionToken?: string,
  onProgress?: (responseText: string) => void,
  signal?: AbortSignal,
) {
  const payload = await sendChatTurn(
    { message, session_token: sessionToken },
    {
      signal,
      onProgress: (partial) => {
        if (partial.response) {
          onProgress?.(partial.response);
        }
      },
    },
  );
  return {
    message: buildAssistantMessage(payload),
    sessionToken: payload.session_token,
  };
}
