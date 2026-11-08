import { stripIndicatorRuntimeFields, type ActiveIndicatorPersistence } from "../indicators/activeIndicatorStore.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyStorage } from "../../shared/strategyStorage.js";

const storageKey = "candlescope:research-indicator-scopes:v1";
const maxStudies = 8;
const maxStorageBytes = 128 * 1024;
export const MAX_STUDY_DATASETS = 8;

export interface StudyDataset {
  dataset_id: string;
  data_epoch: string;
  name: string;
  interval: string;
}

interface StudyScope {
  indicator: IndicatorDefinition;
  datasets: StudyDataset[];
}

interface StudyScopeState {
  scopes: readonly StudyScope[];
  storageError: boolean;
}

export function studyDatasetKey(dataset: Pick<StudyDataset, "dataset_id" | "data_epoch">): string {
  return JSON.stringify([dataset.dataset_id, dataset.data_epoch]);
}

function validDataset(dataset: StudyDataset): boolean {
  return !!dataset && [dataset.dataset_id, dataset.data_epoch, dataset.name, dataset.interval]
    .every(value => typeof value === "string" && value.length > 0 && value.length <= 256);
}

function validIndicator(indicator: IndicatorDefinition): boolean {
  return !!indicator && indicator.is_builtin === true && typeof indicator.id === "string"
    && indicator.id.length > 0 && indicator.id.length <= 128
    && typeof indicator.engineName === "string" && indicator.engineName.length > 0;
}

function readScopes(storage: StrategyStorage): StudyScope[] {
  const raw = storage.getItem(storageKey);
  if (raw === null) return [];
  if (new TextEncoder().encode(raw).byteLength > maxStorageBytes) throw new Error("RESEARCH_INDICATOR_SCOPE_STORAGE_INVALID");
  const data = JSON.parse(raw) as { schema?: number; scopes?: StudyScope[] } | null;
  if (data?.schema !== 1 || !Array.isArray(data.scopes) || data.scopes.length > maxStudies
      || data.scopes.some(scope => !scope || !validIndicator(scope.indicator)
        || !Array.isArray(scope.datasets) || scope.datasets.length < 1 || scope.datasets.length > MAX_STUDY_DATASETS
        || !scope.datasets.every(validDataset) || new Set(scope.datasets.map(studyDatasetKey)).size !== scope.datasets.length)
      || new Set(data.scopes.map(scope => scope.indicator.id)).size !== data.scopes.length) {
    throw new Error("RESEARCH_INDICATOR_SCOPE_STORAGE_INVALID");
  }
  return data.scopes;
}

export class ResearchIndicatorScopeStore {
  private state: StudyScopeState;
  private readonly listeners = new Set<() => void>();
  private writes = Promise.resolve();
  private persistedScopes: readonly StudyScope[] = [];

  constructor(private readonly storage: StrategyStorage | null) {
    try {
      if (!storage) throw new Error("RESEARCH_INDICATOR_SCOPE_STORAGE_UNAVAILABLE");
      this.persistedScopes = readScopes(storage);
      this.state = { scopes: this.persistedScopes, storageError: false };
    } catch {
      this.state = { scopes: [], storageError: true };
    }
  }

  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private publish(state: StudyScopeState) {
    this.state = state;
    this.listeners.forEach(listener => listener());
  }

  private replace(scopes: readonly StudyScope[]): Promise<void> {
    if (!this.storage || this.state.storageError) throw new Error("RESEARCH_INDICATOR_SCOPE_STORAGE_UNAVAILABLE");
    const storage = this.storage;
    const wire = JSON.stringify({ schema: 1, scopes });
    if (new TextEncoder().encode(wire).byteLength > maxStorageBytes) throw new Error("RESEARCH_INDICATOR_SCOPE_CAPACITY");
    this.publish({ scopes, storageError: false });
    const pending = this.writes.then(async () => {
      if (this.state.storageError) throw new Error("RESEARCH_INDICATOR_SCOPE_STORAGE_UNAVAILABLE");
      await storage.setItem(storageKey, wire);
      this.persistedScopes = scopes;
    });
    this.writes = pending.catch(() => this.publish({ scopes: this.persistedScopes, storageError: true }));
    return pending;
  }

  async apply(indicator: IndicatorDefinition, current: LocalDatasetManifest, selected: readonly LocalDatasetManifest[],
    local: ActiveIndicatorPersistence): Promise<void> {
    const datasets = selected.map(({ dataset_id, data_epoch, name, interval }) => ({ dataset_id, data_epoch, name, interval }));
    if (!validIndicator(indicator) || datasets.length < 2 || datasets.length > MAX_STUDY_DATASETS
      || !datasets.every(validDataset) || new Set(datasets.map(studyDatasetKey)).size !== datasets.length
      || !datasets.some(dataset => studyDatasetKey(dataset) === studyDatasetKey(current))) {
      throw new Error("RESEARCH_INDICATOR_SCOPE_INVALID");
    }
    const currentScopes = this.state.scopes;
    const position = currentScopes.findIndex(scope => scope.indicator.id === indicator.id);
    if (position === -1 && currentScopes.length >= maxStudies) throw new Error("RESEARCH_INDICATOR_SCOPE_CAPACITY");
    const scope = { indicator: stripIndicatorRuntimeFields(indicator), datasets };
    await this.replace(position === -1 ? [...currentScopes, scope] : currentScopes.map((item, index) => index === position ? scope : item));
    local.save(local.load().filter(item => item.id !== indicator.id));
  }

  chartPersistence(dataset: StudyDataset, scopes: readonly StudyScope[], local: ActiveIndicatorPersistence): ActiveIndicatorPersistence {
    const key = studyDatasetKey(dataset);
    const matching = (scope: StudyScope) => scope.datasets.some(target => studyDatasetKey(target) === key);
    return {
      controlled: true,
      load: () => {
        const shared = scopes.filter(matching).map(scope => scope.indicator);
        const sharedIds = new Set(shared.map(indicator => indicator.id));
        return [...local.load().filter(indicator => !sharedIds.has(indicator.id)), ...shared];
      },
      save: (definitions) => {
        const current = this.state.scopes;
        const owned = new Map(current.filter(matching).map(scope => [scope.indicator.id, scope]));
        if (!this.state.storageError && owned.size > 0) {
          const byId = new Map(definitions.map(indicator => [indicator.id, indicator]));
          const next = current.flatMap(scope => {
            if (!owned.has(scope.indicator.id)) return [scope];
            const indicator = byId.get(scope.indicator.id);
            if (indicator) {
              const definition = stripIndicatorRuntimeFields(indicator);
              return [JSON.stringify(scope.indicator) === JSON.stringify(definition) ? scope : { ...scope, indicator: definition }];
            }
            const datasets = scope.datasets.filter(target => studyDatasetKey(target) !== key);
            return datasets.length ? [{ ...scope, datasets }] : [];
          });
          if (next.length !== current.length || next.some((scope, index) => scope !== current[index])) {
            try { void this.replace(next).catch(() => {}); }
            catch { this.publish({ ...this.state, storageError: true }); }
          }
        }
        local.save(definitions.filter(indicator => !owned.has(indicator.id)));
      },
    };
  }
}
