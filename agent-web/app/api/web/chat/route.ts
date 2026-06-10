import { dispatchWebChatTurn, webChatRequestSchema } from "@/lib/server/core-chat";
import { assertRateLimit } from "@/lib/server/rate-limit";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const rateLimit = assertRateLimit(request);
  if (!rateLimit.allowed) {
    return NextResponse.json(
      {
        response: null,
        source: "web",
        error: "Rate limit exceeded for the embedded web channel.",
        ui_artifact: null,
      },
      {
        status: 429,
        headers: {
          "Retry-After": String(rateLimit.retryAfterSeconds),
        },
      },
    );
  }

  const parsedBody = webChatRequestSchema.safeParse(await request.json().catch(() => null));
  if (!parsedBody.success) {
    return NextResponse.json(
      {
        response: null,
        source: "web",
        error: "Invalid web chat request payload.",
        ui_artifact: null,
      },
      { status: 400 },
    );
  }

  const result = await dispatchWebChatTurn(request, parsedBody.data);
  return NextResponse.json(result.payload, { status: result.status });
}
