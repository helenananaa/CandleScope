import { t } from "../../i18n/index.js";

function decimalParts(text: string): { units: bigint; scale: number } | null {
  const match = /^(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(text.trim());
  if (!match) return null;
  const scale = (match[2]?.length ?? 0) - Number(match[3] ?? 0);
  if (!Number.isSafeInteger(scale) || Math.abs(scale) > 100) return null;
  const units = BigInt(`${match[1]}${match[2] ?? ""}`);
  return scale < 0 ? { units: units * 10n ** BigInt(-scale), scale: 0 } : { units, scale };
}

/** Keep an explicit percentage tied to the freshly quoted submission side. */
export function replayQuantityForShare(maximum: string, share: number, step: string): string | null {
  if (!Number.isFinite(share) || share < 0 || share > 1) return null;
  const cap = decimalParts(maximum);
  const ratio = decimalParts(String(share));
  const tick = decimalParts(step);
  if (!cap || !ratio || !tick || tick.units <= 0n) return null;
  const steps = (cap.units * ratio.units * 10n ** BigInt(tick.scale))
    / (tick.units * 10n ** BigInt(cap.scale + ratio.scale));
  const units = steps * tick.units;
  if (tick.scale === 0) return String(units);
  const digits = String(units).padStart(tick.scale + 1, "0");
  return `${digits.slice(0, -tick.scale)}.${digits.slice(-tick.scale)}`.replace(/\.?0+$/, "");
}

export interface ReplayMaxQuantityRebaseInput {
  readonly previousMaxQuantity: number | null;
  readonly previousReferencePrice: number | null;
  readonly nextReferencePrice: number | null;
  readonly previousAvailableEquity: number | null;
  readonly nextAvailableEquity: number | null;
  readonly previousLeverage: number;
  readonly nextLeverage: number;
  readonly reduceOnly: boolean;
}

export interface ReplayOrderSizingAvailability {
  readonly sliderDisabled: boolean;
  readonly quantityExceedsCapacity: boolean;
}

/** A stale advisory must never offer more closing size than the remaining leg. */
export function replayBoundClosingCapacity(
  advisory: string | null, reduceOnly: boolean, positionQuantity: number,
): string | null {
  if (!reduceOnly) return advisory;
  const remaining = Math.abs(positionQuantity);
  if (remaining === 0) return "0";
  if (advisory === null || advisory.trim() === "" || !Number.isFinite(Number(advisory))) return null;
  return String(Math.max(0, Math.min(remaining, Number(advisory))));
}

/** A quote for one hedge leg must not disable the other leg's submit button. */
export function replayOrderSideCapacity(
  advisory: string | null,
  advisorySide: "BUY" | "SELL",
  requestedSide: "BUY" | "SELL",
  reduceOnly: boolean,
  targetPositionQuantity: number,
): string | null {
  const matching = advisorySide === requestedSide;
  if (!reduceOnly) return matching ? advisory : null;
  return replayBoundClosingCapacity(
    matching ? advisory : String(Math.abs(targetPositionQuantity)),
    true,
    targetPositionQuantity,
  );
}

export function replayReduceOnlyUnavailableMessage({
  reduceOnly,
  positionQuantity,
  positionMode,
  targetPositionSide,
}: {
  readonly reduceOnly: boolean;
  readonly positionQuantity: number;
  readonly positionMode: "ONE_WAY" | "HEDGE";
  readonly targetPositionSide: "LONG" | "SHORT";
}): string | null {
  if (!reduceOnly || positionQuantity !== 0) return null;
  if (positionMode !== "HEDGE") return t("replay.paper.noPos");
  return targetPositionSide === "LONG" ? t("replay.paper.noLong") : t("replay.paper.noShort");
}

/**
 * Derive draft validity only from the independent capacity channel. Preview
 * failures intentionally are not an input, so they cannot disable the slider.
 */
export function replayOrderSizingAvailability(
  maxQuantity: string | null,
  draftQuantity: string,
): ReplayOrderSizingAvailability {
  // Number("") is 0; blank/whitespace maxima are unknown, not a zero cap.
  const maximum = maxQuantity === null || maxQuantity.trim() === ""
    ? Number.NaN
    : Number(maxQuantity);
  const quantity = Number(draftQuantity);
  const validMaximum = Number.isFinite(maximum) && maximum > 0;
  const knownCapacity = Number.isFinite(maximum) && maximum >= 0;
  return {
    sliderDisabled: !validMaximum,
    quantityExceedsCapacity: knownCapacity
      && Number.isFinite(quantity)
      && quantity > maximum,
  };
}

function positiveFinite(value: number | null): value is number {
  return value !== null && Number.isFinite(value) && value > 0;
}

export function replayOrderPreviewSide(
  positionQuantity: number,
  selectedSide: "BUY" | "SELL",
): "BUY" | "SELL" {
  if (positionQuantity > 0) return "BUY";
  if (positionQuantity < 0) return "SELL";
  return selectedSide;
}

export function replayOrderContextSide(
  positionQuantity: number,
  selectedSide: "BUY" | "SELL",
  reduceOnly: boolean,
): "BUY" | "SELL" {
  if (!reduceOnly) return replayOrderPreviewSide(positionQuantity, selectedSide);
  if (positionQuantity > 0) return "SELL";
  if (positionQuantity < 0) return "BUY";
  return selectedSide;
}

/**
 * Conservatively carry a server-authoritative quantity cap across a market
 * cursor change. The estimate may shrink immediately, but never grows until a
 * fresh server preview confirms the larger capacity.
 */
export function rebaseReplayMaxQuantity({
  previousMaxQuantity,
  previousReferencePrice,
  nextReferencePrice,
  previousAvailableEquity,
  nextAvailableEquity,
  previousLeverage,
  nextLeverage,
  reduceOnly,
}: ReplayMaxQuantityRebaseInput): number | null {
  if (!positiveFinite(previousMaxQuantity)) return null;
  if (reduceOnly) return previousMaxQuantity;
  // Known zero/negative equity cannot fund a new opening size, even if the
  // previous equity snapshot is missing and cannot be used as a ratio.
  if (
    nextAvailableEquity !== null
    && Number.isFinite(nextAvailableEquity)
    && nextAvailableEquity <= 0
  ) {
    return null;
  }

  let rebased = previousMaxQuantity;
  if (positiveFinite(previousReferencePrice) && positiveFinite(nextReferencePrice)) {
    rebased *= previousReferencePrice / nextReferencePrice;
  }
  if (positiveFinite(previousAvailableEquity) && positiveFinite(nextAvailableEquity)) {
    rebased *= nextAvailableEquity / previousAvailableEquity;
  }
  if (
    Number.isFinite(previousLeverage)
    && previousLeverage > 0
    && Number.isFinite(nextLeverage)
    && nextLeverage > 0
  ) {
    rebased *= nextLeverage / previousLeverage;
  }
  if (!Number.isFinite(rebased) || rebased <= 0) return null;

  return Math.min(previousMaxQuantity, rebased);
}
