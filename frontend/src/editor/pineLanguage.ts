import type * as Monaco from "monaco-editor";

const PINE_LANGUAGE_ID = "pine";

const KEYWORDS = [
  "and", "as", "bool", "break", "by", "color", "const", "continue",
  "else", "enum", "export", "false", "float", "for", "if", "import",
  "in", "indicator", "int", "library", "map", "matrix", "method", "na",
  "not", "or", "series", "simple", "strategy", "string", "switch", "true",
  "type", "var", "varip", "while",
];

const BUILTINS = [
  "open", "high", "low", "close", "volume", "time", "bar_index",
  "plot", "plotchar", "plotshape", "plotarrow", "hline", "fill", "bgcolor",
  "barcolor", "alert", "alertcondition", "input", "ta", "math", "color",
];

export function registerPineLanguageSupport(monaco: typeof Monaco): void {
  if (!monaco.languages.getLanguages().some((language) => language.id === PINE_LANGUAGE_ID)) {
    monaco.languages.register({
      id: PINE_LANGUAGE_ID,
      aliases: ["Pine", "Pine Script"],
      extensions: [".pine"],
    });
  }

  monaco.languages.setLanguageConfiguration(PINE_LANGUAGE_ID, {
    comments: { lineComment: "//" },
    brackets: [["{", "}"], ["[", "]"], ["(", ")"]],
    autoClosingPairs: [
      { open: "{", close: "}" },
      { open: "[", close: "]" },
      { open: "(", close: ")" },
      { open: '"', close: '"' },
    ],
    surroundingPairs: [
      { open: "{", close: "}" },
      { open: "[", close: "]" },
      { open: "(", close: ")" },
      { open: '"', close: '"' },
    ],
  });

  monaco.languages.setMonarchTokensProvider(PINE_LANGUAGE_ID, {
    keywords: KEYWORDS,
    builtins: BUILTINS,
    tokenizer: {
      root: [
        [/^\s*\/\/@version=\d+/, "metatag"],
        [/\/\/.*$/, "comment"],
        [/[a-zA-Z_]\w*/, {
          cases: {
            "@keywords": "keyword",
            "@builtins": "type.identifier",
            "@default": "identifier",
          },
        }],
        [/\d+\.\d+([eE][-+]?\d+)?/, "number.float"],
        [/\d+/, "number"],
        [/"([^"\\]|\\.)*$/, "string.invalid"],
        [/"/, { token: "string.quote", bracket: "@open", next: "@string" }],
        [/[{}()[\]]/, "@brackets"],
        [/[=><!~?:&|+*/%^-]+/, "operator"],
        [/[;,.]/, "delimiter"],
      ],
      string: [
        [/[^\\"]+/, "string"],
        [/\\./, "string.escape.invalid"],
        [/"/, { token: "string.quote", bracket: "@close", next: "@pop" }],
      ],
    },
  });

  monaco.languages.registerCompletionItemProvider(PINE_LANGUAGE_ID, {
    triggerCharacters: ["."],
    provideCompletionItems(model, position) {
      const range = model.getWordUntilPosition(position);
      const suggestions = [...KEYWORDS, ...BUILTINS].map((label) => ({
        label,
        kind: monaco.languages.CompletionItemKind.Keyword,
        insertText: label,
        range: {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: range.startColumn,
          endColumn: range.endColumn,
        },
      }));
      return { suggestions };
    },
  });
}
