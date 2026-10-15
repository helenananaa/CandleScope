export type AiControlMode = "off" | "read" | "control";
export interface AiControlView { windowId: string; viewId: string; revision: string; kind: "market" | "replay" | "research" }
export interface AiControlStatus {
  mode: AiControlMode; endpoint: string | null; token: string | null; views: AiControlView[];
  audit: { at: string; tool: string; windowId?: string; viewId?: string; outcome: string; elapsedMs: number }[];
}
export interface AiControlRequest {
  type: "request" | "cancel"; requestId: string; name?: string;
  arguments?: { windowId: string; viewId: string; expectedRevision?: string; operationId?: string; interval?: string; chartType?: string; action?: string };
}
export interface AiControlBridge {
  aiControlStatus(): Promise<AiControlStatus>;
  aiControlSetMode(mode: AiControlMode): Promise<AiControlStatus>;
  aiControlPublish(views: Omit<AiControlView, "windowId">[]): Promise<{ ok: boolean }>;
  onAiControlRequest(listener: (request: AiControlRequest) => void): () => void;
  aiControlReply(value: { requestId: string; ok: boolean; result?: Record<string, unknown>; code?: string }): void;
}
