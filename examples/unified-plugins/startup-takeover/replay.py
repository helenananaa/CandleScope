"""Decorate the actual replay service used by the API and the data manager."""


def prepare(ctx):
    async def wrap(default, *args, **kwargs):
        runtime = await default(*args, **kwargs)
        if runtime.service is not None:
            service = runtime.service
            original = service.capabilities

            def capabilities():
                return {**original(), "startupTakeover": ctx.id}

            service.capabilities = capabilities
            ctx.track(lambda: setattr(service, "capabilities", original))
        return runtime

    ctx.wrap_factory("replay", wrap)


def activate(ctx):
    ctx.ensure_current()
