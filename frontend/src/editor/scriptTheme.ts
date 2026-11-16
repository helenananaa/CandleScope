/**
 * Script editor themes — dark and light themes for the CandleScope script editors
 * (indicators and strategies), following the app theme.
 *
 * Highlights Script keywords (ta, input, color, plot, etc.)
 * with distinctive colors to make scripts more readable.
 */

import { useEffect, useState } from "react";
import type * as Monaco from "monaco-editor";
import { bindExtensionEditorTheme } from "./extensionTheme.js";

export const SCRIPT_THEME_DARK = "script-dark";
export const SCRIPT_THEME_LIGHT = "script-light";

/**
 * Light counterpart of the dark theme: the light surface and text tokens, and syntax colours
 * that keep WCAG AA (4.5:1) on white.
 */
const LIGHT_THEME: Monaco.editor.IStandaloneThemeData = {
  base: "vs",
  inherit: true,
  rules: [
    { token: "keyword", foreground: "a626a4" },
    { token: "keyword.control", foreground: "a626a4" },
    { token: "string", foreground: "a31515" },
    { token: "string.escape", foreground: "8a4a00" },
    { token: "number", foreground: "0b7a4b" },
    { token: "comment", foreground: "3f6b3f", fontStyle: "italic" },
    { token: "identifier", foreground: "0f4c81" },
    { token: "type", foreground: "1d6f7a" },
    { token: "operator", foreground: "17181b" },
    { token: "delimiter", foreground: "4a4d55" },
    { token: "tag", foreground: "0f5bbd" },
  ],
  colors: {
    "editor.background": "#ffffff",
    "editor.foreground": "#17181b",
    "editor.selectionBackground": "#0f5bbd33",
    "editor.inactiveSelectionBackground": "#0f5bbd1f",
    "editor.lineHighlightBackground": "#f0f1f3",
    "editor.lineHighlightBorder": "#00000000",
    "editorLineNumber.foreground": "#5b5f69",
    "editorLineNumber.activeForeground": "#17181b",
    "editorCursor.foreground": "#0f5bbd",
    "editorGutter.background": "#ffffff",
    "editorIndentGuide.background": "#e2e3e7",
    "editorIndentGuide.activeBackground": "#c8cad0",
    "editorBracketMatch.background": "#12703a22",
    "editorBracketMatch.border": "#12703a66",
    "editorWidget.background": "#f7f7f8",
    "editorWidget.border": "#c8cad0",
    "editorWidget.foreground": "#17181b",
    "editorSuggestWidget.background": "#f7f7f8",
    "editorSuggestWidget.border": "#c8cad0",
    "editorSuggestWidget.foreground": "#17181b",
    "editorSuggestWidget.highlightForeground": "#0f5bbd",
    "editorSuggestWidget.selectedBackground": "#0f5bbd22",
    "editorHoverWidget.background": "#f7f7f8",
    "editorHoverWidget.border": "#c8cad0",
    "editorHoverWidget.foreground": "#17181b",
    "scrollbarSlider.background": "#5b5f6933",
    "scrollbarSlider.hoverBackground": "#5b5f6955",
    "scrollbarSlider.activeBackground": "#5b5f6988",
    "minimap.background": "#ffffff",
  },
};

/** The script theme for the app theme: light when the document is in the light theme. */
export function scriptThemeForDocument(): string {
  return typeof document !== "undefined" && document.documentElement.dataset.theme === "light" ? SCRIPT_THEME_LIGHT : SCRIPT_THEME_DARK;
}

