import type {
  AngleToolId,
  ArrowToolId,
  AxisLineToolId,
  BasicLineToolId,
  ChannelToolId,
  DrawingToolId,
  FibonacciToolId,
  PathToolId,
  PositionToolId,
  RangeMeasureToolId,
  ShapeToolId,
} from "../drawingTypes.js";
import type { TwoPointCreationTool } from "./drawingEntityCreation.js";

/** Tool-id predicates shared by the interaction controller (split from it). */
export type LineToolId = RangeMeasureToolId
  | BasicLineToolId
  | ArrowToolId
  | PathToolId
  | ChannelToolId
  | AxisLineToolId
  | AngleToolId;
export function isLineToolId(tool: DrawingToolId | null | undefined): tool is LineToolId {
  return tool === "line-segment"
    || tool === "line-ray"
    || tool === "line-infinite"
    || tool === "line-horizontal"
    || tool === "line-vertical"
    || tool === "line-cross"
    || tool === "line-arrow"
    || tool === "path-line" || tool === "path-arrow"
    || tool === "channel-parallel"
    || tool === "measure-price"
    || tool === "measure-time"
    || tool === "measure-price-time"
    || tool === "angle-measure";
}

export function isAxisLineToolId(tool: DrawingToolId | null | undefined): tool is AxisLineToolId {
  return tool === "line-horizontal" || tool === "line-vertical" || tool === "line-cross";
}

export function isFibonacciToolId(tool: DrawingToolId | null | undefined): tool is FibonacciToolId {
  return tool === "fibonacci";
}

export function isPositionToolId(tool: DrawingToolId | null | undefined): tool is PositionToolId {
  return tool === "position-long" || tool === "position-short";
}

export function isShapeToolId(tool: DrawingToolId | null | undefined): tool is ShapeToolId {
  return tool === "shape-rectangle" || tool === "shape-ellipse";
}

export function isTwoPointCreationTool(
  tool: DrawingToolId | null | undefined,
): tool is TwoPointCreationTool {
  return tool === "line-segment"
    || tool === "line-ray"
    || tool === "line-infinite"
    || tool === "line-arrow"
    || tool === "path-line" || tool === "path-arrow"
    || tool === "channel-parallel"
    || tool === "measure-price"
    || tool === "measure-time"
    || tool === "measure-price-time"
    || tool === "angle-measure"
    || tool === "fibonacci"
    || tool === "shape-rectangle"
    || tool === "shape-ellipse"
    || tool === "fib-extension"
    || tool === "anchored-vwap"
    || tool === "volume-profile"
    || tool === "regression-channel";
}
