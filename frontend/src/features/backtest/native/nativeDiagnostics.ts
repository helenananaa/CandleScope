import type { NativeRun } from "./nativeBacktestApi.js";

export type NativeFeedbackStatus = ReturnType<typeof nativeRunFeedback>["status"];

/** Feedback belongs to the selected history entry, while commands keep their current-run state. */
export function nativeRunFeedback(input: {
  current: NativeRun | null;
  historical: NativeRun | null;
  error: string;
  busy: boolean;
  preparationState?: string | undefined;
  needsData: boolean;
}) {
  const selected = input.historical ?? input.current;
  const operationError = input.historical ? "" : input.error;
  const errorDetails = operationError || (selected?.error
    ? `${selected.error.message}\n${JSON.stringify(selected.error.details ?? {}, null, 2)}` : "");
  const status = selected?.state === "CANCELLED" || (!input.historical && input.preparationState === "CANCELLED") ? "cancelled"
    : operationError || selected?.state === "FAILED" || selected?.state === "INTERRUPTED" ? "failed"
      : input.historical ? selected?.state === "COMPLETED" ? "completed" : "running"
        : input.busy ? (input.current ? "running" : "preparing")
          : selected?.state === "COMPLETED" ? "completed"
            : input.needsData ? "needsData" : "idle";
  return { status, errorDetails } as const;
}

/** Engine locations are 1-based; only expose a jump for a valid source line. */
export function diagnosticLocation(text: string, source: string): { line: number; column: number; offset: number } | null {
  const match = /(?:Error|Warning):(\d+):(\d+):|\(line (\d+):(\d+)\)/.exec(text);
  if (!match) return null;
  const line = Number(match[1] ?? match[3]), column = Number(match[2] ?? match[4]);
  const lines = source.split("\n");
  if (line < 1 || line > lines.length || column < 1) return null;
  return { line, column, offset: lines.slice(0, line - 1).reduce((n, value) => n + value.length + 1, 0) + Math.min(column - 1, lines[line - 1]!.length) };
}
