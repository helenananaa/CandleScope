import assert from "node:assert/strict";
import test from "node:test";
import { loadLocaleCatalog } from "../../../i18n/registry.js";
import { getLocale, setLocale } from "../../../i18n/index.js";
import { trainingRunStatusLabel } from "../trainingHubLabels.js";

test.before(async () => { await loadLocaleCatalog("fr"); });

const SERVER_READY = "训练可继续";

function withLocale(locale: "en" | "fr" | "zh-CN", run: () => void): void {
  const previous = getLocale();
  setLocale(locale);
  try { run(); } finally { setLocale(previous); }
}

test("known status codes show the reader's language, not the server's Chinese text", () => {
  const card = { state: "PAUSED", resume_action: "OPEN_ADAPTER", status: { code: "READY", message: SERVER_READY } } as const;
  withLocale("en", () => {
    assert.equal(trainingRunStatusLabel(card), "Training can continue");
    assert.equal(
      trainingRunStatusLabel({ ...card, state: "AWAITING_MARKET", status: { code: "AWAITING_MARKET", message: "回放已创建，请选择第一个商品。" } }),
      "Replay created; select its first symbol.",
    );
    assert.match(trainingRunStatusLabel({ ...card, resume_action: "UNAVAILABLE", status: { code: "UNAVAILABLE", message: "存档当前不可恢复" } }), /^This archive cannot be restored/);
    assert.match(trainingRunStatusLabel({ ...card, status: { code: "HEDGE_INPUT_RECOVERY_REQUIRED", message: "输入时间线需要恢复" } }), /^The input timeline needs recovery/);
  });
  withLocale("fr", () => assert.equal(trainingRunStatusLabel(card), "L’entraînement peut reprendre"));
  withLocale("zh-CN", () => assert.equal(trainingRunStatusLabel(card), SERVER_READY));
});

test("an unknown status code shows the server's message as sent", () => {
  withLocale("en", () => {
    assert.equal(
      trainingRunStatusLabel({ state: "PAUSED", resume_action: "OPEN_ADAPTER", status: { code: "SOMETHING_NEW", message: "服务端新状态" } }),
      "服务端新状态",
    );
  });
});

test("an ended run is described by whether its review opens, whatever its stored status says", () => {
  withLocale("en", () => {
    const ended = { state: "ENDED", status: { code: "READY", message: `STALE: ${SERVER_READY}` } } as const;
    assert.equal(trainingRunStatusLabel({ ...ended, resume_action: "OPEN_ADAPTER" }), "Training ended; review is available.");
    assert.equal(trainingRunStatusLabel({ ...ended, resume_action: "UNAVAILABLE" }), "Training ended; this archive cannot open review.");
  });
});
