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
