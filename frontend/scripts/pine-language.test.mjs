import assert from "node:assert/strict";
import test from "node:test";

import monarchCompile from "monaco-editor/esm/vs/editor/standalone/common/monarch/monarchCompile.js";

import { registerPineLanguageSupport } from "../src/editor/pineLanguage.ts";

const { compile } = monarchCompile;

test("Pine language registration compiles its Monarch tokenizer", () => {
  const registeredLanguages = [];
  const monaco = {
    languages: {
      getLanguages: () => registeredLanguages,
      register: (language) => registeredLanguages.push(language),
      setLanguageConfiguration: () => {},
      setMonarchTokensProvider: (languageId, definition) => {
        compile(languageId, definition);
      },
      registerCompletionItemProvider: () => {},
    },
  };

  assert.doesNotThrow(() => registerPineLanguageSupport(monaco));
  assert.deepEqual(registeredLanguages.map(({ id }) => id), ["pine"]);
});
