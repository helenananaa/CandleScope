/** Keep each language's source separate, including an intentionally empty draft. */
export interface ScriptEditorDraft {
  initialSource: string | null;
  sources: Readonly<Record<string, string>>;
}

export function createScriptEditorDraft(source: string | undefined, saved: boolean): ScriptEditorDraft {
  return { initialSource: saved || source ? source ?? "" : null, sources: {} };
}

export function scriptEditorSource(draft: ScriptEditorDraft, language: string, starter: string): string {
  return draft.sources[language] ?? draft.initialSource ?? starter;
}

export function editScriptEditorSource(draft: ScriptEditorDraft, language: string, source: string): ScriptEditorDraft {
  if (!language) return { ...draft, initialSource: source };
  return { initialSource: null, sources: { ...draft.sources, [language]: source } };
}

export function switchScriptEditorLanguage(
  draft: ScriptEditorDraft, currentLanguage: string, currentSource: string,
  nextLanguage: string, nextStarter: string,
): ScriptEditorDraft {
  const sources = { ...draft.sources, [currentLanguage]: currentSource };
  return { initialSource: null, sources: { ...sources, [nextLanguage]: sources[nextLanguage] ?? nextStarter } };
}
