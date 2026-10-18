import type { MainChartType } from "../../shared/mainChartTypes.js";
import { getChartTypeDescriptor } from "./chartTypeRegistry.js";
import { createProjector } from "./projectorFactory.js";
import { ProjectionStore } from "./projectionStore.js";
import { resolveRenkoProjectorOptions } from "./renkoProjectionOptions.js";
import { resolvePointFigureProjectorOptions } from "./pointFigureProjectionOptions.js";
import { resolveKagiProjectorOptions } from "./kagiProjectionOptions.js";
import { resolveLineBreakProjectorOptions } from "./lineBreakProjectionOptions.js";
import type { RenkoProjectionOptions, PointFigureProjectionOptions, KagiProjectionOptions,
  LineBreakProjectionOptions, SourceBar, ProjectionSourceDelta, ProjectionPatch } from "./chartRepresentationTypes.js";

type ProjectionSettings = RenkoProjectionOptions & PointFigureProjectionOptions
  & KagiProjectionOptions & LineBreakProjectionOptions;

function resolveProjectionRuntime(
  chartType: MainChartType,
  rows: readonly SourceBar[],
  settings: ProjectionSettings = {},
) {
  const descriptor = getChartTypeDescriptor(chartType);
  if (descriptor.projectionId === "renko") {
    const options = resolveRenkoProjectorOptions(rows, settings);
    return { descriptor, options, configKey: options.configKey };
  }
  if (descriptor.projectionId === "point-and-figure") {
    const options = resolvePointFigureProjectorOptions(rows, settings);
    return { descriptor, options, configKey: options.configKey };
  }
  if (descriptor.projectionId === "kagi") {
    const options = resolveKagiProjectorOptions(rows, settings);
    return { descriptor, options, configKey: options.configKey };
  }
  if (descriptor.projectionId === "line-break") {
    const options = resolveLineBreakProjectorOptions(rows, settings);
    return { descriptor, options, configKey: options.configKey };
  }
  return { descriptor, options: {}, configKey: descriptor.projectionId };
}

/** The display uses the existing whole-revealed-window ATR rule. Resolve the
 * same parameters after an async load, a live delta and a fresh restoration.
 * This may reproject earlier display bricks when ATR changes; it is not a
 * causal strategy-input series and never receives future source rows.
 */
class ConfiguredProjectionStore extends ProjectionStore {
  configurationKey: string;

  constructor(private readonly chartType: MainChartType, rows: readonly SourceBar[],
    private readonly settings: ProjectionSettings) {
    const runtime = resolveProjectionRuntime(chartType, rows, settings);
    super({ projector: createProjector(runtime.descriptor.projectionId, runtime.options) });
    this.configurationKey = runtime.configKey;
  }

  private calibrate(rows: readonly SourceBar[]): boolean {
    const runtime = resolveProjectionRuntime(this.chartType, rows, this.settings);
    if (runtime.configKey === this.configurationKey) return false;
    this.projector = createProjector(runtime.descriptor.projectionId, runtime.options);
    this.configurationKey = runtime.configKey;
    return true;
  }

  override reset(rows: readonly SourceBar[] = []): ProjectionPatch {
    this.calibrate(rows);
    return super.reset(rows);
  }

  override applySourceDelta(delta: ProjectionSourceDelta | null | undefined,
    rows: readonly SourceBar[] = []): ProjectionPatch {
    if (delta?.type !== "noop" && delta?.type !== "clear" && this.calibrate(rows)) {
      return super.reset(rows);
    }
    return super.applySourceDelta(delta, rows);
  }
}

export function createConfiguredProjectionStore(chartType: MainChartType,
  rows: readonly SourceBar[] = [], settings: ProjectionSettings = {}): ConfiguredProjectionStore {
  return new ConfiguredProjectionStore(chartType, rows, { ...settings });
}
