import { ApiError } from "../../services/api.js";

export function tradingErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.detail) as { message?: unknown };
      if (typeof parsed.message === "string") return parsed.message;
    } catch {
      // detail is plain text
    }
    return error.detail;
  }
  return error instanceof Error ? error.message : String(error);
}
