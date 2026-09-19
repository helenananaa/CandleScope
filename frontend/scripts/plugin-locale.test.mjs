import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL(
  "../../packages/candlescope-plugin-pyne-workbench/src/candlescope_plugin_pyne_workbench/web/app.js",
  import.meta.url,
), "utf8");

const NEW_HOST_LOCALES = [
  {
    id: "de",
    regional: "de-DE",
    scanner: {
      scan: "Autorisierte Märkte scannen",
      interval: ["1 Minute", "5 Minuten", "1 Stunde"],
      symbol: "Symbol",
      emptyState: "Führen Sie den Scanner aus, um Ergebnisse anzuzeigen",
    },
    workbench: {
      run: "Pyne auf dem aktuellen Chart ausführen",
      view: "Pyne-Werkbank",
    },
  },
  {
    id: "it",
    regional: "it-IT",
    scanner: {
      scan: "Scansiona i mercati autorizzati",
      interval: ["1 minuto", "5 minuti", "1 ora"],
      symbol: "Simbolo",
      emptyState: "Esegui lo scanner per visualizzare i risultati qui",
    },
    workbench: {
      run: "Esegui Pyne sul grafico attuale",
      view: "Banco di lavoro Pyne",
    },
  },
  {
    id: "id",
    regional: "id-ID",
    scanner: {
      scan: "Pindai pasar yang diizinkan",
      interval: ["1 menit", "5 menit", "1 jam"],
      symbol: "Simbol",
      emptyState: "Jalankan pemindai untuk menampilkan hasil di sini",
    },
    workbench: {
      run: "Jalankan Pyne pada grafik saat ini",
      view: "Meja kerja Pyne",
    },
  },
  {
    id: "tr",
    regional: "tr-TR",
    scanner: {
      scan: "Yetkili piyasaları tara",
      interval: ["1 dakika", "5 dakika", "1 saat"],
      symbol: "Sembol",
      emptyState: "Sonuçları burada görmek için tarayıcıyı çalıştırın",
    },
    workbench: {
      run: "Geçerli grafikte Pyne çalıştır",
      view: "Pyne çalışma tezgâhı",
    },
  },
  {
    id: "vi",
    regional: "vi-VN",
    scanner: {
      scan: "Quét các thị trường được ủy quyền",
      interval: ["1 phút", "5 phút", "1 giờ"],
      symbol: "Mã",
      emptyState: "Chạy bộ quét để hiển thị kết quả tại đây",
    },
    workbench: {
      run: "Chạy Pyne trên biểu đồ hiện tại",
      view: "Bàn làm việc Pyne",
    },
  },
  {
    id: "pl",
    regional: "pl-PL",
    scanner: {
      scan: "Skanuj autoryzowane rynki",
      interval: ["1 minuta", "5 minut", "1 godzina"],
      symbol: "Symbol",
      emptyState: "Uruchom skaner, aby wyświetlić wyniki",
    },
    workbench: {
      run: "Uruchom Pyne na bieżącym wykresie",
      view: "Warsztat Pyne",
    },
  },
];

test("first-party plugins ship de/it/id/tr/vi/pl copy for every owned surface", () => {
  const scanner = JSON.parse(fs.readFileSync(new URL(
    "../../packages/candlescope-plugin-market-scanner/src/candlescope_plugin_market_scanner/manifest.json",
    import.meta.url,
  ), "utf8"));
  const workbench = JSON.parse(fs.readFileSync(new URL(
    "../../packages/candlescope-plugin-pyne-workbench/src/candlescope_plugin_pyne_workbench/manifest.json",
    import.meta.url,
  ), "utf8"));
  const scannerById = Object.fromEntries(scanner.contributions.map((item) => [item.id, item]));
  const workbenchById = Object.fromEntries(workbench.contributions.map((item) => [item.id, item]));
  const englishInterval = scannerById.settings.configuration.schema.properties.interval.enum;
  for (const locale of NEW_HOST_LOCALES) {
    const id = locale.id;
    for (const item of scanner.contributions) {
      assert.ok(item.configuration.localizations[id], `${item.id} missing ${id}`);
      assert.ok(item.configuration.localizations[id].title);
    }
    for (const item of workbench.contributions) {
      assert.ok(item.configuration.localizations[id], `${item.id} missing ${id}`);
      assert.ok(item.configuration.localizations[id].title);
    }
    assert.equal(scannerById.scan.configuration.localizations[id].title, locale.scanner.scan);
    assert.deepEqual(
      scannerById.settings.configuration.localizations[id].schema.properties.interval.enumLabels,
      locale.scanner.interval,
    );
    assert.equal(
      scannerById.settings.configuration.localizations[id].schema.properties.interval.enumLabels.length,
      englishInterval.length,
    );
    assert.equal(scannerById.results.configuration.localizations[id].fields.symbol, locale.scanner.symbol);
    assert.equal(scannerById.results.configuration.localizations[id].emptyState, locale.scanner.emptyState);
    assert.equal(workbenchById.run.configuration.localizations[id].title, locale.workbench.run);
    assert.equal(workbenchById["workbench-view"].configuration.localizations[id].title, locale.workbench.view);
  }
});

