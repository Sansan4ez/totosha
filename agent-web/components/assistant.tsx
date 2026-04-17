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
import { useEffect, useMemo, useRef, useState } from "react";

export default function Assistant() {
  const [messages, setMessages] = useState<WidgetMessage[]>([INITIAL_MESSAGE]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [sessionToken, setSessionToken] = useState<string | undefined>();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    setSessionToken(loadPersistedSessionToken());
  }, []);

  const stats = useMemo(() => {
    const userTurns = messages.filter((item) => item.role === "user").length;
    return `${userTurns} turn${userTurns === 1 ? "" : "s"} in this ephemeral session`;
  }, [messages]);

  async function handleSendMessage() {
    const trimmed = input.trim();
    if (!trimmed || pending) {
      return;
    }

    const userMessage = createMessage("user", trimmed);
    const thinkingMessage = createMessage("assistant", "Waiting for the web adapter response...", {
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
    <section className="overflow-hidden rounded-[2rem] border border-white/70 bg-white/80 shadow-[0_24px_80px_rgba(31,56,88,0.18)] backdrop-blur">
      <div className="border-b border-border/80 bg-[linear-gradient(120deg,rgba(7,93,105,0.96),rgba(16,132,120,0.88))] px-4 py-5 text-white sm:px-6">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <p className="text-[11px] uppercase tracking-[0.28em] text-white/70">
              LocalTopSH Agent Web
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">
              Embedded widget scaffold
            </h1>
            <p className="max-w-2xl text-sm text-white/78">
              Forked from the OpenAI conversational-assistant shape, but reduced
              to a repo-owned shell with a typed transport boundary and no direct
              model orchestration in the browser.
            </p>
          </div>
          <div className="rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-white/80">
            {stats}
          </div>
        </div>
      </div>
      <div className="h-[calc(100vh-12rem)] min-h-[38rem] bg-[linear-gradient(180deg,rgba(245,248,251,0.55),rgba(255,255,255,0.88))]">
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
