export type ContinuousMode = "HISTORY" | "HISTORY_LIVE" | "LIVE_ONLY";
export interface CommittedIdentity {
  id: string; generation: number; revision: number; checkpoint_revision: number;
  sequence: number; event_time_ms: number; data_revision: string;
}
export interface ContinuousRun extends CommittedIdentity {
  phase: string; failure_code?: string | null; [field: string]: unknown;
}
export interface ContinuousCreation {
  request_key: string; run_id: string; revision: number; phase: string;
  cutoff_ms: number; mode: string; [field: string]: unknown;
}
export interface ContinuousCapabilities {
  execution_enabled: boolean; runtime_mode: string; protocol: "continuous.v1";
  python_editor_authorized: boolean; python_author_contract: string;
  repair_available: boolean; intervals: string[]; languages: string[];
}
export interface ContinuousCreate {
  mode: Exclude<ContinuousMode, "HISTORY">;
  series: { exchange: string; market_type: string; symbol: string; interval: string; identity: Record<string, string> };
  provider: { language: "python" | "builtin"; source_text?: string; builtin_id?: string;
    parameters: Record<string, unknown>; output_mode: "SIGNAL" | "TARGET_POSITION" | "ORDER_INTENT";
    runtime_mode?: "TRUSTED_LOCAL"; trusted_confirmed?: boolean };
  execution: Record<string, unknown>; from_ms?: number; warmup_bars?: number;
}
export const resultKinds = ["orders", "fills", "decisions", "rejected", "equity_curve", "ledger",
  "order_events", "frozen_intents", "fill_source_events"] as const;
export type ResultKind = typeof resultKinds[number];
export interface ContinuousPage {
  run: ContinuousRun; identity: CommittedIdentity; summary: Record<string, unknown>;
  counts: Record<ResultKind, number>; stale: boolean;
  items: Array<{ kind: ResultKind; index: number; value: unknown }>;
  more: boolean; next_cursor: [number, ResultKind, number] | null;
}
export interface ContinuousInitial {
  creation: ContinuousCreation; initial_result_ready: boolean; result: ContinuousPage | null;
}
export type ContinuousPacket = Partial<ContinuousPage> & {
  protocol: "continuous.v1"; type: string; begin?: boolean; complete?: boolean;
  terminal?: boolean; after_checkpoint?: number; creation?: ContinuousCreation | null;
  initial_result_ready?: boolean; reason?: string;
  repair?: ContinuousRepair | null;
  error?: { code: string; message: string };
};
export type ContinuousAction = "pause" | "resume" | "retry" | "cancel";
export interface ContinuousControl {
  action: ContinuousAction; revision: number; expected?: CommittedIdentity; refresh_input?: boolean;
}
export interface ContinuousRepairPlan {
  plan_id: string; expected: CommittedIdentity; resume_after: boolean;
  from_ms: number; through_ms: number; original_from_ms: number;
  anchor_sequence: number; full_reinitialization: boolean; expanded_range_reason: string | null;
  dirty_from_ms: number | null; dirty_through_ms: number | null;
  recompute_bars: number; expires_in_seconds: number;
}
export interface ContinuousRepair {
  id: string; request_key: string; run_id: string;
  phase: "REQUESTED" | "PREPARING" | "READY" | "COMMITTED" | "FAILED" | "CANCELLED";
  target_revision: number; base_identity: CommittedIdentity; plan_id: string;
  resume_after: boolean; from_ms: number; through_ms: number; original_from_ms: number;
  anchor_sequence: number; full_reinitialization: boolean; expanded_range_reason: string | null;
  progress: { state?: string; sequence?: number; event_time_ms?: number; through_ms?: number;
    waiting?: string; resources_released?: boolean; physical_resources_released?: boolean;
    cleanup_error?: { code: string; message: string } } | null;
  error: { code: string; message: string } | null; updated_at_ms: number;
}
export interface ContinuousRepairConfirm {
  expected: CommittedIdentity; plan_id: string; resume_after: boolean; confirmed: true;
}
export interface ContinuousApi {
  capabilities(signal: AbortSignal): Promise<ContinuousCapabilities>;
  create(key: string, body: ContinuousCreate, signal: AbortSignal): Promise<{ creation: ContinuousCreation }>;
  request(key: string, signal: AbortSignal): Promise<{ creation: ContinuousCreation }>;
  catalog(signal: AbortSignal): Promise<{ runs: ContinuousRun[]; preparations: ContinuousCreation[]; repairs?: ContinuousRepair[] }>;
  status(id: string, signal: AbortSignal): Promise<{ creation: ContinuousCreation | null; run: ContinuousRun | null; identity?: CommittedIdentity; repair?: ContinuousRepair | null }>;
  initial(id: string, signal: AbortSignal): Promise<ContinuousInitial>;
  page(id: string, body: { since_revision: number; expected: CommittedIdentity;
    change_cursor: ContinuousPage["next_cursor"] }, signal: AbortSignal): Promise<ContinuousPage>;
  control(key: string, body: ContinuousControl, signal: AbortSignal): Promise<{ creation: ContinuousCreation; run: ContinuousRun | null }>;
  repairPreview(id: string, body: { expected: CommittedIdentity; resume_after: boolean }, signal: AbortSignal): Promise<{ plan: ContinuousRepairPlan }>;
  repair(id: string, key: string, body: ContinuousRepairConfirm, signal: AbortSignal): Promise<{ repair: ContinuousRepair }>;
  repairStatus(key: string, signal: AbortSignal): Promise<{ repair: ContinuousRepair }>;
  latestRepair(id: string, signal: AbortSignal): Promise<{ repair: ContinuousRepair | null }>;
  cancelRepair(key: string, expected: CommittedIdentity, signal: AbortSignal): Promise<{ repair: ContinuousRepair }>;
  stream(id: string, after: CommittedIdentity | undefined, signal: AbortSignal,
    accept: (packet: ContinuousPacket) => void): Promise<void>;
}