test("first-party plugins ship Japanese manifest copy for owned surfaces", () => {
  const scanner = JSON.parse(fs.readFileSync(new URL(
    "../../packages/candlescope-plugin-market-scanner/src/candlescope_plugin_market_scanner/manifest.json",
    import.meta.url,
  ), "utf8"));
  const workbench = JSON.parse(fs.readFileSync(new URL(
    "../../packages/candlescope-plugin-pyne-workbench/src/candlescope_plugin_pyne_workbench/manifest.json",
    import.meta.url,
  ), "utf8"));
  const scannerById = Object.fromEntries(scanner.contributions.map((item) => [item.id, item]));
  const workbenchById = Object.fromEntries(workbench.contributions.map((item) => [item.id, item]));
  assert.equal(scannerById.scan.configuration.localizations.ja.title, "許可済み市場をスキャン");
  assert.deepEqual(
    scannerById.settings.configuration.localizations.ja.schema.properties.interval.enumLabels,
    ["1分", "5分", "1時間"],
  );
  assert.equal(scannerById.results.configuration.localizations.ja.fields.symbol, "銘柄");
  assert.equal(
    scannerById.results.configuration.localizations.ja.emptyState,
    "スキャナーを実行すると結果が表示されます",
  );
  assert.equal(workbenchById.run.configuration.localizations.ja.title, "現在のチャートで Pyne を実行");
  assert.equal(workbenchById["workbench-view"].configuration.localizations.ja.title, "Pyne ワークベンチ");
});

test("Pyne sandbox follows locale lifecycle updates and falls back to its own English catalog", () => {
  const title = { dataset: { i18n: "title" }, textContent: "" };
  const status = { dataset: { i18n: "statusWaiting" }, textContent: "" };
  const elements = { "#status": status, "#market": {}, "#theme": {} };
  const document = {
    title: "Pyne Workbench",
    documentElement: { lang: "zh-CN", dataset: {} },
    querySelector: (selector) => elements[selector],
    querySelectorAll: () => [title, status],
  };
  const parent = {};
  let connect;
  const channel = { start() {}, close() {}, postMessage() {}, onmessage: null };
  vm.runInNewContext(source, {
    document,
    parent,
    window: { addEventListener: (_type, listener) => { connect = listener; } },
  });
  const payload = (locale) => ({
    locale, theme: "dark", state: "active",
    market: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
  });
  connect({
    source: parent,
    ports: [channel],
    data: { protocol: "candlescope.ui-bridge/1", type: "host.connect", sequence: 1, payload: payload("nl") },
  });
  assert.equal(document.documentElement.lang, "en");
  assert.equal(title.textContent, "Pyne Workbench");
  let sequence = 1;
  for (const [requested, expected, label, connected] of [
    ["zh-CN", "zh-CN", "Pyne 工作台"],
    ["zh-TW", "zh-TW", "Pyne 工作台", "已連線 · 命令從外掛面板執行"],
    ["EN-us", "en", "Pyne Workbench"],
    ["es", "es", "Banco de trabajo Pyne"],
    ["es-MX", "es", "Banco de trabajo Pyne"],
    ["es-ES", "es", "Banco de trabajo Pyne"],
    ["fr-CA", "fr", "Atelier Pyne"],
    ["ja-JP", "ja", "Pyne ワークベンチ"],
    ["ko-KR", "ko", "Pyne 작업대"],
    ["ko", "ko", "Pyne 작업대"],
    ["pt-BR", "pt-BR", "Pyne Workbench"],
    ["pt-br", "pt-BR", "Pyne Workbench"],
    ["PT-BR", "pt-BR", "Pyne Workbench"],
    ["pt", "en", "Pyne Workbench"],
    ["pt-PT", "en", "Pyne Workbench"],
    ["ru", "ru", "Верстак Pyne"],
    ["ru-RU", "ru", "Верстак Pyne"],
    ["de", "de", "Pyne-Werkbank"],
    ["de-DE", "de", "Pyne-Werkbank", "Verbunden · führen Sie Befehle über das Plugin-Panel aus"],
    ["it", "it", "Banco di lavoro Pyne"],
    ["it-IT", "it", "Banco di lavoro Pyne"],
    ["id", "id", "Meja kerja Pyne"],
    ["id-ID", "id", "Meja kerja Pyne"],
    ["tr", "tr", "Pyne çalışma tezgâhı"],
    ["tr-TR", "tr", "Pyne çalışma tezgâhı"],
    ["vi", "vi", "Bàn làm việc Pyne"],
    ["vi-VN", "vi", "Bàn làm việc Pyne"],
    ["pl", "pl", "Warsztat Pyne"],
    ["pl-PL", "pl", "Warsztat Pyne"],
  ]) {
    channel.onmessage({ data: {
      protocol: "candlescope.ui-bridge/1", type: "host.lifecycle",
      sequence: ++sequence, payload: payload(requested),
    } });
    assert.equal(document.documentElement.lang, expected);
    assert.equal(title.textContent, label);
    if (connected !== undefined) assert.equal(status.textContent, connected);
  }
});

