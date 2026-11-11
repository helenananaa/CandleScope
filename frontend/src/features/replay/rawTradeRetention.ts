export interface RawTradeDayKey {
  readonly symbol: string;
  readonly day: string;
  readonly day_id: string;
}

export interface RawTradePolicy {
  readonly revision: number;
  readonly retain_until_ms: number | null;
}

export interface RawTradeDay {
  readonly day_id: string;
  readonly state: "COMMITTED" | "RETIRED";
  readonly reclaim_started: boolean;
  readonly files: number;
  readonly logical_bytes: number;
}

export interface RawTradePlan {
  readonly plan_id: string;
  readonly day_id: string;
  readonly revision: number;
  readonly expires_ms: number;
  readonly max_files: number;
  readonly max_bytes: number;
}

export interface RawTradeRetentionReply {
  readonly status: string;
  readonly item?: RawTradeDay;
  readonly policy?: RawTradePolicy | null;
  readonly saved_reference_count?: number;
  readonly saved_reference_scan_complete?: boolean;
  readonly plan?: RawTradePlan;
  readonly removed_logical_bytes?: number;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Invalid trade retention record");
  }
  return value as Record<string, unknown>;
}

function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new TypeError("Invalid trade retention integer");
  }
  return value;
}

function identifier(value: unknown, pattern: RegExp): string {
  if (typeof value !== "string" || !pattern.test(value)) {
    throw new TypeError("Invalid trade retention identifier");
  }
  return value;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw new TypeError("Invalid trade retention flag");
  return value;
}

const DAY_ID = /^sha256:[0-9a-f]{64}$/;

export function parseRawTradeRetentionReply(value: unknown): RawTradeRetentionReply {
  const raw = record(value);
  const status = identifier(raw.status, /^[A-Z_]{1,64}$/);
  let policy: RawTradePolicy | null | undefined;
  if (raw.policy !== undefined) {
    const item = raw.policy === null ? null : record(raw.policy);
    policy = item === null ? null : {
      revision: integer(item.revision),
      retain_until_ms: item.retain_until_ms === null ? null : integer(item.retain_until_ms),
    };
  }
  if (status === "READY") {
    const item = record(raw.item);
    if (item.state !== "COMMITTED" && item.state !== "RETIRED") {
      throw new TypeError("Invalid trade retention day state");
    }
    if (policy === undefined) throw new TypeError("Missing trade retention policy");
    return {
      status, policy,
      item: {
        day_id: identifier(item.day_id, DAY_ID), state: item.state,
        reclaim_started: boolean(item.reclaim_started), files: integer(item.files),
        logical_bytes: integer(item.logical_bytes),
      },
      saved_reference_count: integer(raw.saved_reference_count),
      saved_reference_scan_complete: boolean(raw.saved_reference_scan_complete),
    };
  }
  if (status === "PLANNED") {
    const plan = record(raw.plan);
    return {
      status,
      plan: {
        plan_id: identifier(plan.plan_id, /^[0-9a-f]{32}$/),
        day_id: identifier(plan.day_id, DAY_ID), revision: integer(plan.revision),
        expires_ms: integer(plan.expires_ms), max_files: integer(plan.max_files),
        max_bytes: integer(plan.max_bytes),
      },
    };
  }
  if (status === "RECLAIMED" || status === "RECLAIM_PENDING") {
    return { status, removed_logical_bytes: integer(raw.removed_logical_bytes) };
  }
  return policy === undefined ? { status } : { status, policy };
}
