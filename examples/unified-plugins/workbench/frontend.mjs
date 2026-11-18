export function activate(context) {
  context.services.register("workbench", { identity: context.identity, entryId: context.entryId });
  context.commands.register("probe", (input) => ({ identity: context.identity, input }));
}
