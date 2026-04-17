"use client";

import Message from "@/components/message";
import type { WidgetMessage } from "@/lib/types";

interface ChatProps {
  items: WidgetMessage[];
  pending: boolean;
  input: string;
  onInputChange: (value: string) => void;
  onSendMessage: () => void;
}

export default function Chat({
  items,
  pending,
  input,
  onInputChange,
  onSendMessage,
}: ChatProps) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
        {items.map((item) => (
          <Message key={item.id} message={item} />
        ))}
      </div>
      <div className="border-t border-border/80 bg-white/85 px-4 py-4 backdrop-blur sm:px-6">
        <div className="rounded-[1.35rem] border border-border bg-white shadow-sm">
          <textarea
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSendMessage();
              }
            }}
            rows={1}
            placeholder="Send a message"
            className="min-h-[3.5rem] w-full resize-none rounded-[1.35rem] bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-between border-t border-border/70 px-4 py-3">
            <p className="text-xs text-muted-foreground">
              Embedded widget shell. History lives only in this page instance.
            </p>
            <button
              type="button"
              disabled={pending || !input.trim()}
              onClick={onSendMessage}
              className="rounded-full bg-brand px-4 py-2 text-sm font-medium text-brand-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {pending ? "Sending..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