test("Pyne sandbox new host locales translate every owned message key", () => {
  const keys = [
    "title", "statusWaiting", "statusRejected", "statusConnected", "statusDisposed",
    "howTo", "stepOpenChart", "stepRunCommand", "stepDebug",
    "boundaryTitle", "boundaryBody", "mainChart", "theme",
  ];
  const elements = Object.fromEntries(keys.map((key) => [
    key,
    { dataset: { i18n: key }, textContent: "" },
  ]));
  const status = { dataset: { i18n: "statusWaiting" }, textContent: "" };
  const document = {
    title: "Pyne Workbench",
    documentElement: { lang: "zh-CN", dataset: {} },
    querySelector: (selector) => ({ "#status": status, "#market": {}, "#theme": {} }[selector]),
    querySelectorAll: () => [...Object.values(elements), status],
  };
  const parent = {};
  let connect;
  const channel = { start() {}, close() {}, postMessage() {}, onmessage: null };
  vm.runInNewContext(source, {
    document,
    parent,
    window: { addEventListener: (_type, listener) => { connect = listener; } },
  });
  const payload = (locale) => ({
    locale, theme: "dark", state: "active",
    market: { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" },
  });
  connect({
    source: parent,
    ports: [channel],
    data: { protocol: "candlescope.ui-bridge/1", type: "host.connect", sequence: 1, payload: payload("en") },
  });
  const english = Object.fromEntries(keys.map((key) => [key, elements[key].textContent]));
  assert.equal(english.title, "Pyne Workbench");
  assert.match(english.boundaryBody, /Render IR v2/);
  assert.match(english.boundaryBody, /candle/);
  assert.match(english.boundaryBody, /table/);
  assert.match(english.boundaryBody, /linefill/);
  let sequence = 1;
  for (const locale of NEW_HOST_LOCALES) {
    for (const requested of [locale.id, locale.regional]) {
      channel.onmessage({ data: {
        protocol: "candlescope.ui-bridge/1", type: "host.lifecycle",
        sequence: ++sequence, payload: payload(requested),
      } });
      assert.equal(document.documentElement.lang, locale.id);
      assert.equal(elements.title.textContent, locale.workbench.view);
      for (const key of keys) {
        const value = elements[key].textContent;
        assert.ok(value, `${locale.id} missing ${key}`);
        assert.notEqual(value, key);
        if (key !== "title") assert.notEqual(value, english[key], `${locale.id} left ${key} in English`);
      }
      assert.match(elements.boundaryBody.textContent, /Render IR v2/);
      assert.match(elements.boundaryBody.textContent, /candle/);
      assert.match(elements.boundaryBody.textContent, /table/);
      assert.match(elements.boundaryBody.textContent, /linefill/);
    }
  }
});
