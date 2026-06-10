"use client";

import Chat from "@/components/chat";
import {
  INITIAL_MESSAGE,
  createMessage,
  loadPersistedSessionToken,
  persistSessionToken,
  requestAssistantReply,
} from "@/lib/assistant";
import type { WidgetMessage } from "@/lib/types";
import { useEffect, useRef, useState } from "react";

export default function Assistant() {
  const [messages, setMessages] = useState<WidgetMessage[]>([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [sessionToken, setSessionToken] = useState<string | undefined>();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setSessionToken(loadPersistedSessionToken());
  }, []);

  async function handleSendMessage() {
    const trimmed = input.trim();
    if (!trimmed || pending) {
      return;
    }

    const userMessage = createMessage("user", trimmed);
    const thinkingMessage = createMessage("assistant", "Думаю...", {
      id: `pending-${Date.now()}`,
      state: "pending",
    });

    abortRef.current?.abort();
    abortRef.current = new AbortController();
    setPending(true);
    setInput("");
    setMessages((current) => [...current, userMessage, thinkingMessage]);

    try {
      const reply = await requestAssistantReply(
        trimmed,
        sessionToken,
        (partialResponse) => {
          setMessages((current) => [
            ...current.slice(0, -1),
            {
              ...thinkingMessage,
              content: partialResponse,
            },
          ]);
        },
        abortRef.current.signal,
      );
      setSessionToken(reply.sessionToken);
      persistSessionToken(reply.sessionToken);
      setMessages((current) => [
        ...current.slice(0, -1),
        {
          ...reply.message,
          id: thinkingMessage.id,
        },
      ]);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to reach the web adapter.";
      setMessages((current) => [
        ...current.slice(0, -1),
        createMessage("assistant", message, {
          id: thinkingMessage.id,
          state: "error",
        }),
      ]);
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="h-full overflow-hidden rounded-[2rem] border border-white/70 bg-white/80 shadow-[0_24px_80px_rgba(31,56,88,0.18)] backdrop-blur">
      <div className="h-full bg-[linear-gradient(180deg,rgba(245,248,251,0.55),rgba(255,255,255,0.88))]">
        <Chat
          items={messages}
          pending={pending}
          input={input}
          onInputChange={setInput}
          onSendMessage={handleSendMessage}
        />
      </div>
    </section>
  );
}
