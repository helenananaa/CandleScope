import type { IndicatorParams } from "./indicatorTypes.js";

export interface PineCurrencyRates {
  schemaVersion: 1;
  pairs: Array<{ from: string; to: string; rates?: Array<{ effectiveTime: number; rate: number }>; unavailable?: true }>;
}

export function parsePineCurrencyRates(text: string): PineCurrencyRates | null {
  if (!text.trim()) return null;
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected currency rate data");
  const root = value as Record<string, unknown>;
  if (Object.keys(root).sort().join() !== "pairs,schemaVersion" || root.schemaVersion !== 1 || !Array.isArray(root.pairs) || root.pairs.length > 64)
    throw new Error("Use schemaVersion 1 and at most 64 currency pairs");
  const seen = new Set<string>();
  let count = 0;
  for (const item of root.pairs) {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("Invalid currency pair");
    const pair = item as Record<string, unknown>;
    const key = `${String(pair.from)}:${String(pair.to)}`;
    if (typeof pair.from !== "string" || !/^[A-Z]{1,20}$/.test(pair.from) || typeof pair.to !== "string" || !/^[A-Z]{1,20}$/.test(pair.to) || seen.has(key))
      throw new Error("Use unique uppercase currency pairs");
    seen.add(key);
    const fields = Object.keys(pair).sort().join();
    if (fields === "from,to,unavailable" && pair.unavailable === true) continue;
    if (fields !== "from,rates,to" || !Array.isArray(pair.rates)) throw new Error("Each pair needs rates or unavailable: true");
    count += pair.rates.length;
    if (count > 100_000) throw new Error("At most 100000 effective rates");
    let previous = -Infinity;
    for (const entry of pair.rates) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) throw new Error("Invalid effective rate");
      const row = entry as Record<string, unknown>;
      if (Object.keys(row).sort().join() !== "effectiveTime,rate" || typeof row.effectiveTime !== "number" || !Number.isSafeInteger(row.effectiveTime) || row.effectiveTime <= previous
        || typeof row.rate !== "number" || !Number.isFinite(row.rate) || row.rate <= 0)
        throw new Error("Use increasing millisecond availability times and positive rates");
      previous = row.effectiveTime;
    }
  }
  return value as PineCurrencyRates;
}

export function pineCurrencyParams(params: IndicatorParams, text: string): IndicatorParams {
  const rates = parsePineCurrencyRates(text);
  const result = { ...params };
  delete result.__pineCurrencyRates;
  return rates ? { ...result, __pineCurrencyRates: rates } : result;
}
