import { ReplayDataManager } from "../../replay/replayDataManager.js";

/** Common lifecycle owner without live feeds, transports, or wall-clock IO.
 * The live MarketDataManager extends this core; replay roots use it directly. */
export class MarketDataManagerCore {
  readonly replay = new ReplayDataManager();
  diagnostics() { return { replay: this.replay.diagnostics() }; }
  closeAll(): void { this.replay.dispose(); }
}
