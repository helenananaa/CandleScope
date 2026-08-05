import type {
  KlineApi,
  KlineBeforeRequestOptions,
  KlineFetchResult,
  KlineHistoryRequestOptions,
  KlineRangeRequestOptions,
  KlineRequestOptions,
} from "../market-data/klineContracts.js";
import {
  toEpochSeconds,
  type EpochSeconds,
  type KlineBar,
} from "../market-data/marketDataTypes.js";
import type { IntervalString } from "../../utils/intervals.js";
import { API_BASE } from "../../services/apiConfig.js";
import {
  isJsonRecord,
  parseKlineResponse,
  type TransportKlineResponse,
} from "../../services/apiPayloadParsers.js";
import type {
  LocalDatasetListResponse,
  LocalDatasetManifest,
  LocalImportInput,
} from "./localDataTypes.js";


export class LocalDataApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "LocalDataApiError";
  }
}

function localUrl(path: string, params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return `${API_BASE}/local${path}${query ? `?${query}` : ""}`;
}

async function responseJson(response: Response): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (response.ok) return payload;
  const detail = isJsonRecord(payload) ? payload.detail : null;
  const message = typeof detail === "string"
    ? detail
    : isJsonRecord(detail) && typeof detail.message === "string"
      ? detail.message
      : `HTTP ${response.status}`;
  const code = isJsonRecord(detail) && typeof detail.code === "string" ? detail.code : null;
  throw new LocalDataApiError(message, response.status, code);
}

function expectManifest(value: unknown): LocalDatasetManifest {
  if (!isJsonRecord(value)) throw new TypeError("Local dataset manifest must be an object");
  const requiredStrings = [
    "dataset_id",
    "data_epoch",
    "name",
    "source",
    "symbol",
    "interval",
    "timezone",
    "timestamp_semantics",
    "sqlite_sha256",
    "imported_at",
  ] as const;
  for (const key of requiredStrings) {
    if (typeof value[key] !== "string" || value[key].length === 0) {
      throw new TypeError(`Local dataset manifest field ${key} is invalid`);
    }
  }
  for (const key of [
    "schema_version",
    "rows",
    "first_open_ms",
    "last_open_ms",
    "excluded_range_count",
  ] as const) {
    if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
      throw new TypeError(`Local dataset manifest field ${key} is invalid`);
    }
  }
  if (typeof value.all_rows_final !== "boolean") {
    throw new TypeError("Local dataset manifest field all_rows_final is invalid");
  }
  if (value.volume_available !== undefined && typeof value.volume_available !== "boolean") {
    throw new TypeError("Local dataset manifest field volume_available is invalid");
  }
  if (value.source !== "local_dataset" || value.timestamp_semantics !== "bar_open") {
    throw new TypeError("Local dataset manifest has unsupported source semantics");
  }
  return {
    ...value,
    volume_available: value.volume_available ?? true,
  } as unknown as LocalDatasetManifest;
}

export async function listLocalDatasets(signal?: AbortSignal): Promise<LocalDatasetManifest[]> {
  const payload = await responseJson(await fetch(
    localUrl("/datasets"),
    signal === undefined ? {} : { signal },
  ));
  if (!isJsonRecord(payload) || !Array.isArray(payload.datasets)) {
    throw new TypeError("Local dataset list response is invalid");
  }
  const parsed: LocalDatasetListResponse = {
    datasets: payload.datasets.map(expectManifest),
    count: typeof payload.count === "number" ? payload.count : payload.datasets.length,
  };
  return parsed.datasets;
}

export async function importLocalCsv(input: LocalImportInput): Promise<LocalDatasetManifest> {
  const url = localUrl("/imports/csv", {
    name: input.name,
    symbol: input.symbol,
    interval: input.interval,
    timezone: input.timezone,
    timestamp_unit: input.timestampUnit,
    volume_required: input.volumeRequired,
  });
  const payload = await responseJson(await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "text/csv" },
    body: input.file,
  }));
  return expectManifest(payload);
}

function toKlineFetchResult(payload: unknown, operation: string): KlineFetchResult {
  const result: TransportKlineResponse = parseKlineResponse(payload, operation);
  const data: KlineBar[] = result.data.map((row) => {
    const time = toEpochSeconds(row.time);
    if (time === null) throw new TypeError(`${operation} returned an invalid bar time`);
    return { ...row, time };
  });
  return { ...result, data } as KlineFetchResult;
}

export class LocalKlineApi implements KlineApi {
  constructor(readonly datasetId: string) {}

  private async get(
    path: string,
    params: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<KlineFetchResult> {
    const payload = await responseJson(await fetch(
      localUrl(`/datasets/${encodeURIComponent(this.datasetId)}/klines${path}`, params),
      signal === undefined ? {} : { signal },
    ));
    return toKlineFetchResult(payload, `GET local klines${path}`);
  }

  fetchKlinesHistory(
    _symbol: string,
    interval: IntervalString,
    days: number | null | undefined,
    _marketType: string,
    _exchange: string,
    options: KlineHistoryRequestOptions,
  ): Promise<KlineFetchResult> {
    return this.get("/history", {
      interval,
      days,
      count_back: options.countBack ?? 1_000,
    }, options.signal);
  }

  fetchKlinesBefore(
    _symbol: string,
    interval: IntervalString,
    before: EpochSeconds | undefined,
    bars: number,
    _marketType: string,
    _exchange: string,
    options: KlineBeforeRequestOptions,
  ): Promise<KlineFetchResult> {
    return this.get("/history/before", { interval, before: before ?? 0, bars }, options.signal);
  }

  fetchKlinesRange(
    _symbol: string,
    interval: IntervalString,
    start: EpochSeconds,
    end: EpochSeconds,
    _marketType: string,
    _exchange: string,
    options: KlineRangeRequestOptions,
  ): Promise<KlineFetchResult> {
    return this.get("/range", { interval, start, end }, options.signal);
  }

  fetchLatestKlines(
    _symbol: string,
    interval: IntervalString,
    limit: number,
    _marketType: string,
    _exchange: string,
    _source: string,
    options: KlineRequestOptions,
  ): Promise<KlineFetchResult> {
    return this.get("/latest", { interval, limit }, options.signal);
  }

  getMultiStreamUrl(): string {
    return "";
  }
}
