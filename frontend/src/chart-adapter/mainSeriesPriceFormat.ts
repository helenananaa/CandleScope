import type { ChartSeriesInputRow } from "./chartAdapterTypes.js";

type PriceDelta = { type: string; addedLeft?: number; addedRight?: number };

/** Precision is a display property, never an execution tick-size rule. */
export class MainSeriesPriceFormatTracker {
  private precision = 2;
  private rowCount = 0;

  reset(): void { this.precision = 2; this.rowCount = 0; }

  resolve(rows: readonly ChartSeriesInputRow[], delta: PriceDelta | null = null) {
    if (!delta || delta.type === "replace" || rows.length === 0) this.reset();
    let start = 0;
    let end = rows.length;
    if (delta?.type === "tick" && rows.length >= this.rowCount && rows.length <= this.rowCount + 1) {
      start = Math.max(0, rows.length - 1);
    } else if (delta?.type === "append" && Number.isInteger(delta.addedRight) && Number(delta.addedRight) > 0) {
      start = Math.max(0, rows.length - Number(delta.addedRight));
    } else if (delta?.type === "prepend" && Number.isInteger(delta.addedLeft) && Number(delta.addedLeft) > 0) {
      end = Math.min(rows.length, Number(delta.addedLeft));
    }
    for (let index = start; index < end; index += 1) {
      const row = rows[index];
      if (!row || row.__whitespace) continue;
      for (const field of ["open", "high", "low", "close"] as const) {
        const value = Number(row[field]);
        if (!Number.isFinite(value)) continue;
        const [coefficient = "", exponent = "0"] = String(value).toLowerCase().split("e");
        const decimals = Math.max(0, (coefficient.split(".")[1]?.length ?? 0) - Number(exponent));
        this.precision = Math.max(this.precision, Math.min(8, decimals));
      }
    }
    this.rowCount = rows.length;
    return { type: "price" as const, precision: this.precision, minMove: 10 ** -this.precision };
  }
}
