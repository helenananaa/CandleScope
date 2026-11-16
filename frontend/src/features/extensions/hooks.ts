import { useEffect } from "react";
import { bindHostService } from "./state.js";

export function useExtensionService(name: string, value: unknown): void {
  useEffect(() => bindHostService(name, value), [name, value]);
}
