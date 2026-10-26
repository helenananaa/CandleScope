import { useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import UtcReplayStartInput from "../features/replay/components/UtcReplayStartInput.js";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

/** Exercise native datetime-local sanitization and the actual React event lifecycle. */
export async function checkTrainingInput() {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const controls: { replace?: (value: number | null) => void; published: Array<number | null> } = { published: [] };
  function Form() {
    const [value, setValue] = useState<number | null>(Date.UTC(2023, 0, 2, 3, 4));
    useLayoutEffect(() => { controls.replace = setValue; }, []);
    return <UtcReplayStartInput value={value} onChange={next => {
      controls.published.push(next);
      setValue(next);
    }} />;
  }
  try {
    flushSync(() => root.render(<Form />));
    const input = host.querySelector("input")!;
    input.focus();
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    const values = ["0002-01-02T03:04", "0020-01-02T03:04", "0202-01-02T03:04", "2024-01-02T03:04"];
    for (const value of values) {
      flushSync(() => {
        setValue.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await new Promise(resolve => setTimeout(resolve, 0));
      assert(input.value === value, `native year edit was erased: ${value} -> ${input.value}`);
      assert(document.activeElement === input, "date edit lost focus");
    }
    assert(controls.published[0] === null, "incomplete year must not publish a valid start");
    assert(controls.published.at(-1) === Date.UTC(2024, 0, 2, 3, 4), "completed year was not published");
    flushSync(() => controls.replace!(Date.UTC(2025, 1, 3, 4, 5)));
    assert(input.value === "2025-02-03T04:05", "external preset was not applied");
    flushSync(() => controls.replace!(null));
    assert(String(input.value) === "", "external clear was not applied");
    return { passed: true, checks: ["partial year preserved", "focus retained", "valid UTC published", "external preset applied", "external clear applied"] };
  } finally {
    flushSync(() => root.unmount());
    host.remove();
  }
}
