/** Neutral chart contract rules shared by Workbench and requested markets. */
export interface PineContractMetadata {
  priceTickSize: string; currency?: string; quantityPrecision?: number;
  pointValue?: number; quantityStep?: string; minContract?: string;
}
export interface PineContractDraft {
  priceTickSize?: string; currency?: string; quantityPrecision?: string;
  pointValue?: string; quantityStep?: string; minContract?: string;
}
export const contractDraftKeys = ["priceTickSize", "currency", "quantityPrecision", "pointValue", "quantityStep", "minContract"] as const;

function decimalParts(text: string): { coefficient: bigint; exponent: number } {
  if (text.length > 80 || !/^[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$/.test(text))
    throw new Error("Use a positive decimal quantity rule");
  const [mantissa = "", scale = "0"] = text.replace(/^\+/, "").toLowerCase().split("e");
  let exponent = Number(scale) - (mantissa.split(".")[1]?.length ?? 0);
  if (!Number.isSafeInteger(exponent) || Math.abs(Number(scale)) > 100)
    throw new Error("Quantity rule exponent exceeds the runtime limit");
  let coefficient = BigInt(mantissa.replace(".", ""));
  if (coefficient <= 0n) throw new Error("Quantity rule must be positive");
  while (coefficient % 10n === 0n) { coefficient /= 10n; exponent++; }
  return { coefficient, exponent };
}

export function quantityDecimalPlaces(text: unknown): number {
  if (typeof text !== "string") throw new Error("Quantity rule must be a decimal string");
  const exact = decimalParts(text);
  if (exact.exponent < -18 || exact.exponent > 19
      || exact.coefficient * 10n ** BigInt(Math.max(0, exact.exponent)) > 18446744073709551615n)
    throw new Error("Quantity rule exceeds the runtime decimal limit");
  const transported = decimalParts(String(Number(text)));
  if (exact.coefficient !== transported.coefficient || exact.exponent !== transported.exponent)
    throw new Error("Quantity rule cannot preserve its exact value in the runtime");
  return Math.max(0, -exact.exponent);
}

export function validatePineContractMetadata(value: unknown): asserts value is PineContractMetadata {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Use actual instrument metadata");
  const metadata = value as Record<string, unknown>;
  if (Object.keys(metadata).some(key => !(contractDraftKeys as readonly string[]).includes(key))
      || typeof metadata.priceTickSize !== "string" || !Number.isFinite(Number(metadata.priceTickSize)) || Number(metadata.priceTickSize) <= 0
      || (metadata.currency !== undefined && (typeof metadata.currency !== "string" || !/^[A-Z]{1,20}$/.test(metadata.currency)))
      || (metadata.quantityPrecision !== undefined && (typeof metadata.quantityPrecision !== "number" || !Number.isInteger(metadata.quantityPrecision) || metadata.quantityPrecision < 0 || metadata.quantityPrecision > 9))
      || (metadata.pointValue !== undefined && (typeof metadata.pointValue !== "number" || !Number.isFinite(metadata.pointValue) || metadata.pointValue <= 0)))
    throw new Error("Use actual positive price tick, point value, currency and quantity rules");
  if (metadata.quantityStep !== undefined) {
    const places = quantityDecimalPlaces(metadata.quantityStep);
    if (typeof metadata.quantityPrecision === "number" && places > metadata.quantityPrecision)
      throw new Error("Quantity step exceeds quantity precision");
  }
  if (metadata.minContract !== undefined) quantityDecimalPlaces(metadata.minContract);
}

export function pineContractMetadata(draft: PineContractDraft): PineContractMetadata | undefined {
  if (!contractDraftKeys.some(key => draft[key])) return undefined;
  if (!draft.priceTickSize) throw new Error("Instrument metadata requires its actual price tick");
  if (draft.quantityPrecision && !/^[0-9]$/.test(draft.quantityPrecision)) throw new Error("Quantity precision must be 0..9");
  const result = { priceTickSize: draft.priceTickSize,
    ...(draft.currency ? { currency: draft.currency } : {}),
    ...(draft.pointValue ? { pointValue: Number(draft.pointValue) } : {}),
    ...(draft.quantityPrecision ? { quantityPrecision: Number(draft.quantityPrecision) } : {}),
    ...(draft.quantityStep ? { quantityStep: draft.quantityStep } : {}),
    ...(draft.minContract ? { minContract: draft.minContract } : {}) };
  validatePineContractMetadata(result);
  return result;
}
