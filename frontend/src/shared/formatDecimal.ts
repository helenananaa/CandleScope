/** Round for display only, without losing precision through a floating-point conversion. */
export function formatDecimal(value: string, maximumFractionDigits = 2): string {
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)) return value;
  const digits = Math.max(0, Math.min(18, Math.trunc(maximumFractionDigits) || 0));
  const negative = value.startsWith("-");
  const [whole = "0", fraction] = value.replace(/^-/, "").split(".");
  if (fraction === undefined) return `${negative ? "-" : ""}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
  const scale = 10n ** BigInt(digits);
  const rounded = BigInt(whole) * scale + BigInt(fraction.slice(0, digits).padEnd(digits, "0") || "0")
    + (Number(fraction[digits] ?? "0") >= 5 ? 1n : 0n);
  const grouped = (rounded / scale).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimals = digits === 0 ? "" : `.${(rounded % scale).toString().padStart(digits, "0")}`;
  return `${negative && rounded !== 0n ? "-" : ""}${grouped}${decimals}`;
}
