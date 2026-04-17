"use client";

import ArtifactPanel from "@/components/artifact-panel";
import type { WidgetMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface MessageProps {
  message: WidgetMessage;
}

export default function Message({ message }: MessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div className={cn("max-w-[88%] space-y-2", isUser ? "items-end" : "items-start")}>
        <div className="px-1 text-[11px] font-medium uppercase tracking-[0.22em] text-muted-foreground">
          {isUser ? "You" : message.state === "pending" ? "Thinking" : "Agent"}
        </div>
        <div
          className={cn(
            "rounded-[1.35rem] px-4 py-3 text-sm leading-6 shadow-sm",
            isUser
              ? "bg-brand text-brand-foreground"
              : message.state === "error"
                ? "border border-rose-300 bg-rose-50 text-rose-950"
                : "border border-white/80 bg-white/95 text-foreground",
          )}
        >
          <div className="whitespace-pre-wrap">{message.content}</div>
          {!isUser && message.artifact ? <ArtifactPanel artifact={message.artifact} /> : null}
        </div>
      </div>
    </div>
  );
}
