export function activate({ React, ui, id }) {
  function Shell({ fallback }) {
    return React.createElement("div", {
      "data-startup-shell": id,
      style: { display: "contents" },
    }, fallback);
  }

  ui.replaceSlot("shell", Shell);
}
