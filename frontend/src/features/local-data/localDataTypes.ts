export interface LocalDatasetManifest {
  schema_version: number;
  dataset_id: string;
  data_epoch: string;
  name: string;
  source: "local_dataset";
  symbol: string;
  interval: string;
  volume_available: boolean;
  timezone: string;
  timestamp_semantics: "bar_open";
  rows: number;
  first_open_ms: number;
  last_open_ms: number;
  all_rows_final: boolean;
  excluded_range_count: number;
  sqlite_sha256: string;
  imported_at: string;
}

export interface LocalImportInput {
  file: File;
  name: string;
  symbol: string;
  interval: string;
  timezone: string;
  timestampUnit: "auto" | "s" | "ms" | "iso";
  volumeRequired: boolean;
}

export interface LocalDatasetListResponse {
  datasets: LocalDatasetManifest[];
  count: number;
}

export type LocalEventTimeResolutionMode = "exact" | "containing";

export interface LocalEventTimeResolution {
  input_index: number;
  input_time_ms: number;
  matched: boolean;
  bar_open_ms?: number;
  bar_close_ms?: number;
  delta_ms?: number;
}

export interface LocalEventTimeResolutionResponse {
  dataset_id: string;
  data_epoch: string;
  mode: LocalEventTimeResolutionMode;
  matched: number;
  rejected: number;
  results: LocalEventTimeResolution[];
}

export type LocalIndicatorName = "MA" | "EMA" | "RSI" | "MACD" | "BOLL";
