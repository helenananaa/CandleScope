import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../registry.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../index.js";
import { describeError, serverErrorKind } from "../serverErrors.js";

class CodedError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
  }
}

test("server error codes map to a summary kind by their wording", () => {
  assert.equal(serverErrorKind("TRAINING_RUN_NOT_FOUND"), "notFound");
  assert.equal(serverErrorKind("REPLAY_REVISION_CONFLICT"), "conflict");
  assert.equal(serverErrorKind("REPLAY_ENTRY_INVALID"), "invalid");
  assert.equal(serverErrorKind("NATIVE_RUNTIME_UNAVAILABLE"), "unavailable");
  assert.equal(serverErrorKind("REPLAY_V2_TRANSPORT_ERROR"), "network");
  assert.equal(serverErrorKind("REQUEST_TIMEOUT"), "timeout");
  assert.equal(serverErrorKind("CONTROLLER_LOCKED"), "forbidden");
  assert.equal(serverErrorKind("SOMETHING_ELSE"), "generic");
});

test("coded errors get a localized summary and keep the server text as detail", () => {
  setLocale("zh-CN");
  const text = describeError(new CodedError("TRAINING_RUN_NOT_FOUND", "training run does not exist"), "fallback");
  assert.equal(text, "请求的内容不存在，可能已被删除（training run does not exist）");
  setLocale("en");
  assert.equal(
    describeError(new CodedError("TRAINING_RUN_NOT_FOUND", "training run does not exist"), "fallback"),
    "The requested item doesn't exist or was deleted (training run does not exist)",
  );
});

test("errors without a backend code keep their message, and non-errors use the fallback", () => {
  setLocale("zh-CN");
  assert.equal(describeError(new Error("plain failure"), "fallback"), "plain failure");
  assert.equal(describeError(new CodedError("lowercase-code", "kept"), "fallback"), "kept");
  assert.equal(describeError("not an error", "fallback"), "fallback");
});

test("a code with its own message shows only that message, without the English server text", () => {
  setLocale("zh-CN");
  const boundary = new CodedError("HISTORY_ORIGIN_UNAVAILABLE", "Could not read the provider history boundary");
  assert.equal(describeError(boundary, "fallback"), "暂时无法读取交易所的历史起点，请稍后重试");
  assert.doesNotMatch(describeError(new CodedError("SUBSCRIBE_FAILED", "trade-flow subscription rejected"), "fallback"), /[A-Za-z]/);
  setLocale("en");
  assert.equal(describeError(boundary, "fallback"), "Couldn't read where the exchange's history begins. Try again shortly.");
});

class HttpError extends Error {
  constructor(readonly status: number, message: string, readonly code: string | null = null) {
    super(message);
  }
}

test("a coded error's JSON detail shows only its message", () => {
  setLocale("en");
  const detail = JSON.stringify({ code: "TRAINING_RUN_NOT_FOUND", message: "training run does not exist" });
  assert.equal(
    describeError(new HttpError(404, detail, "TRAINING_RUN_NOT_FOUND"), "fallback"),
    "The requested item doesn't exist or was deleted (training run does not exist)",
  );
});

test("uncoded HTTP errors get a summary by status, with the backend message as detail", () => {
  setLocale("zh-CN");
  assert.equal(describeError(new HttpError(404, "Not found"), "fallback"), "请求的内容不存在，可能已被删除（Not found）");
  assert.equal(describeError(new HttpError(503, "HTTP 503"), "fallback"), "该功能当前不可用");
  assert.equal(describeError(new HttpError(500, "boom"), "fallback"), "操作失败（boom）");
  setLocale("en");
  assert.equal(describeError(new HttpError(409, "No metadata changes were provided"), "fallback"),
    "This was changed elsewhere. Refresh and try again (No metadata changes were provided)");
});

test("a service that has not started yet, and a request that never arrived, read as such", () => {
  setLocale("zh-CN");
  assert.equal(describeError(new HttpError(503, "DataManager 尚未初始化"), "fallback"), "本地服务仍在启动，请稍后重试");
  setLocale("en");
  assert.equal(describeError(new HttpError(503, "Order-book service is not initialized"), "fallback"),
    "The local service is still starting. Try again shortly");
  assert.equal(describeError(new TypeError("Failed to fetch"), "fallback"), "Can't reach the local service");
  assert.equal(describeError(new TypeError("Load failed"), "fallback"), "Can't reach the local service");
  assert.equal(describeError(new TypeError("x is not a function"), "fallback"), "x is not a function");
});

test("a message that repeats its code drops it, and a bare HTTP status adds no detail", () => {
  setLocale("zh-CN");
  const repeated = describeError(new CodedError("DATA_SNAPSHOT_MISMATCH", "DATA_SNAPSHOT_MISMATCH: saved order has an invalid boundary"), "fallback");
  assert.match(repeated, /（saved order has an invalid boundary）$/);
  assert.doesNotMatch(repeated, /DATA_SNAPSHOT_MISMATCH/);
  // An uncoded failure of the backtest service: the client names it, the summary says what it means.
  assert.equal(describeError(new HttpError(503, "BACKTEST_API_UNAVAILABLE: HTTP 503", "BACKTEST_API_UNAVAILABLE"), "fallback"), "该功能当前不可用");
});
