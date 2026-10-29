import { decodeKlineResult } from "./klineEndpointDecoder.js";
import {
  fetchKlinesBefore as fetchTransportKlinesBefore,
  fetchKlinesHistory as fetchTransportKlinesHistory,
  fetchKlinesHistoryBatch as fetchTransportKlinesHistoryBatch,
  fetchKlinesRange as fetchTransportKlinesRange,
  fetchLatestKlines as fetchTransportLatestKlines,
  getMultiStreamUrl,
} from "../../../services/api.js";
import type {
  KlineApi,
  KlineBeforeRequestOptions,
  KlineFetchResult,
  KlineHistoryRequestOptions,
  KlineHistoryBatchOutcome,
  KlineHistoryBatchRequest,
  KlineRangeRequestOptions,
  KlineRequestOptions,
} from "../klineContracts.js";
import type { EpochSeconds } from "../marketDataTypes.js";
import type { IntervalString } from "../../../utils/intervals.js";

async function fetchKlinesHistory(
  symbol: string,
  interval: IntervalString,
  days: number | null | undefined,
  marketType: string,
  exchange: string,
  options: KlineHistoryRequestOptions,
): Promise<KlineFetchResult> {
  return decodeKlineResult(await fetchTransportKlinesHistory(
    symbol,
    interval,
    days,
    marketType,
    exchange,
    options,
  ), "history");
}

async function fetchKlinesHistoryBatch(
  requests: readonly KlineHistoryBatchRequest[],
  options: { signal?: AbortSignal },
): Promise<KlineHistoryBatchOutcome[]> {
  const outcomes = await fetchTransportKlinesHistoryBatch(requests, options);
  return outcomes.map((outcome) => outcome.ok
    ? { ok: true, result: decodeKlineResult(outcome.result, "history") }
    : outcome);
}

async function fetchKlinesBefore(
  symbol: string,
  interval: IntervalString,
  before: EpochSeconds | undefined,
  bars: number,
  marketType: string,
  exchange: string,
  options: KlineBeforeRequestOptions,
): Promise<KlineFetchResult> {
  return decodeKlineResult(await fetchTransportKlinesBefore(
    symbol,
    interval,
    before ?? 0,
    bars,
    marketType,
    exchange,
    options,
  ), "before");
}

async function fetchKlinesRange(
  symbol: string,
  interval: IntervalString,
  start: EpochSeconds,
  end: EpochSeconds,
  marketType: string,
  exchange: string,
  options: KlineRangeRequestOptions,
): Promise<KlineFetchResult> {
  return decodeKlineResult(await fetchTransportKlinesRange(
    symbol,
    interval,
    start,
    end,
    marketType,
    exchange,
    options,
  ), "range");
}

async function fetchLatestKlines(
  symbol: string,
  interval: IntervalString,
  limit: number,
  marketType: string,
  exchange: string,
  source: string,
  options: KlineRequestOptions,
): Promise<KlineFetchResult> {
  return decodeKlineResult(await fetchTransportLatestKlines(
    symbol,
    interval,
    limit,
    marketType,
    exchange,
    source,
    options,
  ), "latest");
}

export const defaultKlineApi = {
  fetchKlinesHistory,
  fetchKlinesHistoryBatch,
  fetchKlinesBefore,
  fetchKlinesRange,
  fetchLatestKlines,
  getMultiStreamUrl,
} satisfies KlineApi;
