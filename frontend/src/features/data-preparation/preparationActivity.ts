import type { PreparationJob } from "./api.js";

export function replayPreparationActivity(jobs: readonly PreparationJob[]) {
  const pending = jobs.filter((job) => job.request.consumer === "REPLAY"
    && ["QUEUED", "RUNNING", "FAILED", "BLOCKED_STORAGE"].includes(job.state));
  return {
    pending,
    failed: pending.filter((job) => ["FAILED", "BLOCKED_STORAGE"].includes(job.state)).length,
  };
}

export function replayPreparationCompleted(previous: readonly PreparationJob[], current: readonly PreparationJob[]): boolean {
  const unfinished = new Set(previous.filter((job) => job.state !== "READY").map((job) => job.id));
  return current.some((job) => job.request.consumer === "REPLAY" && job.state === "READY" && unfinished.has(job.id));
}
