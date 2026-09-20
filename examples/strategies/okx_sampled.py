def init(ctx):
    ctx.strategy.configure()


def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=0.001)
    if ctx.bar_index == 5:
        ctx.strategy.close("L")
