export interface WidgetUiArtifact {
  type: string;
  version?: string;
  payload: unknown;
}

export interface WidgetTurnResponse {
  response: string | null;
  source: string;
  session_token?: string;
  disabled?: boolean;
  access_denied?: boolean;
  error?: string;
  ui_artifact?: WidgetUiArtifact | null;
}

export interface WidgetMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
  artifact?: WidgetUiArtifact | null;
  state?: "ready" | "error" | "pending";
}

export interface WidgetTurnRequest {
  message: string;
  session_token?: string;
}
