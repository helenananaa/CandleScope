import type { Tone } from "../../../components/ui/index.js";

/** Badge tone for a run, study or bridge state shown in the research tools. */
export function researchStateTone(state: string | null | undefined): Tone {
  const value = String(state ?? "").toUpperCase();
  if (["COMPLETED", "READY", "SUCCEEDED", "PASSED", "ACCEPTED", "REVEALED"].includes(value)) return "success";
  if (["FAILED", "REJECTED", "ERROR", "INVALID"].includes(value)) return "danger";
  if (["CANCELED", "CANCELLED", "ARCHIVED", "DRAFT", ""].includes(value)) return "neutral";
  return "accent";
}
