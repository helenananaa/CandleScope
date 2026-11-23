export function activate(context) {
  context.services.register("workbench", { identity: context.identity, entryId: context.entryId });
  context.commands.register("probe", (input) => ({ identity: context.identity, input }));
  context.commands.register("chart-probe", async (chartId) => {
    const scope = context.charts.list().find((chart) => chart.chartId === chartId);
    if (!scope) throw new Error("Chart observation is unavailable");
    return context.charts.invoke(scope, "services", null);
  });
}
