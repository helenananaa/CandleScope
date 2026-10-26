import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";


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
  },
];

test("first-party plugins ship de/it/id/tr/vi/pl copy for every owned surface", () => {
  const scanner = JSON.parse(fs.readFileSync(new URL(
    "../../packages/candlescope-plugin-market-scanner/src/candlescope_plugin_market_scanner/manifest.json",
    import.meta.url,
  ), "utf8"));
  const scannerById = Object.fromEntries(scanner.contributions.map((item) => [item.id, item]));
  const englishInterval = scannerById.settings.configuration.schema.properties.interval.enum;
  for (const locale of NEW_HOST_LOCALES) {
    const id = locale.id;
    for (const item of scanner.contributions) {
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
  }
});

test("first-party plugins ship Japanese manifest copy for owned surfaces", () => {
  const scanner = JSON.parse(fs.readFileSync(new URL(
    "../../packages/candlescope-plugin-market-scanner/src/candlescope_plugin_market_scanner/manifest.json",
    import.meta.url,
  ), "utf8"));
  const scannerById = Object.fromEntries(scanner.contributions.map((item) => [item.id, item]));
  assert.equal(scannerById.scan.configuration.localizations.ja.title, "許可済み市場をスキャン");
  assert.equal(scannerById.scan.configuration.localizations.th.title, "สแกนตลาดที่ได้รับอนุญาต");
  assert.equal(scannerById.scan.configuration.localizations.nl.title, "Geautoriseerde markten scannen");
  assert.equal(
    scannerById.results.configuration.localizations.th.emptyState,
    "เรียกใช้เครื่องสแกนแล้วผลลัพธ์จะแสดงที่นี่",
  );
  assert.equal(
    scannerById.results.configuration.localizations.nl.emptyState,
    "Voer de scanner uit om resultaten te tonen",
  );
  assert.equal(scannerById.scan.configuration.localizations.uk, undefined);
  assert.equal(Object.keys(scannerById.scan.configuration.localizations).length <= 16, true);
  assert.deepEqual(
    scannerById.settings.configuration.localizations.ja.schema.properties.interval.enumLabels,
    ["1分", "5分", "1時間"],
  );
  assert.equal(scannerById.results.configuration.localizations.ja.fields.symbol, "銘柄");
  assert.equal(
    scannerById.results.configuration.localizations.ja.emptyState,
    "スキャナーを実行すると結果が表示されます",
  );
});
