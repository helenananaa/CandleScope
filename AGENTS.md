# Development policy

## Pyne is retired

Pyne was removed from CandleScope in PR #105. Future development must not
maintain Pyne or provide backward compatibility for old Pyne scripts or runtimes.

- Do not restore Pyne engines, plugins, editors, execution routes, build inputs,
  release bundles, compatibility shims, or automatic migration to another language.
- Reject unsupported legacy Pyne scripts and runtimes explicitly. Do not silently
  relabel or execute them as Pine or Python. Preserve original user data and
  historical QA evidence; retirement does not authorize deleting that evidence.
- When updating or merging older branches, preserve Pyne removal and discard
  obsolete Pyne support instead of resolving conflicts by restoring it.
- Keep shared infrastructure language-neutral. Pine, Python strategies, frontend
  JavaScript indicators, and supported community plugins retain their own contracts.
- Keep regression checks that reject retired Pyne entry points and prevent old
  installed runtimes from starting. These checks enforce removal, not compatibility.
