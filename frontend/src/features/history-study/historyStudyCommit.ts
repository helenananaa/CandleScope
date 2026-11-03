import type { HistoryStudyView } from "./historyStudyTypes.js";

export function sameStudyView(left: HistoryStudyView, right: HistoryStudyView): boolean {
  return left.revision === right.revision && left.active === right.active
    && left.cursorMs === right.cursorMs && left.study?.id === right.study?.id;
}

/** A lost acknowledgement is not proof that a write failed. Read the owning
 * service before retrying; only the exact unchanged revision permits one retry.
 * Conflicting writers and unavailable reads leave the caller masked. */
export async function commitStudyView({ before, write, read, matches, uncertain, current }: {
  before: HistoryStudyView;
  write: () => Promise<HistoryStudyView>;
  read: () => Promise<HistoryStudyView>;
  matches: (view: HistoryStudyView) => boolean;
  uncertain: () => void;
  current: () => boolean;
}): Promise<HistoryStudyView> {
  const validate = (view: HistoryStudyView) => {
    if (!current()) throw new Error("study_context_changed");
    if (view.revision !== before.revision + 1 || !matches(view)) throw new Error("study_commit_conflict");
    return view;
  };
  try { return validate(await write()); }
  catch (error) {
    if (!current()) throw error;
    uncertain();
    const authoritative = await read();
    if (!current()) throw new Error("study_context_changed");
    if (authoritative.revision === before.revision + 1 && matches(authoritative)) return authoritative;
    if (!sameStudyView(before, authoritative)) throw new Error("study_commit_conflict", { cause: error });
    // The immutable input id and expected revision are retained by write().
    return validate(await write());
  }
}
