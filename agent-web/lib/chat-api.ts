import type { WidgetTurnRequest, WidgetTurnResponse } from "@/lib/types";

const CHAT_ENDPOINT =
  process.env.NEXT_PUBLIC_AGENT_WEB_CHAT_ENDPOINT || "/api/web/chat";
const STREAM_ENDPOINT =
  process.env.NEXT_PUBLIC_AGENT_WEB_STREAM_ENDPOINT || "/api/web/chat/stream";
const SSE_ENABLED = process.env.NEXT_PUBLIC_AGENT_WEB_SSE !== "0";

interface SendChatTurnOptions {
  signal?: AbortSignal;
  onProgress?: (payload: Partial<WidgetTurnResponse> & { response?: string | null }) => void;
}

async function sendChatTurnJson(
  request: WidgetTurnRequest,
  signal?: AbortSignal,
): Promise<WidgetTurnResponse> {
  const response = await fetch(CHAT_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    signal,
    cache: "no-store",
  });

  const payload = (await response.json().catch(() => null)) as WidgetTurnResponse | null;

  if (!response.ok) {
    throw new Error(payload?.error || `Chat endpoint returned ${response.status}`);
  }

  if (!payload) {
    throw new Error("Chat endpoint returned an empty payload");
  }

  return payload;
}

function parseSseFrames(buffer: string) {
  const frames = buffer.split("\n\n");
  return {
    complete: frames.slice(0, -1),
    remainder: frames.at(-1) || "",
  };
}

async function sendChatTurnSse(
  request: WidgetTurnRequest,
  options: SendChatTurnOptions,
): Promise<WidgetTurnResponse> {
  const response = await fetch(STREAM_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    signal: options.signal,
    cache: "no-store",
  });

  if (!response.ok || !response.body) {
    throw new Error(`SSE endpoint returned ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sessionToken = request.session_token;
  let responseText = "";
  let artifact: WidgetTurnResponse["ui_artifact"] = null;
  let terminalPayload: WidgetTurnResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const { complete, remainder } = parseSseFrames(buffer);
    buffer = remainder;

    for (const frame of complete) {
      const eventLine = frame
        .split("\n")
        .find((line) => line.startsWith("event:"));
      const dataLine = frame
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!eventLine || !dataLine) {
        continue;
      }

      const event = eventLine.replace("event:", "").trim();
      const data = JSON.parse(dataLine.replace("data:", "").trim());

      if (event == "session" && data.session_token) {
        sessionToken = data.session_token;
      } else if (event == "chunk") {
        responseText = data.response || responseText;
        options.onProgress?.({
          response: responseText,
          session_token: sessionToken,
        });
      } else if (event == "artifact") {
        artifact = data.ui_artifact || artifact;
        options.onProgress?.({
          response: responseText,
          session_token: sessionToken,
          ui_artifact: artifact,
        });
      } else if (event == "done") {
        terminalPayload = data as WidgetTurnResponse;
      } else if (event == "error") {
        throw new Error(data.error || "SSE transport failed.");
      }
    }
  }

  if (!terminalPayload) {
    throw new Error("SSE stream ended without a terminal payload.");
  }

  return {
    ...terminalPayload,
    response: terminalPayload.response ?? responseText,
    session_token: terminalPayload.session_token || sessionToken,
    ui_artifact: terminalPayload.ui_artifact ?? artifact ?? null,
  };
}

export async function sendChatTurn(
  request: WidgetTurnRequest,
  options: SendChatTurnOptions = {},
): Promise<WidgetTurnResponse> {
  if (SSE_ENABLED) {
    try {
      return await sendChatTurnSse(request, options);
    } catch {
      return sendChatTurnJson(request, options.signal);
    }
  }
  return sendChatTurnJson(request, options.signal);
}
