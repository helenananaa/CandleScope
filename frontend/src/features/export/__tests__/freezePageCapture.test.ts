import assert from "node:assert/strict";
import test from "node:test";
import { freezePageCapture } from "../freezePageCapture.js";

class ElementStub {
  childNodes: ElementStub[] = [];
  styles = new Map<string, string>();
  style = { setProperty: (key: string, value: string) => this.styles.set(key, value) };
  textContent = "";
  cloneNode() { return new ElementStub(); }
  appendChild(child: ElementStub) { this.childNodes.push(child); }
}
class CanvasStub extends ElementStub {
  width = 20;
  height = 10;
  pixels = "frame-before-capture";
  override cloneNode() { return new CanvasStub(); }
  getContext() { return { drawImage: (source: CanvasStub) => { this.pixels = source.pixels; } }; }
}
class InputStub extends ElementStub {
  value = "";
  checked = false;
  override cloneNode() { return new InputStub(); }
}
class OtherFormStub extends ElementStub {}

test("page snapshot retains pixels, form state and styles when the live page updates", async () => {
  const globals = {
    Element: ElementStub,
    HTMLCanvasElement: CanvasStub,
    HTMLInputElement: InputStub,
    HTMLTextAreaElement: OtherFormStub,
    HTMLSelectElement: OtherFormStub,
    window: {
      getComputedStyle: (node: ElementStub) => Object.assign([...node.styles.keys()], {
        getPropertyValue: (key: string) => node.styles.get(key) ?? "",
      }),
    },
  };
  const descriptors = new Map(Object.keys(globals).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  try {
    for (const [key, value] of Object.entries(globals)) Object.defineProperty(globalThis, key, { configurable: true, value });
    const page = new ElementStub();
    const canvas = new CanvasStub();
    const input = new InputStub();
    input.value = "snapshot value";
    input.checked = true;
    canvas.styles.set("width", "20px");
    const excluded = new CanvasStub();
    page.childNodes = [canvas, input, excluded];
    const frozen = freezePageCapture(page as unknown as HTMLElement, (node) => node !== (excluded as unknown as HTMLElement)) as unknown as ElementStub;
    await Promise.resolve(); // Simulate the asynchronous DOM/image encoding boundary.
    canvas.pixels = "live frame after capture";
    canvas.styles.set("width", "100px");
    input.value = "live value";
    input.checked = false;
    page.childNodes = [];
    assert.equal(frozen.childNodes.length, 2);
    assert.equal((frozen.childNodes[0] as CanvasStub).pixels, "frame-before-capture");
    assert.equal(frozen.childNodes[0]?.styles.get("width"), "20px");
    assert.equal((frozen.childNodes[1] as InputStub).value, "snapshot value");
    assert.equal((frozen.childNodes[1] as InputStub).checked, true);
  } finally {
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});
