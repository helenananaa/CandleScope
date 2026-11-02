# Render output update ranges

`ExecuteBatchResult.meta.outputUpdate` optionally describes the scope of an
accepted output update. It supplements the existing Render IR and output-patch
protocol; input versions and output revisions remain separate. No SDK wire
model or plugin mathematical behavior changes.

The schema is `render.update-range/1`:

- `mode: "snapshot"`: adopt the complete current output. This includes seed,
  recovery, history correction, structural changes and unproven retained state.
  Its optional `range` describes the full retained host-time window, including
  the session prefix omitted by a sliding input window.
- `mode: "range"`, `range: {start, end}`: the inclusive range of displayed
  timestamps that changed. Both endpoints are nonnegative integer seconds.
  Replace this range, including deletions. Source bar time is insufficient:
  negative plot offsets can affect a previous displayed timestamp.
- `mode: "range"`, `range: null`: there is no changed timed output. Whole native
  drawing scenes are still authoritative replacements, as before.

The Pine bridge emits this metadata for realtime execution. With negotiated
output-stream revisions it derives a range from the same proven prefixes used for
RenderPatch, including both removed old points and appended new points. It does
not subtract an interval from source time, infer a regular calendar, or compare
complete output history on each tick. Changes to collection identities or record
headers conservatively request a snapshot. Object scenes are already delivered
whole and do not participate in timed range inference.
Without a proven output base, the full result requests a snapshot; it cannot
promise that only the current source-bar timestamp changed.

The host uses its existing `indicator.replace_range` envelope for a proven
range, slices every timed projection consistently, and omits the unused nested
full Render IR. Empty data in that range clears prior points and annotations.
Snapshot mode or an unknown/malformed update contract delivers the full current
snapshot. Plugins without this optional contract keep their existing behavior.
HTTP historical target ranges retain their existing independent contract.

This does not eliminate native `result()` materialization, change Pine formulas,
or establish native UI/public-market qualification. The contract is language
neutral; other runtimes may implement it without adopting Pine code.
