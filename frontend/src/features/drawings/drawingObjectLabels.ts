import { t } from "../../i18n/index.js";
export function drawingName(type: string): string {
  if (type === "fibonacci") return t("drawing.settings.fibonacciLevels");
  if (type === "position") return t("drawing.settings.position");
  const key = ({
    line: "drawing.variant.line-segment",
    "line-segment": "drawing.variant.line-segment",
    "line-ray": "drawing.variant.line-ray",
    "line-infinite": "drawing.variant.line-infinite",
    "horizontal-line": "drawing.variant.line-horizontal",
    "vertical-line": "drawing.variant.line-vertical",
    "cross-line": "drawing.variant.line-cross",
    "range-measure": "drawing.variant.measure-price-time",
    "measure-price": "drawing.variant.measure-price",
    "measure-time": "drawing.variant.measure-time",
    "measure-price-time": "drawing.variant.measure-price-time",
    "angle-measure": "drawing.variant.angle-measure",
    rectangle: "drawing.variant.shape-rectangle",
    ellipse: "drawing.variant.shape-ellipse",
    freehand: "drawing.variant.pen",
    highlighter: "drawing.variant.highlighter",
    "position-long": "drawing.variant.position-long",
    "position-short": "drawing.variant.position-short",
  } as const)[type as "line"];
  return key ? t(key) : type;
}
