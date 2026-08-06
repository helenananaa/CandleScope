import type { IndicatorRuntime } from "../indicators/indicatorRuntimeContract.js";
import type { IndicatorParameterSchema, IndicatorParams } from "../indicators/indicatorTypes.js";
import type { LocalDatasetManifest } from "./localDataTypes.js";
import {
  createLocalIndicatorDefinition,
  LOCAL_INDICATOR_CATALOG,
  localIndicatorCatalogEntry,
} from "./localIndicatorCatalog.js";


function schemaKey(schema: IndicatorParameterSchema): string {
  return schema.key ?? schema.name ?? "";
}

function ParameterEditor({
  schema,
  value,
  onChange,
}: {
  schema: IndicatorParameterSchema;
  value: unknown;
  onChange(value: unknown): void;
}) {
  const key = schemaKey(schema);
  if (schema.type === "color") {
    return (
      <label className="local-indicator-color-field">
        <span>{schema.label ?? key}</span>
        <input type="color" value={String(value ?? schema.default)} onChange={(event) => onChange(event.target.value)} />
      </label>
    );
  }
  if (schema.options) {
    return (
      <label>
        <span>{schema.label ?? key}</span>
        <select value={String(value ?? schema.default)} onChange={(event) => onChange(event.target.value)}>
          {schema.options.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label>
      <span>{schema.label ?? key}</span>
      <input
        type="number"
        value={typeof value === "number" ? value : Number(schema.default ?? 0)}
        min={schema.min}
        max={schema.max}
        step={schema.type === "int" ? 1 : schema.step ?? "any"}
        onChange={(event) => {
          if (event.target.value === "") return;
          const parsed = schema.type === "int"
            ? Number.parseInt(event.target.value, 10)
            : Number.parseFloat(event.target.value);
          if (Number.isFinite(parsed)) onChange(parsed);
        }}
      />
    </label>
  );
}

export default function LocalIndicatorPanel({
  manifest,
  runtime,
}: {
  manifest: LocalDatasetManifest;
  runtime: IndicatorRuntime;
}) {
  return (
    <section className="local-indicator-panel" aria-label="本地静态指标">
      <header>
        <div>
          <span>INDICATORS</span>
          <strong>静态本地指标</strong>
        </div>
        <small>{runtime.status.computing ? "计算中…" : `${runtime.view.activeIndicators.length} 个`}</small>
      </header>
      <p className="local-indicator-truth">
        只读取当前 dataEpoch 的已导入行；不联网、不回填，数据缺口保持原样。
        {!manifest.volume_available && " 当前为 OHLC-only，成交量指标不可用。"}
      </p>
      <div className="local-indicator-catalog">
        {LOCAL_INDICATOR_CATALOG.map((entry) => (
          <button
            type="button"
            key={entry.engineName}
            title={entry.description}
            disabled={runtime.view.activeIndicators.length >= 32}
            onClick={() => runtime.actions.addIndicator(createLocalIndicatorDefinition(entry.engineName))}
          >
            <strong>＋ {entry.shortName}</strong>
            <small>{entry.paneTarget === "main" ? "主图" : "副图"}</small>
          </button>
        ))}
      </div>
      {runtime.view.activeIndicators.length === 0 ? (
        <div className="local-indicator-empty">添加 MA、EMA、RSI、MACD 或 BOLL 后，结果会直接画在当前 CSV 图表上。</div>
      ) : (
        <div className="local-indicator-active-list">
          {runtime.view.activeIndicators.map((indicator) => {
            const entry = localIndicatorCatalogEntry(indicator.engineName);
            if (entry === null) return null;
            const params: IndicatorParams = indicator.params ?? {};
            return (
              <article key={indicator.id} className={indicator.error ? "error" : ""}>
                <div className="local-indicator-active-head">
                  <span><strong>{entry.shortName}</strong><small>{entry.name}</small></span>
                  <span>
                    <button type="button" onClick={() => runtime.actions.toggleVisibility(indicator.id)}>
                      {indicator.visible ? "隐藏" : "显示"}
                    </button>
                    <button type="button" className="danger" onClick={() => runtime.actions.removeIndicator(indicator.id)}>删除</button>
                  </span>
                </div>
                <div className="local-indicator-params">
                  {entry.paramSchema.map((schema) => {
                    const key = schemaKey(schema);
                    return (
                      <ParameterEditor
                        key={key}
                        schema={schema}
                        value={params[key]}
                        onChange={(value) => runtime.actions.updateIndicatorParams(
                          indicator.id,
                          { ...params, [key]: value },
                        )}
                      />
                    );
                  })}
                </div>
                {indicator.error && <p role="alert">{indicator.error}</p>}
              </article>
            );
          })}
        </div>
      )}
      <button
        type="button"
        className="local-indicator-recompute"
        disabled={runtime.status.computing || runtime.view.activeIndicators.length === 0}
        onClick={() => runtime.actions.recompute(true)}
      >
        {runtime.status.computing ? "正在重新计算…" : "重新计算当前指标"}
      </button>
    </section>
  );
}
