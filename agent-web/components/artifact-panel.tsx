"use client";

import UiArtifactRenderer from "@/components/ui-artifact-renderer";
import { parseComponentTreeArtifact } from "@/lib/ui-artifacts";
import type { WidgetUiArtifact } from "@/lib/types";

interface ArtifactPanelProps {
  artifact: WidgetUiArtifact;
}

export default function ArtifactPanel({ artifact }: ArtifactPanelProps) {
  const parsed = parseComponentTreeArtifact(artifact);

  if (parsed.success) {
    return (
      <div className="mt-3">
        <UiArtifactRenderer artifact={parsed.data} />
      </div>
    );
  }

  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-dashed border-border bg-muted/70">
      <div className="border-b border-border/80 px-4 py-2 text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
        Unsupported artifact
      </div>
      <div className="space-y-2 px-4 py-3">
        <p className="text-sm font-medium text-foreground">
          Artifact payload did not match the allowed widget schema.
        </p>
        <div className="rounded-xl bg-white px-3 py-3 text-xs text-muted-foreground">
          <p className="font-mono text-foreground">{artifact.type}</p>
          <p className="mt-2">Validation errors are intentionally hidden from the model-facing UI.</p>
        </div>
      </div>
    </div>
  );
}
