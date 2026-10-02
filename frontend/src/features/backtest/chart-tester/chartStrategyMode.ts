export function resolveStrategyTesterMode(saved: unknown, hasAttachment: boolean): "NATIVE" | "CANDLESCOPE" {
  return saved === "NATIVE" || saved === "CANDLESCOPE" ? saved : hasAttachment ? "CANDLESCOPE" : "NATIVE";
}
