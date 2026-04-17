import { dispatchWebChatTurn, webChatRequestSchema } from "@/lib/server/core-chat";
import { assertRateLimit } from "@/lib/server/rate-limit";

const encoder = new TextEncoder();

function emitEvent(event: string, data: unknown) {
  return encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function splitResponse(text: string) {
  const parts = text.match(/.{1,36}(\s+|$)/g) || [text];
  return parts.map((part) => part.trim()).filter(Boolean);
}

export async function POST(request: Request) {
  const rateLimit = assertRateLimit(request);
  if (!rateLimit.allowed) {
    return new Response(
      emitEvent("error", {
        response: null,
        source: "web",
        error: "Rate limit exceeded for the embedded web channel.",
      }),
      {
        status: 429,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
          "Retry-After": String(rateLimit.retryAfterSeconds),
        },
      },
    );
  }

  const parsedBody = webChatRequestSchema.safeParse(await request.json().catch(() => null));
  if (!parsedBody.success) {
    return new Response(
      emitEvent("error", {
        response: null,
        source: "web",
        error: "Invalid web chat request payload.",
      }),
      {
        status: 400,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
        },
      },
    );
  }

  const result = await dispatchWebChatTurn(request, parsedBody.data);
  const headers = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
  };

  const stream = new ReadableStream({
    async start(controller) {
      controller.enqueue(
        emitEvent("session", {
          session_token: result.payload.session_token,
        }),
      );

      const responseText = result.payload.response || "";
      if (responseText) {
        let accumulated = "";
        for (const part of splitResponse(responseText)) {
          accumulated = accumulated ? `${accumulated} ${part}` : part;
          controller.enqueue(
            emitEvent("chunk", {
              delta: part,
              response: accumulated,
            }),
          );
          await new Promise((resolve) => setTimeout(resolve, 12));
        }
      }

      if (result.payload.ui_artifact) {
        controller.enqueue(
          emitEvent("artifact", {
            ui_artifact: result.payload.ui_artifact,
          }),
        );
      }

      controller.enqueue(emitEvent("done", result.payload));
      controller.close();
    },
  });

  return new Response(stream, {
    status: result.status,
    headers,
  });
}
