import assert from "node:assert/strict";
import test from "node:test";
import type { TrainingHubRuntime } from "../replay/useTrainingHub.js";
import { createTrainingRunDraft } from "../replay/trainingHubModel.js";
import { trainingHubCommands } from "./trainingHubCommands.js";

test("training creation acknowledges submission while the domain operation is still pending", async () => {
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  const draft = createTrainingRunDraft();
  let submitted: unknown;
  const runtime = { operation: null, draft, evaluation: { canSubmit: true }, items: [], actions: {
    createRun: (value: unknown) => { submitted = value; return pending; },
  } } as unknown as TrainingHubRuntime;
  const action = trainingHubCommands(runtime).commands.find((row) => row.name === "createRun")!;
  assert.equal(action.available?.(), true);
  const acknowledgement = action.execute({});
  assert.deepEqual(acknowledgement, { submitted: true });
  assert.equal(submitted, draft);
  finish(); await pending;
});
