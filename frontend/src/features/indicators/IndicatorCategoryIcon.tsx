/** Decorative category marks; the adjacent translated text provides the label. */
const paths: Readonly<Record<string, string>> = {
  trend: "M3 18L9 12L13 15L21 6M15 6H21V12",
  momentum: "M13 3L5 14H11L10 21L19 10H13Z",
  oscillator: "M3 12C6 2 8 2 12 12S18 22 21 12",
  volatility: "M3 5L9 8L15 6L21 4M3 12L9 11L15 13L21 12M3 19L9 15L15 18L21 20",
  volume: "M4 20V12H8V20M10 20V4H14V20M16 20V8H20V20M3 20H21",
  "contract-data": "M14 4H7A2 2 0 0 0 5 6V19A2 2 0 0 0 7 21H18A2 2 0 0 0 20 19V10L14 4V10H20M9 14H16M9 17H14",
  custom: "M4 20L5 15L16 4A2 2 0 0 1 20 8L9 19Z M14 6L18 10",
};

export function IndicatorCategoryIcon({ category }: { category: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false">
      <path d={paths[category] ?? "M4 4H10V10H4ZM14 4H20V10H14ZM4 14H10V20H4ZM14 14H20V20H14Z"} />
    </svg>
  );
}
