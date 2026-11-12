/** Offline migration oracle only; never used by the backend production path. */
import { createConfiguredProjectionStore } from "../src/features/chart-representation/configuredProjectionStore.js";
import type { MainChartType } from "../src/shared/mainChartTypes.js";
import type { SourceBar } from "../src/features/chart-representation/chartRepresentationTypes.js";
let input = "";
for await (const chunk of process.stdin) input += String(chunk);
const cases = JSON.parse(input) as Array<{ transform: MainChartType; settings: { mode?: "traditional" | "atr"; boxSize?: number; atrLength?: number }; rows: SourceBar[] }>;
const results = cases.map(item => {
  const store = createConfiguredProjectionStore(item.transform, item.rows, item.settings);
  store.reset(item.rows);
  return store.displaySnapshot();
});
process.stdout.write(JSON.stringify(results));
