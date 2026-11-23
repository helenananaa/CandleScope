import type { SyntheticChartBinding } from "../market-data/synthetic/syntheticChartBinding.js";
import type { ProjectionSourceDelta, SourceBar } from "./chartRepresentationTypes.js";
import { ProjectionStore } from "./projectionStore.js";

/** Renderer mapping only. Backend rows already contain transformed OHLC and
 * source lineage; this adapter never runs a synthetic algorithm. */
export class BackendProjectionStore extends ProjectionStore {
  configurationKey: string;
  constructor(private binding: SyntheticChartBinding) {
    super({ projector: { id: "backend", oneToOne: false, project: () => binding.rows() } });
    this.configurationKey = binding.configurationKey;
  }
  override reset(rows: readonly SourceBar[] = []) {
    this.configurationKey = this.binding.configurationKey;
    return super.reset(rows);
  }
  override applySourceDelta(_delta: ProjectionSourceDelta | null | undefined, rows: readonly SourceBar[] = []) {
    return this.reset(rows);
  }
}
