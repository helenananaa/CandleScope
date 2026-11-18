"""Inject a replay service before the DataManager binds its consumers."""

from app.replay.service import ReplayService


def prepare(ctx):
    class TakeoverReplayService(ReplayService):
        def capabilities(self):
            return {**super().capabilities(), "startupTakeover": ctx.id}

    async def wrap(default, *args, **kwargs):
        return await default(*args, **{**kwargs, "service_factory": TakeoverReplayService})

    ctx.wrap_factory("replay", wrap)


def activate(ctx):
    ctx.ensure_current()