/** Follows the app theme (the document's data-theme) and returns the script editor theme to use. */
export function useScriptEditorTheme(): string {
  const [theme, setTheme] = useState(scriptThemeForDocument);
  useEffect(() => {
    const update = () => setTheme(scriptThemeForDocument());
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

/**
 * Define and register the script dark and light themes on a Monaco instance.
 *
 * @param {import('monaco-editor')} monaco
 */
export function registerScriptTheme(monaco: typeof Monaco): void {
  const theme: Monaco.editor.IStandaloneThemeData = {
    base: "vs-dark",
    inherit: true,
    rules: [
      // Python keywords
      { token: "keyword", foreground: "c586c0" }, // purple-pink
      { token: "keyword.control", foreground: "c586c0" },

      // Strings
      { token: "string", foreground: "ce9178" }, // warm orange
      { token: "string.escape", foreground: "d7ba7d" },

      // Numbers
      { token: "number", foreground: "b5cea8" }, // soft green

      // Comments
      { token: "comment", foreground: "6a9955", fontStyle: "italic" },

      // Functions / methods
      { token: "identifier", foreground: "9cdcfe" }, // light blue
      { token: "type", foreground: "4ec9b0" }, // teal

      // Operators
      { token: "operator", foreground: "d4d4d4" },
      { token: "delimiter", foreground: "d4d4d4" },

      // Decorators
      { token: "tag", foreground: "569cd6" }, // blue
    ],
    colors: {
      // Editor background
      "editor.background": "#0d1117",
      "editor.foreground": "#c9d1d9",

      // Selection
      "editor.selectionBackground": "#264f7833",
      "editor.inactiveSelectionBackground": "#264f7822",

      // Current line
      "editor.lineHighlightBackground": "#161b2233",
      "editor.lineHighlightBorder": "#00000000",

      // Line numbers
      "editorLineNumber.foreground": "#7d8590",
      "editorLineNumber.activeForeground": "#8b949e",

      // Cursor
      "editorCursor.foreground": "#58a6ff",

      // Gutter
      "editorGutter.background": "#0d1117",

      // Indent guides
      "editorIndentGuide.background": "#21262d",
      "editorIndentGuide.activeBackground": "#30363d",

      // Bracket matching
      "editorBracketMatch.background": "#3fb95033",
      "editorBracketMatch.border": "#3fb95066",

      // Widget (autocomplete dropdown)
      "editorWidget.background": "#161b22",
      "editorWidget.border": "#30363d",
      "editorWidget.foreground": "#c9d1d9",

      // Suggest widget (autocomplete)
      "editorSuggestWidget.background": "#161b22",
      "editorSuggestWidget.border": "#30363d",
      "editorSuggestWidget.foreground": "#c9d1d9",
      "editorSuggestWidget.highlightForeground": "#58a6ff",
      "editorSuggestWidget.selectedBackground": "#1f6feb33",

      // Hover widget
      "editorHoverWidget.background": "#161b22",
      "editorHoverWidget.border": "#30363d",
      "editorHoverWidget.foreground": "#c9d1d9",

      // Scrollbar
      "scrollbarSlider.background": "#484f5833",
      "scrollbarSlider.hoverBackground": "#484f5866",
      "scrollbarSlider.activeBackground": "#484f58aa",

      // Minimap (disabled but just in case)
      "minimap.background": "#0d1117",
    },
  };
  monaco.editor.defineTheme(SCRIPT_THEME_DARK, theme);
  monaco.editor.defineTheme(SCRIPT_THEME_LIGHT, LIGHT_THEME);
  bindExtensionEditorTheme(monaco);
}

/**
 * Get the Monaco editor options optimized for scripts.
 * Merges with any user-provided options.
 *
 * @param {object} [overrides] — Additional Monaco editor options
 * @returns {object} Monaco IStandaloneEditorConstructionOptions
 */
export function getScriptEditorOptions(
  overrides: Partial<Monaco.editor.IStandaloneEditorConstructionOptions> = {},
): Monaco.editor.IStandaloneEditorConstructionOptions {
  return {
    // Typography
    fontSize: 14,
    fontFamily:
      "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace",
    fontLigatures: true,
    lineHeight: 24,
    letterSpacing: 0.3,

    // Layout
    minimap: { enabled: false },
    wordWrap: "on",
    scrollBeyondLastLine: false,
    padding: { top: 16, bottom: 16 },
    glyphMargin: false,
    folding: true,
    foldingHighlight: true,

    // Behavior
    smoothScrolling: true,
    cursorBlinking: "smooth",
    cursorSmoothCaretAnimation: "on",
    formatOnPaste: true,
    autoClosingBrackets: "always",
    autoClosingQuotes: "always",
    autoSurround: "languageDefined",
    tabSize: 4,
    insertSpaces: true,

    // Suggestions
    quickSuggestions: {
      other: true,
      comments: false,
      strings: false,
    },
    suggestOnTriggerCharacters: true,
    acceptSuggestionOnCommitCharacter: true,
    snippetSuggestions: "bottom",
    suggest: {
      showSnippets: true,
      showWords: false, // Don't suggest random words from file
      showKeywords: true,
      preview: true,
      shareSuggestSelections: true,
    },

    // Rendering
    renderWhitespace: "none",
    renderLineHighlight: "line",
    bracketPairColorization: {
      enabled: true,
      independentColorPoolPerBracketType: true,
    },
    guides: {
      bracketPairs: true,
      indentation: true,
    },

    // Overrides
    ...overrides,
  };
}

export default registerScriptTheme;
