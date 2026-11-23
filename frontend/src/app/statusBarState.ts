export type ConnectionStatus = "connected" | "loading" | "disconnected" | string;

export interface StatusBarConnectionInput {
  connectionStatus: ConnectionStatus;
  historyOnly?: boolean;
  wsStatus?: string;
}

/** Status-bar dot state; an exchange outage reads as disconnected, not waiting. */
export function statusBarConnectionState(status: StatusBarConnectionInput): ConnectionStatus {
  if (status.historyOnly || status.wsStatus === "offline") return "disconnected";
  if (status.connectionStatus === "connected" && status.wsStatus && status.wsStatus !== "live") {
    return status.wsStatus === "disconnected" ? "disconnected" : "loading";
  }
  return status.connectionStatus;
}
