/**
 * Text drawn in a chart's candle colours (the legend's OHLC values) must stay readable on the
 * chart's own background, which can be light, dark or a custom colour. The candle colour is kept
 * when it already reaches WCAG AA; otherwise it is blended toward black (on a light background)
 * or white (on a dark one) just far enough, so the hue stays recognisable.
 */

type Rgb = [number, number, number];

function parseHex(value: string): Rgb | null {
  const hex = value.trim().replace(/^#/, "");
  const full = hex.length === 3 || hex.length === 4 ? [...hex.slice(0, 3)].map((c) => c + c).join("") : hex.slice(0, 6);
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as Rgb;
}

function parseRgb(value: string): Rgb | null {
  const match = /^rgba?\(([^)]+)\)$/i.exec(value.trim());
  if (!match) return null;
  const parts = match[1]!.split(/[\s,/]+/).filter(Boolean).slice(0, 3).map(Number);
  return parts.length === 3 && parts.every(Number.isFinite) ? (parts as Rgb) : null;
}

export function parseColor(value: string): Rgb | null {
  return value.trim().startsWith("#") ? parseHex(value) : parseRgb(value);
}

function luminance([r, g, b]: Rgb): number {
  const [R, G, B] = [r, g, b].map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)) as Rgb;
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

export function contrastRatio(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const toHex = (rgb: Rgb) => `#${rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;

/** `color` adjusted to reach `minRatio` against `background`; unchanged when it already does or cannot be read. */
export function legibleOn(color: string, background: string, minRatio = 4.5): string {
  const fg = parseColor(color);
  const bg = parseColor(background);
  if (!fg || !bg || contrastRatio(fg, bg) >= minRatio) return color;
  const target: Rgb = luminance(bg) > 0.18 ? [0, 0, 0] : [255, 255, 255];
  for (let step = 1; step <= 20; step++) {
    const amount = step / 20;
    const mixed = fg.map((v, i) => v + (target[i]! - v) * amount) as Rgb;
    if (contrastRatio(mixed, bg) >= minRatio) return toHex(mixed);
  }
  return toHex(target);
}
