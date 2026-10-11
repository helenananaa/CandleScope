import { useEffect, useState } from "react";
import { nativeApi, type NativeCapabilities } from "./nativeBacktestApi.js";

export type NativeAvailability = "loading" | "available" | "unavailable" | "error";
export function nativeAvailability(capabilities: NativeCapabilities): NativeAvailability {
  return capabilities.engines.some((engine) => engine.available) ? "available" : "unavailable";
}

export function resolveAvailableStrategyMode(
  requested: "NATIVE" | "CANDLESCOPE", availability: NativeAvailability, explicitlyChosen = false,
): "NATIVE" | "CANDLESCOPE" {
  return explicitlyChosen || availability === "available" ? requested : "CANDLESCOPE";
}

export function useNativeAvailability(): NativeAvailability {
  const [availability, setAvailability] = useState<NativeAvailability>("loading");
  useEffect(() => {
    const controller = new AbortController();
    void nativeApi<NativeCapabilities>("/native/capabilities", undefined, undefined, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setAvailability(nativeAvailability(value)); })
      .catch(() => { if (!controller.signal.aborted) setAvailability("error"); });
    return () => controller.abort();
  }, []);
  return availability;
}
